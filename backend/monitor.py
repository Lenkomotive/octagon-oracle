#!/usr/bin/env python3
"""Octagon Oracle Monitor — watches YouTube channels for new UFC prediction
videos, extracts transcripts and predictions, scores them. All data in Postgres."""

import json
import logging
import os
import subprocess
import time
from datetime import datetime

from models import SessionLocal, Channel, Video, Event, Fight, Prediction, Score
from extract_transcript import extract_transcript, _yt_dlp_base_args
from fetch_card import detect_event_from_title

log = logging.getLogger("monitor")


# ── Channel scanning ────────────────────────────────────────

def _scan_channel(channel: Channel) -> list[dict]:
    """Fetch latest video from a YouTube channel."""
    log.info("Scanning channel: %s (%s)", channel.name, channel.youtube_url)
    t0 = time.time()

    args = _yt_dlp_base_args() + [
        "--flat-playlist",
        "--playlist-end", "1",
        "--dump-json",
        channel.youtube_url,
    ]

    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        log.error("Failed to scan %s: %s", channel.name, result.stderr[:300])
        return []

    videos = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            videos.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    log.info("Found %d video(s) from %s (%.1fs)", len(videos), channel.name, time.time() - t0)
    return videos


SKIP_KEYWORDS = ["recap", "reaction", "results", "responds", "reacts", "interview", "news"]


def _classify_video(title: str, keywords_str: str, upcoming_event_name: str = None) -> str:
    """Classify a video: 'prediction', 'skip', or 'uncertain'.

    Rules:
    1. Title contains skip keywords (recap, reaction) → skip
    2. Title contains prediction keywords → prediction
    3. Title mentions upcoming event → prediction
    4. Otherwise → uncertain (needs transcript check)
    """
    title_lower = title.lower()

    # Skip obvious non-predictions
    if any(kw in title_lower for kw in SKIP_KEYWORDS):
        return "skip"

    # Check prediction keywords
    keywords = [k.strip() for k in keywords_str.split(",")] if keywords_str else ["predictions", "picks"]
    if any(kw.lower() in title_lower for kw in keywords):
        return "prediction"

    # Check if title mentions the upcoming event
    if upcoming_event_name:
        # Extract key parts: "UFC 328" → ["ufc", "328"]
        import re
        parts = re.findall(r'\w+', upcoming_event_name.lower())
        if all(p in title_lower for p in parts if len(p) > 2):
            return "prediction"

    return "uncertain"


def _classify_by_transcript_sample(video_url: str, video_id: str) -> bool:
    """Grab first 60s of captions and ask LLM if it's a prediction video."""
    import requests as req
    from dotenv import load_dotenv
    load_dotenv()

    captions = _fetch_youtube_captions_sample(video_url, video_id)
    if not captions:
        return False

    OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
    if not OPENROUTER_API_KEY:
        return False

    response = req.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "deepseek/deepseek-chat-v3-0324",
            "messages": [
                {"role": "system", "content": "Answer only 'yes' or 'no'."},
                {"role": "user", "content": f"Is this the beginning of a video where someone makes fight predictions for an upcoming UFC event? First 500 chars:\n\n{captions[:500]}"},
            ],
            "temperature": 0.0,
            "max_tokens": 5,
        },
    )

    if response.status_code != 200:
        return False

    answer = response.json()["choices"][0]["message"]["content"].strip().lower()
    log.info("LLM classification for %s: %s", video_id, answer)
    return "yes" in answer


def _fetch_youtube_captions_sample(video_url: str, video_id: str) -> str | None:
    """Fetch just the first portion of YouTube auto-captions."""
    from extract_transcript import _fetch_youtube_captions
    try:
        text = _fetch_youtube_captions(video_url, video_id)
        return text[:1000] if text else None
    except Exception:
        return None


# ── Event matching ──────────────────────────────────────────

def _match_event(session, video_title: str) -> Event | None:
    """Try to match a video title to an event in the DB."""
    event_name = detect_event_from_title(video_title)
    if not event_name:
        return None

    # Try exact-ish match on event name
    event = session.query(Event).filter(Event.name.ilike(f"%{event_name}%")).first()
    if event:
        log.info("Matched event: %s -> %s", event_name, event.name)
        return event

    # Try matching numbered events like "UFC 326"
    import re
    m = re.search(r'UFC\s+(\d+)', event_name, re.IGNORECASE)
    if m:
        num = m.group(1)
        event = session.query(Event).filter(Event.name.ilike(f"%UFC {num}%")).first()
        if event:
            log.info("Matched event by number: UFC %s -> %s", num, event.name)
            return event

    log.warning("No event match found for: %s", event_name)
    return None


# ── Prediction extraction (DB-native) ──────────────────────

def _extract_predictions_db(session, transcript_text: str, video_title: str,
                            uploader: str, event: Event | None) -> list[dict]:
    """Call LLM to extract predictions, using fight names from DB."""
    import requests
    from dotenv import load_dotenv
    load_dotenv()

    OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
    MODEL = "deepseek/deepseek-chat-v3-0324"

    SYSTEM_PROMPT = """You are a UFC prediction extractor. Given a transcript from a YouTube video where someone discusses upcoming UFC fights and makes predictions, extract all fight predictions.

For each prediction, extract:
- "fighter_picked": the fighter the YouTuber thinks will win
- "fighter_against": the opponent
- "method": predicted method of victory if mentioned (e.g. "KO", "submission", "decision"), or null if not specified
- "confidence": "high", "medium", or "low" based on how confident the YouTuber sounds, default to "medium" if unclear

IMPORTANT: If a fight card with correct fighter names is provided, you MUST use those exact names in your output. Match the transcript's (often misspelled/mispronounced) names to the closest fighter on the card. Every prediction should use a name from the fight card.

Return ONLY valid JSON in this exact format:
{
  "predictions": [
    {
      "fighter_picked": "Fighter Name",
      "fighter_against": "Opponent Name",
      "method": "KO" | "submission" | "decision" | null,
      "confidence": "high" | "medium" | "low"
    }
  ]
}

If no predictions are found, return {"predictions": []}.
Return ONLY the JSON, no other text."""

    user_content = f"Video title: {video_title}\nUploader: {uploader}\n\n"

    # Add fight card from DB if we have the event
    fights = []
    if event:
        fights = session.query(Fight).filter_by(event_id=event.id).all()
        if fights:
            fights_list = "\n".join(f"- {f.fighter1} vs {f.fighter2}" for f in fights)
            user_content += f"OFFICIAL FIGHT CARD (use these exact names):\n{fights_list}\n\n"

    user_content += f"Transcript:\n{transcript_text}"

    log.info("Calling LLM (model=%s)...", MODEL)
    t0 = time.time()

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.0,
        },
    )

    elapsed = time.time() - t0

    if response.status_code != 200:
        raise RuntimeError(f"OpenRouter error: {response.status_code} {response.text[:300]}")

    data = response.json()
    content = data["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1]
        content = content.rsplit("```", 1)[0].strip()

    usage = data.get("usage", {})
    log.info("LLM response: %d chars, %d prompt/%d completion tokens (%.1fs)",
             len(content), usage.get("prompt_tokens", 0),
             usage.get("completion_tokens", 0), elapsed)

    result = json.loads(content)

    # Validate names against card
    if fights:
        card_names = set()
        for f in fights:
            card_names.add(f.fighter1.lower().strip())
            card_names.add(f.fighter2.lower().strip())

        unmatched = []
        for p in result.get("predictions", []):
            if p["fighter_picked"].lower().strip() not in card_names:
                unmatched.append(p["fighter_picked"])
            if p["fighter_against"].lower().strip() not in card_names:
                unmatched.append(p["fighter_against"])

        if unmatched:
            log.warning("Unmatched names: %s — requesting correction", unmatched)
            fights_list = "\n".join(f"- {f.fighter1} vs {f.fighter2}" for f in fights)
            correction = f"""The following fighter names do NOT match anyone on the official fight card:
{', '.join(set(unmatched))}

Official fight card:
{fights_list}

Please fix the predictions to use the exact names from the fight card.
Return the complete corrected JSON (same format as before)."""

            response2 = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                        {"role": "assistant", "content": content},
                        {"role": "user", "content": correction},
                    ],
                    "temperature": 0.0,
                },
            )
            if response2.status_code == 200:
                content2 = response2.json()["choices"][0]["message"]["content"].strip()
                if content2.startswith("```"):
                    content2 = content2.split("\n", 1)[1]
                    content2 = content2.rsplit("```", 1)[0].strip()
                result = json.loads(content2)
                log.info("Correction applied")

    return result.get("predictions", [])


# ── Scoring (DB-native) ────────────────────────────────────

def _score_prediction(session, prediction: Prediction, event: Event) -> Score | None:
    """Score a single prediction against actual fight results."""
    fights = session.query(Fight).filter_by(event_id=event.id).all()

    picked_norm = prediction.fighter_picked.lower().strip()
    against_norm = prediction.fighter_against.lower().strip()

    for fight in fights:
        f1 = fight.fighter1.lower().strip()
        f2 = fight.fighter2.lower().strip()

        if picked_norm in (f1, f2) or against_norm in (f1, f2):
            if not fight.winner:
                return None  # fight hasn't happened yet

            correct = fight.winner.lower().strip() == picked_norm

            method_correct = None
            if prediction.method and fight.method:
                pm = prediction.method.lower()
                am = fight.method.lower()
                if pm == "ko":
                    method_correct = "ko" in am or "tko" in am
                elif pm == "submission":
                    method_correct = "sub" in am
                elif pm == "decision":
                    method_correct = "dec" in am

            score = Score(
                prediction_id=prediction.id,
                fight_id=fight.id,
                correct=correct,
                method_correct=method_correct,
            )

            icon = "CORRECT" if correct else "WRONG"
            log.info("  %s: %s over %s (actual: %s by %s)",
                     icon, prediction.fighter_picked, prediction.fighter_against,
                     fight.winner, fight.method)
            return score

    log.warning("  No matching fight for: %s vs %s", prediction.fighter_picked, prediction.fighter_against)
    return None


# ── Process a single video ───────────────────────────────────

def _process_video(session, vid_id: str, video_url: str, video_title: str,
                   channel: Channel, transcript_method: str) -> bool:
    """Process a single prediction video end-to-end. Returns True on success."""
    log.info("Processing: [%s] \"%s\" (%s)", channel.name, video_title[:70], vid_id)
    t0 = time.time()

    # 1. Match event
    event = _match_event(session, video_title)

    # 2. Transcript
    log.info("Step 1/3: Fetching transcript...")
    transcript = extract_transcript(video_url, method=transcript_method)

    # 3. Save video to DB
    upload_date = None
    if transcript.get("upload_date"):
        try:
            upload_date = datetime.strptime(transcript["upload_date"], "%Y%m%d").date()
        except (ValueError, TypeError):
            pass

    video = Video(
        video_id=vid_id,
        channel_id=channel.id,
        title=video_title,
        upload_date=upload_date,
        is_prediction=True,
        transcript=transcript["full_text"],
        transcript_method=transcript.get("transcript_method", "unknown"),
    )
    session.add(video)
    session.flush()

    # 4. Extract predictions
    log.info("Step 2/3: Extracting predictions...")
    raw_predictions = _extract_predictions_db(
        session, transcript["full_text"], video_title,
        transcript.get("uploader", channel.name), event,
    )

    # 5. Save predictions to DB
    predictions = []
    for p in raw_predictions:
        pred = Prediction(
            video_id=video.id,
            event_id=event.id if event else None,
            fighter_picked=p["fighter_picked"],
            fighter_against=p["fighter_against"],
            method=p.get("method"),
            confidence=p.get("confidence", "medium"),
        )
        session.add(pred)
        predictions.append(pred)
    session.flush()

    # 6. Score predictions
    log.info("Step 3/3: Scoring predictions...")
    correct = 0
    total = 0
    if event:
        for pred in predictions:
            score = _score_prediction(session, pred, event)
            if score:
                session.add(score)
                total += 1
                if score.correct:
                    correct += 1

    session.commit()

    accuracy = (correct / total * 100) if total > 0 else 0
    log.info("Done: %d predictions, %d/%d correct (%.1f%%) from %s (%.1fs)",
             len(predictions), correct, total, accuracy, channel.name, time.time() - t0)
    return True


# ── Main loop ────────────────────────────────────────────────

def _get_upcoming_event(session) -> Event | None:
    """Find the next upcoming event (date >= today)."""
    from datetime import date
    event = session.query(Event).filter(Event.date >= date.today()).order_by(Event.date).first()
    return event


def _score_unscored(session):
    """Score any predictions that don't have scores yet (results came in after prediction)."""
    unscored = session.query(Prediction).filter(
        Prediction.event_id.isnot(None),
        ~Prediction.score.has(),
    ).all()

    if not unscored:
        return

    log.info("Found %d unscored predictions, scoring...", len(unscored))
    for pred in unscored:
        event = session.query(Event).get(pred.event_id)
        if event:
            score = _score_prediction(session, pred, event)
            if score:
                session.add(score)

    session.commit()


def run_once(session, transcript_method: str = "auto"):
    """Run one scan cycle across all channels."""

    # Step 0: Score any unscored predictions (results may have come in)
    _score_unscored(session)

    # Step 1: Check for upcoming event
    upcoming = _get_upcoming_event(session)
    if not upcoming:
        log.info("No upcoming event found — skipping cycle")
        return

    log.info("Upcoming event: %s (%s)", upcoming.name, upcoming.date)

    # Step 2: Scan channels (latest video only)
    channels = session.query(Channel).all()
    log.info("Scanning %d channels", len(channels))

    new_count = 0

    for channel in channels:
        videos = _scan_channel(channel)
        keywords = channel.keywords or "predictions,picks"

        for video in videos:
            vid_id = video.get("id")
            title = video.get("title", "")

            if not vid_id:
                continue

            # Already in DB? Skip
            existing = session.query(Video).filter_by(video_id=vid_id).first()
            if existing:
                continue

            # Step 3: Classify
            classification = _classify_video(title, keywords, upcoming.name)
            log.info("[%s] \"%s\" → %s", channel.name, title[:60], classification)

            if classification == "skip":
                # Save as non-prediction so we don't check again
                session.add(Video(video_id=vid_id, channel_id=channel.id,
                                  title=title, is_prediction=False))
                session.commit()
                continue

            if classification == "uncertain":
                # Quick LLM check on first 60s of captions
                video_url = f"https://www.youtube.com/watch?v={vid_id}"
                is_pred = _classify_by_transcript_sample(video_url, vid_id)
                if not is_pred:
                    log.info("  LLM says not a prediction video — skipping")
                    session.add(Video(video_id=vid_id, channel_id=channel.id,
                                      title=title, is_prediction=False))
                    session.commit()
                    continue

            # It's a prediction video — process it
            log.info("")
            log.info("=" * 50)
            log.info("NEW PREDICTION VIDEO FOUND")
            log.info("=" * 50)

            video_url = f"https://www.youtube.com/watch?v={vid_id}"
            try:
                success = _process_video(
                    session, vid_id, video_url, title,
                    channel, transcript_method,
                )
                if success:
                    new_count += 1
            except Exception as e:
                log.error("Failed to process %s: %s", vid_id, e, exc_info=True)
                session.add(Video(video_id=vid_id, channel_id=channel.id,
                                  title=title, is_prediction=False))
                session.commit()

    if new_count:
        log.info("")
        log.info("=" * 50)
        log.info("CYCLE COMPLETE — %d new video(s) processed", new_count)
        log.info("=" * 50)
    else:
        log.info("No new prediction videos found this cycle")


def monitor(interval_min: int = 15, transcript_method: str = "auto"):
    """Run the monitor loop indefinitely."""
    session = SessionLocal()
    channels = session.query(Channel).all()

    log.info("=" * 60)
    log.info("  OCTAGON ORACLE MONITOR")
    log.info("  Channels: %d", len(channels))
    log.info("  Interval: %d min", interval_min)
    log.info("  Transcript method: %s", transcript_method)
    log.info("  Models: whisper-large-v3 (Groq), deepseek/deepseek-chat-v3-0324 (OpenRouter)")
    log.info("  Storage: PostgreSQL")
    log.info("=" * 60)

    for ch in channels:
        log.info("  - %s", ch.name)

    while True:
        try:
            log.info("")
            log.info("--- Scan cycle starting at %s ---", time.strftime("%Y-%m-%d %H:%M:%S"))
            run_once(session, transcript_method)
        except Exception as e:
            log.error("Cycle failed: %s", e, exc_info=True)
            session.rollback()

        log.info("Next scan in %d minutes...", interval_min)
        time.sleep(interval_min * 60)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Octagon Oracle — monitor YouTube channels for UFC predictions")
    parser.add_argument("--interval", type=int, default=15,
                        help="Minutes between scans (default: 15)")
    parser.add_argument("--once", action="store_true",
                        help="Run one scan cycle and exit (no loop)")
    parser.add_argument("--method", default="auto",
                        choices=["auto", "whisper", "captions", "both"],
                        help="Transcript method (default: auto)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.once:
        session = SessionLocal()
        run_once(session, args.method)
    else:
        monitor(interval_min=args.interval, transcript_method=args.method)
