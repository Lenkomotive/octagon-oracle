import shutil
import subprocess
import json
import sys
import os


COOKIES_FILE = os.path.join(os.path.dirname(__file__), "cookies.txt")


def _find_node() -> str | None:
    """Find a Node.js >= 20 binary, preferring ~/.local/node/bin/node."""
    local_node = os.path.expanduser("~/.local/node/bin/node")
    if os.path.isfile(local_node):
        return local_node
    system_node = shutil.which("node")
    return system_node


def extract_transcript(video_url: str) -> dict:
    """Extract auto-generated subtitles from a YouTube video using yt-dlp."""
    args = [
        "yt-dlp",
        "--no-playlist",
        "--write-auto-sub",
        "--sub-lang", "en",
        "--sub-format", "json3",
        "--skip-download",
        "--print-json",
        "-o", "/tmp/oo_%(id)s",
    ]

    node_path = _find_node()
    if node_path:
        args += ["--js-runtimes", f"node:{node_path}"]

    if os.path.isfile(COOKIES_FILE):
        args += ["--cookies", COOKIES_FILE]

    args.append(video_url)

    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"yt-dlp error: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    info = json.loads(result.stdout)
    video_id = info.get("id", "unknown")

    # Look for the subtitle file yt-dlp wrote
    sub_file = f"/tmp/oo_{video_id}.en.json3"
    if not os.path.isfile(sub_file):
        print("No English subtitles found for this video.", file=sys.stderr)
        sys.exit(1)

    with open(sub_file) as f:
        subs_data = json.load(f)

    # Parse json3 format into clean transcript
    segments = []
    for event in subs_data.get("events", []):
        if "segs" not in event:
            continue
        text = "".join(seg.get("utf8", "") for seg in event["segs"]).strip()
        if not text:
            continue
        start_ms = event.get("tStartMs", 0)
        segments.append({
            "start": start_ms / 1000,
            "text": text,
        })

    output = {
        "video_id": video_id,
        "title": info.get("title", ""),
        "uploader": info.get("uploader", ""),
        "upload_date": info.get("upload_date", ""),
        "url": video_url,
        "segments": segments,
        "full_text": " ".join(s["text"] for s in segments),
    }

    return output


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_transcript.py <youtube_url>")
        sys.exit(1)

    transcript = extract_transcript(sys.argv[1])

    # Save to file
    out_path = f"transcripts/{transcript['video_id']}.json"
    os.makedirs("transcripts", exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(transcript, f, indent=2)

    print(f"Title: {transcript['title']}")
    print(f"Uploader: {transcript['uploader']}")
    print(f"Segments: {len(transcript['segments'])}")
    print(f"Saved to: {out_path}")
