#!/usr/bin/env python3
"""Octagon Oracle Monitor — orchestrator matching PIPELINE.md.

Calls modules:
  fetch_events.py       → step 0 (refresh upcoming)
  extract_transcript.py → step 3 (whisper/captions)
  classify.py           → step 4 (is it a prediction?)
  extract_predictions.py→ step 5 (extract picks)
  score.py              → step 0a (score after results)
"""

import json
import logging
import subprocess
import time
from datetime import datetime, date

from models import SessionLocal, Channel, Video, Event, Fight, Prediction
from extract_transcript import extract_transcript, _yt_dlp_base_args
from extract_predictions import extract_predictions
from classify import classify_video
from score import score_unscored
from fetch_events import refresh_upcoming

log = logging.getLogger("monitor")


# ── Step 2: Scan channel ────────────────────────────────────

def _scan_channel(channel: Channel) -> dict | None:
    """Fetch latest video from a YouTube channel."""
    log.info("Scanning: %s", channel.name)
    t0 = time.time()

    args = _yt_dlp_base_args() + [
        "--flat-playlist", "--playlist-end", "1",
        "--dump-json", channel.youtube_url,
    ]

    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        log.error("Failed to scan %s: %s", channel.name, result.stderr[:200])
        return None

    for line in result.stdout.strip().split("\n"):
        if line.strip():
            try:
                video = json.loads(line)
                log.info("  Latest: \"%s\" (%s) (%.1fs)",
                         video.get("title", "?")[:60], video.get("id", "?"), time.time() - t0)
                return video
            except json.JSONDecodeError:
                continue
    return None


# ── Steps 3-5: Process a single video ───────────────────────

def _process_video(session, vid_id: str, video_url: str, video_title: str,
                   channel: Channel, upcoming: Event) -> bool:
    """
    Step 3: Transcript (in memory)
    Step 4: Classify (is it a prediction video?)
    Step 5: Extract picks + save to DB
    """
    log.info("Processing: [%s] \"%s\" (%s)", channel.name, video_title[:60], vid_id)
    t0 = time.time()

    # Step 3: Transcript (in memory only)
    log.info("  Step 3: Transcribing...")
    transcript = extract_transcript(video_url, method="auto")
    transcript_text = transcript["full_text"]
    log.info("  Transcript: %d chars via %s", len(transcript_text), transcript.get("transcript_method"))

    # Step 4: Classify
    log.info("  Step 4: Classifying...")
    is_prediction = classify_video(transcript_text)

    if not is_prediction:
        session.add(Video(
            video_id=vid_id, channel_id=channel.id,
            title=video_title, is_prediction=False,
        ))
        session.commit()
        log.info("  Not a prediction video — skipped")
        return False

    # Step 5: Extract picks
    log.info("  Step 5: Extracting picks...")
    fights = session.query(Fight).filter_by(event_id=upcoming.id).all()
    fight_card = [{"fighter1": f.fighter1, "fighter2": f.fighter2} for f in fights]

    predictions = extract_predictions(
        transcript_text, video_title,
        transcript.get("uploader", channel.name),
        fight_card=fight_card,
    )

    if not predictions:
        session.add(Video(
            video_id=vid_id, channel_id=channel.id,
            title=video_title, is_prediction=False,
        ))
        session.commit()
        log.info("  No predictions extracted — saved as non-prediction")
        return False

    # Save video WITH transcript
    upload_date = None
    if transcript.get("upload_date"):
        try:
            upload_date = datetime.strptime(transcript["upload_date"], "%Y%m%d").date()
        except (ValueError, TypeError):
            pass

    video = Video(
        video_id=vid_id, channel_id=channel.id,
        title=video_title, upload_date=upload_date,
        is_prediction=True, transcript=transcript_text,
        transcript_method=transcript.get("transcript_method"),
    )
    session.add(video)
    session.flush()

    for p in predictions:
        session.add(Prediction(
            video_id=video.id, event_id=upcoming.id,
            fighter_picked=p["fighter_picked"],
            fighter_against=p["fighter_against"],
            method=p.get("method"),
            confidence=p.get("confidence", "medium"),
        ))

    session.commit()
    log.info("  Saved %d predictions (%.1fs total)", len(predictions), time.time() - t0)
    return True


# ── Main loop ────────────────────────────────────────────────

def run_once(session):
    """One full monitor cycle matching PIPELINE.md."""

    # Step 0: Refresh upcoming events from Wikipedia
    log.info("Step 0: Refreshing events...")
    refresh_upcoming(session)

    # Step 0a: Score unscored predictions
    score_unscored(session)

    # Step 1: Get upcoming event
    upcoming = session.query(Event).filter(
        Event.date >= date.today()
    ).order_by(Event.date).first()

    if not upcoming:
        log.info("No upcoming event — skipping cycle")
        return

    log.info("Step 1: Upcoming event: %s (%s)", upcoming.name, upcoming.date)

    # Step 2: Scan channels
    channels = session.query(Channel).all()
    log.info("Step 2: Scanning %d channels...", len(channels))

    new_count = 0

    for channel in channels:
        video = _scan_channel(channel)
        if not video:
            continue

        vid_id = video.get("id")
        title = video.get("title", "")
        if not vid_id:
            continue

        if session.query(Video).filter_by(video_id=vid_id).first():
            continue

        video_url = f"https://www.youtube.com/watch?v={vid_id}"
        try:
            if _process_video(session, vid_id, video_url, title, channel, upcoming):
                new_count += 1
        except Exception as e:
            log.error("Failed to process %s: %s", vid_id, e, exc_info=True)
            session.add(Video(video_id=vid_id, channel_id=channel.id,
                              title=title, is_prediction=False))
            session.commit()

    if new_count:
        log.info("=" * 50)
        log.info("CYCLE COMPLETE — %d new prediction(s)", new_count)
        log.info("=" * 50)
    else:
        log.info("No new prediction videos this cycle")


def monitor(interval_min: int = 15):
    """Run the monitor loop indefinitely."""
    session = SessionLocal()

    log.info("=" * 60)
    log.info("  OCTAGON ORACLE MONITOR")
    log.info("  Interval: %d min", interval_min)
    log.info("=" * 60)

    while True:
        try:
            log.info("")
            log.info("--- Scan cycle at %s ---", time.strftime("%Y-%m-%d %H:%M:%S"))
            run_once(session)
        except Exception as e:
            log.error("Cycle failed: %s", e, exc_info=True)
            session.rollback()

        log.info("Next scan in %d minutes...", interval_min)
        time.sleep(interval_min * 60)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Octagon Oracle Monitor")
    parser.add_argument("--interval", type=int, default=15, help="Minutes between scans")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.once:
        session = SessionLocal()
        run_once(session)
    else:
        monitor(interval_min=args.interval)
