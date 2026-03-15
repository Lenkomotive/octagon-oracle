#!/usr/bin/env python3
"""Octagon Oracle Monitor — watches YouTube channels for new UFC prediction
videos, extracts transcripts and predictions on a recurring loop."""

import json
import logging
import os
import subprocess
import sys
import time

from extract_transcript import extract_transcript, _yt_dlp_base_args
from extract_predictions import extract_predictions
from fetch_card import detect_event_from_title
from fetch_all_results import get_event_list, fetch_event_results

log = logging.getLogger("monitor")

PROCESSED_PATH = os.path.join(os.path.dirname(__file__), "processed.json")
CHANNELS_PATH = os.path.join(os.path.dirname(__file__), "channels.json")


# ── Processed video tracking ────────────────────────────────

def _load_processed() -> set[str]:
    if os.path.isfile(PROCESSED_PATH):
        with open(PROCESSED_PATH) as f:
            return set(json.load(f))
    return set()


def _save_processed(processed: set[str]):
    with open(PROCESSED_PATH, "w") as f:
        json.dump(sorted(processed), f, indent=2)


# ── Channel scanning ────────────────────────────────────────

def _scan_channel(channel: dict, limit: int = 10) -> list[dict]:
    """Fetch recent videos from a YouTube channel. Returns list of video info dicts."""
    url = channel["url"]
    log.info("Scanning channel: %s (%s)", channel["name"], url)
    t0 = time.time()

    args = _yt_dlp_base_args() + [
        "--flat-playlist",
        "--playlist-end", str(limit),
        "--dump-json",
        url,
    ]

    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        log.error("Failed to scan %s: %s", channel["name"], result.stderr[:300])
        return []

    videos = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            videos.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    log.info("Found %d recent videos from %s (%.1fs)", len(videos), channel["name"], time.time() - t0)
    return videos


def _is_prediction_video(title: str, keywords: list[str]) -> bool:
    """Check if a video title suggests it contains UFC predictions."""
    title_lower = title.lower()
    return any(kw.lower() in title_lower for kw in keywords)


# ── Results lookup ────────────────────────────────────────────

def _find_results_file(event_name: str) -> str | None:
    """Find a local results file matching the event name. Returns path or None."""
    results_dir = os.path.join(os.path.dirname(__file__), "results")
    if not os.path.isdir(results_dir):
        return None

    event_lower = event_name.lower()

    # Check index first
    index_path = os.path.join(results_dir, "_index.json")
    if os.path.isfile(index_path):
        with open(index_path) as f:
            index = json.load(f)
        for entry in index:
            if event_lower in entry.get("name", "").lower():
                path = entry.get("file")
                if path and os.path.isfile(path):
                    return path

    # Fallback: fuzzy match on filenames
    for fname in os.listdir(results_dir):
        if not fname.endswith(".json") or fname.startswith("_"):
            continue
        # Compare normalized names
        fname_lower = fname.replace("_", " ").replace(".json", "").lower()
        # Check if key parts of event name appear in filename
        parts = [p for p in event_lower.replace("ufc", "").split() if len(p) > 2]
        if all(p in fname_lower for p in parts):
            return os.path.join(results_dir, fname)

    return None


def _get_results_for_event(event_name: str) -> str | None:
    """Find or fetch results for an event. Returns results file path or None."""
    # Try local first
    path = _find_results_file(event_name)
    if path:
        log.info("Found local results: %s -> %s", event_name, path)
        return path

    # Try fetching from ufcstats.com
    log.info("No local results for %s, checking ufcstats.com...", event_name)
    try:
        events = get_event_list(since_event="UFC 280")
        for ev in events:
            if event_name.lower() in ev["name"].lower():
                result = fetch_event_results(ev["ufcstats_url"])
                os.makedirs("results", exist_ok=True)
                slug = result["event"].replace(" ", "_").replace(":", "").replace(".", "")
                out_path = f"results/{slug}.json"
                with open(out_path, "w") as f:
                    json.dump(result, f, indent=2)
                log.info("Fetched and saved: %s -> %s", event_name, out_path)
                return out_path
    except Exception as e:
        log.error("Failed to fetch results for %s: %s", event_name, e)

    return None


# ── Process a single video ───────────────────────────────────

def _process_video(video_id: str, video_url: str, video_title: str,
                   channel_name: str, transcript_method: str) -> dict | None:
    """Process a single prediction video end-to-end. Returns predictions dict or None."""
    log.info("Processing: [%s] \"%s\" (%s)", channel_name, video_title[:70], video_id)
    t0 = time.time()

    # 1. Detect event
    event_name = detect_event_from_title(video_title)
    if not event_name:
        log.warning("Could not detect event from title: \"%s\" — processing without card", video_title)

    # 2. Get results file (used as fight list for name validation)
    results_path = None
    if event_name:
        results_path = _get_results_for_event(event_name)

    # 3. Transcript
    log.info("Step 1/2: Fetching transcript...")
    transcript = extract_transcript(video_url, method=transcript_method)

    os.makedirs("transcripts", exist_ok=True)
    t_path = f"transcripts/{transcript['video_id']}.json"
    with open(t_path, "w") as f:
        json.dump(transcript, f, indent=2)

    # 4. Extract predictions
    log.info("Step 2/2: Extracting predictions...")
    predictions = extract_predictions(t_path, results_path)

    os.makedirs("predictions", exist_ok=True)
    p_path = f"predictions/{video_id}.json"
    with open(p_path, "w") as f:
        json.dump(predictions, f, indent=2)

    n = len(predictions.get("predictions", []))
    log.info("Done: %d predictions from %s (%.1fs)", n, channel_name, time.time() - t0)
    return predictions


# ── Main loop ────────────────────────────────────────────────

def run_once(channels: list[dict], limit: int = 10, transcript_method: str = "auto"):
    """Run one scan cycle across all channels."""
    processed = _load_processed()
    log.info("Loaded %d previously processed video IDs", len(processed))

    new_count = 0
    results = []

    for channel in channels:
        videos = _scan_channel(channel, limit=limit)
        keywords = channel.get("keywords", ["predictions", "picks"])

        for video in videos:
            vid_id = video.get("id")
            title = video.get("title", "")

            if not vid_id:
                continue
            if vid_id in processed:
                log.debug("Already processed: %s", vid_id)
                continue
            if not _is_prediction_video(title, keywords):
                log.debug("Not a prediction video: \"%s\"", title[:60])
                continue

            log.info("")
            log.info("=" * 50)
            log.info("NEW PREDICTION VIDEO FOUND")
            log.info("=" * 50)

            video_url = f"https://www.youtube.com/watch?v={vid_id}"
            try:
                predictions = _process_video(
                    vid_id, video_url, title,
                    channel["name"], transcript_method,
                )
                if predictions:
                    results.append(predictions)
                    new_count += 1
            except Exception as e:
                log.error("Failed to process %s: %s", vid_id, e, exc_info=True)

            # Mark as processed even on failure to avoid retry loops
            processed.add(vid_id)
            _save_processed(processed)

    # Summary
    if new_count:
        log.info("")
        log.info("=" * 50)
        log.info("CYCLE COMPLETE — %d new video(s) processed", new_count)
        log.info("=" * 50)
        for pred in results:
            log.info("")
            log.info("  %s — %s:", pred.get("uploader", "?"), pred.get("event", "?"))
            for p in pred.get("predictions", []):
                method = f" by {p['method']}" if p.get("method") else ""
                log.info("    %s over %s%s (%s)",
                         p["fighter_picked"], p["fighter_against"], method, p["confidence"])
    else:
        log.info("No new prediction videos found this cycle")

    return results


def monitor(interval_min: int = 15, transcript_method: str = "auto"):
    """Run the monitor loop indefinitely."""
    with open(CHANNELS_PATH) as f:
        config = json.load(f)

    channels = config["channels"]
    limit = config.get("check_last_n_videos", 10)

    log.info("=" * 60)
    log.info("  OCTAGON ORACLE MONITOR")
    log.info("  Channels: %d", len(channels))
    log.info("  Interval: %d min", interval_min)
    log.info("  Transcript method: %s", transcript_method)
    log.info("  Models: whisper-large-v3 (Groq), deepseek/deepseek-chat-v3-0324 (OpenRouter)")
    log.info("=" * 60)

    for ch in channels:
        log.info("  - %s (%s)", ch["name"], ", ".join(ch.get("keywords", [])))

    while True:
        try:
            log.info("")
            log.info("--- Scan cycle starting at %s ---", time.strftime("%Y-%m-%d %H:%M:%S"))
            run_once(channels, limit=limit, transcript_method=transcript_method)
        except Exception as e:
            log.error("Cycle failed: %s", e, exc_info=True)

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
    parser.add_argument("--reprocess", nargs="*",
                        help="Force reprocess specific video IDs")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Handle reprocessing
    if args.reprocess:
        processed = _load_processed()
        for vid in args.reprocess:
            processed.discard(vid)
            log.info("Unmarked for reprocessing: %s", vid)
        _save_processed(processed)

    if args.once:
        with open(CHANNELS_PATH) as f:
            config = json.load(f)
        run_once(config["channels"],
                 limit=config.get("check_last_n_videos", 10),
                 transcript_method=args.method)
    else:
        monitor(interval_min=args.interval, transcript_method=args.method)
