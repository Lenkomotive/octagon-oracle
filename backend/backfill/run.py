#!/usr/bin/env python3
"""Backfill predictions for a YouTube channel using Claude Code as the LLM.

Usage:
    python backfill.py                          # Process THE MMA GURU
    python backfill.py --channel "Bedtime MMA"  # Process specific channel
    python backfill.py --limit 10               # Only first 10 videos

Outputs to backfill_results.json. Watch progress live in terminal.
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from extract_transcript import _yt_dlp_base_args, _fetch_youtube_captions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backfill")

CHANNELS = {
    "THE MMA GURU": "https://www.youtube.com/@the-mma-guru/videos",
    "Bedtime MMA": "https://www.youtube.com/@BedtimeMMA/videos",
    "KampfgeistMMA": "https://www.youtube.com/@KampfgeistMMA/videos",
    "We Want Picks": "https://www.youtube.com/@WeWantPicks/videos",
    "MMA EXPERTS": "https://www.youtube.com/@MMAEXPERTS/videos",
    "Artem MMA": "https://www.youtube.com/@artem_mma/videos",
    "Mighty Mouse": "https://www.youtube.com/@Mighty15x/videos",
    "Lucrative James": "https://www.youtube.com/@LucrativeJames/videos",
    "Walk The Line MMA": "https://www.youtube.com/@mmafortuneteller/videos",
    "HopperoMMA": "https://www.youtube.com/@hoppero-mma/videos",
    "MMA Joey C": "https://www.youtube.com/@MMAJoeyC/videos",
    "Locked Door MMA": "https://www.youtube.com/@LockedDoorMMA/videos",
    "The Weasle": "https://www.youtube.com/@theweaslemma/videos",
    "Bet Slam With Sam": "https://www.youtube.com/@BetSlamWithSam/videos",
    "Lorenzo Predicts": "https://www.youtube.com/@LorenzoPredicts/videos",
}

BACKFILL_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(BACKFILL_DIR, "results.json")


def _load_results() -> list[dict]:
    if os.path.isfile(OUTPUT_FILE):
        with open(OUTPUT_FILE) as f:
            return json.load(f)
    return []


def _save_results(results: list[dict]):
    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2)


def _get_video_list(channel_url: str, limit: int = 500) -> list[dict]:
    """Fetch video IDs and titles from channel."""
    log.info("Fetching video list (limit=%d)...", limit)
    args = _yt_dlp_base_args() + [
        "--flat-playlist", "--playlist-end", str(limit),
        "--print", "%(id)s|||%(title)s",
        channel_url,
    ]
    result = subprocess.run(args, capture_output=True, text=True, timeout=60)
    videos = []
    for line in result.stdout.strip().split("\n"):
        parts = line.split("|||", 1)
        if len(parts) == 2:
            videos.append({"id": parts[0], "title": parts[1]})
    return videos



def _detect_event(title: str, events: list[dict]) -> dict | None:
    """Match video title to a UFC event."""
    # Try UFC numbered event
    m = re.search(r"UFC\s+(\d+)", title, re.IGNORECASE)
    if m:
        num = m.group(1)
        for ev in events:
            if f"UFC {num}" in ev["name"]:
                return ev

    # Try fighter names (e.g. "Emmett vs Vallejos")
    m = re.search(r"(\w+)\s+vs\.?\s+(\w+)", title, re.IGNORECASE)
    if m:
        name1 = m.group(1).lower()
        name2 = m.group(2).lower()
        for ev in events:
            ev_lower = ev["name"].lower()
            if name1 in ev_lower and name2 in ev_lower:
                return ev

    # Try Vegas number
    m = re.search(r"UFC\s+Vegas\s+(\d+)", title, re.IGNORECASE)
    if m:
        for ev in events:
            if f"Vegas {m.group(1)}" in ev.get("name", ""):
                return ev

    return None


def _load_events() -> list[dict]:
    """Load events from local events.json (exported from DB)."""
    events_file = os.path.join(BACKFILL_DIR, "events.json")
    with open(events_file) as f:
        return json.load(f)


def _get_captions(video_id: str) -> str | None:
    """Get YouTube auto-captions for a video."""
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    return _fetch_youtube_captions(video_url, video_id)


def _extract_with_claude(video_id: str, title: str, channel: str,
                         event_name: str, fight_card: list[dict],
                         transcript: str) -> dict | None:
    """Call claude -p to extract predictions."""
    card_text = "\n".join(f"- {f['fighter1']} vs {f['fighter2']}" for f in fight_card)

    prompt = f"""You are a UFC prediction extractor. Extract all fight predictions from this transcript.

Video: "{title}" by {channel}
Event: {event_name}

OFFICIAL FIGHT CARD (use these exact fighter names):
{card_text}

For each prediction, extract:
- fighter_picked: who they pick to win (MUST match a name from the card)
- fighter_against: the opponent (MUST match a name from the card)
- method: KO, submission, decision, or null
- confidence: high, medium, or low

Return ONLY this JSON, nothing else:
{{"video_id": "{video_id}", "title": "{title}", "channel": "{channel}", "event": "{event_name}", "predictions": [{{"fighter_picked": "...", "fighter_against": "...", "method": "...", "confidence": "..."}}]}}

TRANSCRIPT:
{transcript}"""

    # Write prompt to temp file to avoid shell escaping
    prompt_file = f"/tmp/oo_bf_{video_id}.txt"
    with open(prompt_file, "w") as f:
        f.write(prompt)

    try:
        result = subprocess.run(
            ["claude", "-p", "--output-format", "json"],
            stdin=open(prompt_file),
            capture_output=True, text=True,
            timeout=120,
        )

        os.remove(prompt_file)

        if result.returncode != 0:
            log.error("  Claude error: %s", result.stderr[:200])
            return None

        raw = result.stdout.strip()
        # Find JSON in response
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(raw[start:end])

        return None

    except subprocess.TimeoutExpired:
        log.error("  Claude timed out")
        os.remove(prompt_file)
        return None
    except Exception as e:
        log.error("  Claude failed: %s", e)
        if os.path.isfile(prompt_file):
            os.remove(prompt_file)
        return None


def backfill(channel_name: str, channel_url: str, limit: int = 500):
    """Run backfill for a single channel."""
    log.info("=" * 60)
    log.info("BACKFILL: %s", channel_name)
    log.info("=" * 60)

    # Load existing results
    results = _load_results()
    processed_ids = {r["video_id"] for r in results}

    # Get video list
    videos = _get_video_list(channel_url, limit)
    log.info("Found %d total videos", len(videos))

    pred_videos = videos
    log.info("Videos to process: %d", len(pred_videos))

    # Load events from local JSON (exported from DB)
    all_events = _load_events()
    log.info("Loaded %d events from events.json", len(all_events))

    new_count = 0

    for i, video in enumerate(pred_videos):
        vid_id = video["id"]
        title = video["title"]

        # Skip if already done
        if vid_id in processed_ids:
            log.info("[%d/%d] SKIP: %s", i + 1, len(pred_videos), title[:60])
            continue

        log.info("")
        log.info("=" * 50)
        log.info("[%d/%d] %s", i + 1, len(pred_videos), title[:70])
        log.info("  ID: %s", vid_id)

        # Detect event
        event = _detect_event(title, all_events)
        if not event:
            log.warning("  Could not detect event — skipping")
            continue
        log.info("  Event: %s", event["name"])

        # Get fight card from event data
        fights = event.get("fights")
        if not fights:
            log.warning("  No fight card found — skipping")
            continue
        log.info("  Card: %d fights", len(fights))

        # Get captions
        log.info("  Fetching captions...")
        transcript = _get_captions(vid_id)
        if not transcript or len(transcript) < 500:
            log.warning("  No captions or too short — skipping")
            continue
        log.info("  Transcript: %d chars", len(transcript))

        # Extract with Claude
        log.info("  Extracting predictions with Claude...")
        result = _extract_with_claude(
            vid_id, title, channel_name,
            event["name"], fights, transcript,
        )

        if result and result.get("predictions"):
            results.append(result)
            _save_results(results)
            processed_ids.add(vid_id)
            n = len(result["predictions"])
            log.info("  ✓ Saved %d predictions", n)
            for p in result["predictions"]:
                method = f" by {p['method']}" if p.get("method") else ""
                log.info("    %s over %s%s", p["fighter_picked"], p["fighter_against"], method)
            new_count += 1
        else:
            log.warning("  No predictions extracted")

        time.sleep(1)

    log.info("")
    log.info("=" * 60)
    log.info("BACKFILL COMPLETE: %d new videos processed", new_count)
    log.info("Total in %s: %d", OUTPUT_FILE, len(results))
    log.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill predictions using Claude Code")
    parser.add_argument("--channel", default=None, help="Channel name (default: all)")
    parser.add_argument("--all", action="store_true", help="Process all channels")
    parser.add_argument("--limit", type=int, default=500, help="Max videos to scan per channel")
    args = parser.parse_args()

    if args.all or args.channel is None:
        for name, url in CHANNELS.items():
            backfill(name, url, args.limit)
    else:
        channel_url = CHANNELS.get(args.channel)
        if not channel_url:
            print(f"Unknown channel: {args.channel}")
            print(f"Available: {', '.join(CHANNELS.keys())}")
            sys.exit(1)
        backfill(args.channel, channel_url, args.limit)
