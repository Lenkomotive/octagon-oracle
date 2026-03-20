import shutil
import subprocess
import json
import logging
import time
import sys
import os
import requests
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

COOKIES_FILE = os.path.join(os.path.dirname(__file__), "cookies.txt")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
WHISPER_MODEL = "whisper-large-v3"


def _find_node() -> str | None:
    """Find a Node.js >= 20 binary, preferring ~/.local/node/bin/node."""
    local_node = os.path.expanduser("~/.local/node/bin/node")
    if os.path.isfile(local_node):
        return local_node
    return shutil.which("node")


def _yt_dlp_base_args() -> list[str]:
    """Common yt-dlp arguments."""
    args = ["yt-dlp", "--no-playlist"]
    node_path = _find_node()
    if node_path:
        args += ["--js-runtimes", f"node:{node_path}"]
        log.debug("Using Node.js at %s", node_path)
    if os.path.isfile(COOKIES_FILE):
        args += ["--cookies", COOKIES_FILE]
        log.debug("Using cookies file: %s", COOKIES_FILE)
    return args


def _get_video_info(video_url: str) -> dict:
    """Get video metadata without downloading anything."""
    log.debug("Fetching video metadata: %s", video_url)
    t0 = time.time()
    args = _yt_dlp_base_args() + ["--dump-json", "--skip-download", video_url]
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp metadata failed: {result.stderr[:500]}")
    info = json.loads(result.stdout)
    log.info("Got video info: \"%s\" by %s (%.1fs)",
             info.get("title", "?"), info.get("uploader", "?"), time.time() - t0)
    return info


def _fetch_youtube_captions(video_url: str, video_id: str) -> str | None:
    """Fetch YouTube auto-captions via yt-dlp. Returns caption text or None."""
    log.info("Fetching YouTube auto-captions for %s...", video_id)
    t0 = time.time()
    out_template = f"/tmp/oo_{video_id}"
    args = _yt_dlp_base_args() + [
        "--write-auto-sub", "--sub-lang", "en",
        "--sub-format", "json3",
        "--skip-download",
        "-o", out_template,
        video_url,
    ]

    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        log.debug("yt-dlp captions stderr: %s", result.stderr[:300])

    sub_path = f"{out_template}.en.json3"
    if not os.path.isfile(sub_path):
        log.warning("No auto-captions available for %s", video_id)
        return None

    try:
        with open(sub_path) as f:
            sub_data = json.load(f)

        texts = []
        for event in sub_data.get("events", []):
            for seg in event.get("segs", []):
                text = seg.get("utf8", "").strip()
                if text and text != "\n":
                    texts.append(text)

        caption_text = " ".join(texts) if texts else None
        if caption_text:
            log.info("Captions OK: %d chars (%.1fs)", len(caption_text), time.time() - t0)
        else:
            log.warning("Captions file was empty for %s", video_id)
        return caption_text
    finally:
        if os.path.isfile(sub_path):
            os.remove(sub_path)


def _download_audio(video_url: str, video_id: str) -> str:
    """Download audio from YouTube video. Returns path to mp3 file."""
    log.info("Downloading audio for %s...", video_id)
    t0 = time.time()
    audio_path = f"/tmp/oo_{video_id}.mp3"

    args = _yt_dlp_base_args() + [
        "-x", "--audio-format", "mp3",
        "--audio-quality", "5",
        "-o", f"/tmp/oo_{video_id}.%(ext)s",
        video_url,
    ]

    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp audio download failed: {result.stderr[:500]}")

    if not os.path.isfile(audio_path):
        raise RuntimeError(f"Audio file not found at {audio_path}")

    size_mb = os.path.getsize(audio_path) / (1024 * 1024)
    log.info("Audio downloaded: %.1fMB (%.1fs)", size_mb, time.time() - t0)
    return audio_path


def _transcribe_with_groq(audio_path: str) -> dict:
    """Transcribe audio using Groq's Whisper API."""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not set in environment")

    file_size = os.path.getsize(audio_path)
    if file_size > 25 * 1024 * 1024:
        raise RuntimeError(f"Audio too large ({file_size // 1024 // 1024}MB). Groq limit is 25MB.")

    log.info("Sending to Groq Whisper (model=%s, size=%.1fMB)...",
             WHISPER_MODEL, file_size / (1024 * 1024))
    t0 = time.time()

    with open(audio_path, "rb") as f:
        response = requests.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            files={"file": (os.path.basename(audio_path), f, "audio/mpeg")},
            data={
                "model": WHISPER_MODEL,
                "response_format": "verbose_json",
                "language": "en",
            },
        )

    elapsed = time.time() - t0

    if response.status_code != 200:
        log.error("Groq API error %d: %s", response.status_code, response.text[:300])
        raise RuntimeError(f"Groq API error: {response.status_code} {response.text[:300]}")

    result = response.json()
    duration = result.get("duration", 0)
    n_segments = len(result.get("segments", []))
    log.info("Whisper done: %d segments, %.0fs audio transcribed in %.1fs",
             n_segments, duration, elapsed)
    return result


def extract_transcript(video_url: str, method: str = "auto") -> dict:
    """
    Extract transcript from a YouTube video.

    Methods:
      "auto"     - Whisper first, YouTube captions fallback
      "captions" - YouTube auto-captions only
      "whisper"  - Groq Whisper only
      "both"     - fetch both for cross-reference
    """
    log.info("=== Transcript extraction: method=%s ===", method)
    t0 = time.time()

    info = _get_video_info(video_url)
    video_id = info.get("id", "unknown")

    captions_text = None
    whisper_text = None
    whisper_segments = []

    # --- Whisper (primary) ---
    need_whisper = method in ("auto", "whisper", "both")
    if need_whisper:
        try:
            audio_path = _download_audio(video_url, video_id)
            whisper_result = _transcribe_with_groq(audio_path)
            os.remove(audio_path)
            log.debug("Cleaned up audio file: %s", audio_path)

            for seg in whisper_result.get("segments", []):
                text = seg.get("text", "").strip()
                if text:
                    whisper_segments.append({"start": seg.get("start", 0), "text": text})

            whisper_text = " ".join(s["text"] for s in whisper_segments)
        except Exception as e:
            log.error("Whisper failed for %s: %s", video_id, e)

    # --- YouTube captions (fallback) ---
    if method in ("captions", "both") or (method == "auto" and not whisper_text):
        try:
            captions_text = _fetch_youtube_captions(video_url, video_id)
        except Exception as e:
            log.error("Captions failed for %s: %s", video_id, e)

    # --- Pick best result ---
    if whisper_text:
        full_text = whisper_text
        segments = whisper_segments
        used_method = "whisper"
    elif captions_text:
        full_text = captions_text
        segments = [{"start": 0, "text": captions_text}]
        used_method = "captions"
    else:
        raise RuntimeError(f"No transcript obtained for {video_url}")

    output = {
        "video_id": video_id,
        "title": info.get("title", ""),
        "uploader": info.get("uploader", ""),
        "upload_date": info.get("upload_date", ""),
        "url": video_url,
        "transcript_method": used_method,
        "segments": segments,
        "full_text": full_text,
    }

    # When both sources available, include both for cross-reference
    if captions_text and whisper_text:
        output["captions_text"] = captions_text
        output["whisper_text"] = whisper_text
        output["transcript_method"] = "both"

    log.info("Transcript complete: method=%s, %d chars, %.1fs total",
             output["transcript_method"], len(full_text), time.time() - t0)
    return output


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if len(sys.argv) < 2:
        print("Usage: python extract_transcript.py <youtube_url> [method]")
        print("  methods: auto (default), captions, whisper, both")
        sys.exit(1)

    url = sys.argv[1]
    m = sys.argv[2] if len(sys.argv) > 2 else "auto"

    transcript = extract_transcript(url, method=m)

    out_path = f"transcripts/{transcript['video_id']}.json"
    os.makedirs("transcripts", exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(transcript, f, indent=2)

    log.info("Saved to %s", out_path)
