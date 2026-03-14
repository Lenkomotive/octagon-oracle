import json
import logging
import time
import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
MODEL = "deepseek/deepseek-chat-v3-0324"

SYSTEM_PROMPT = """You are a UFC prediction extractor. Given a transcript from a YouTube video where someone discusses upcoming UFC fights and makes predictions, extract all fight predictions.

For each prediction, extract:
- "fighter_picked": the fighter the YouTuber thinks will win
- "fighter_against": the opponent
- "method": predicted method of victory if mentioned (e.g. "KO", "submission", "decision"), or null if not specified
- "confidence": "high", "medium", or "low" based on how confident the YouTuber sounds, default to "medium" if unclear

Also extract:
- "event": the UFC event name if mentioned (e.g. "UFC 315"), or null

IMPORTANT: If a fight card with correct fighter names is provided, you MUST use those exact names in your output. Match the transcript's (often misspelled/mispronounced) names to the closest fighter on the card. Every prediction should use a name from the fight card.

Return ONLY valid JSON in this exact format:
{
  "event": "UFC XXX",
  "predictions": [
    {
      "fighter_picked": "Fighter Name",
      "fighter_against": "Opponent Name",
      "method": "KO" | "submission" | "decision" | null,
      "confidence": "high" | "medium" | "low"
    }
  ]
}

If no predictions are found, return {"event": null, "predictions": []}.
Return ONLY the JSON, no other text."""

CORRECTION_PROMPT = """The following fighter names in your output do NOT match anyone on the official fight card:
{unmatched}

Official fight card:
{card_fights}

Please fix the predictions to use the exact names from the fight card. Match by closest name/pronunciation.
Return the complete corrected JSON (same format as before)."""


def _get_card_fighters(card: dict) -> dict[str, str]:
    """Build a lookup of normalized name -> original name from card."""
    fighters = {}
    for fight in card.get("fights", []):
        for key in ("fighter1", "fighter2"):
            name = fight[key]
            fighters[name.lower().strip()] = name
    return fighters


def _validate_against_card(predictions: dict, card: dict) -> list[str]:
    """Check all predicted fighter names exist on the card. Returns unmatched names."""
    card_fighters = _get_card_fighters(card)
    unmatched = []
    for p in predictions.get("predictions", []):
        if p["fighter_picked"].lower().strip() not in card_fighters:
            unmatched.append(p["fighter_picked"])
        if p["fighter_against"].lower().strip() not in card_fighters:
            unmatched.append(p["fighter_against"])
    return list(set(unmatched))


def _call_llm(messages: list[dict]) -> str:
    """Call OpenRouter LLM and return content string."""
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not set in environment")

    log.info("Calling LLM (model=%s, messages=%d)...", MODEL, len(messages))
    t0 = time.time()

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "messages": messages,
            "temperature": 0.0,
        },
    )

    elapsed = time.time() - t0

    if response.status_code != 200:
        log.error("OpenRouter error %d: %s", response.status_code, response.text[:300])
        raise RuntimeError(f"OpenRouter error: {response.status_code} {response.text[:300]}")

    data = response.json()
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    log.info("LLM response: %d chars, %d prompt tokens, %d completion tokens (%.1fs)",
             len(content), usage.get("prompt_tokens", 0),
             usage.get("completion_tokens", 0), elapsed)
    return content


def _parse_json_response(content: str) -> dict:
    """Parse JSON from LLM response, handling markdown fences."""
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1]
        content = content.rsplit("```", 1)[0]
        content = content.strip()
    return json.loads(content)


def _load_fight_list(path: str) -> dict:
    """Load a results or card file and normalize to {event, fights} format."""
    with open(path) as f:
        data = json.load(f)

    # Results files have "results" key, card files have "fights" key
    if "results" in data and "fights" not in data:
        data["fights"] = [
            {"fighter1": r["fighter1"], "fighter2": r["fighter2"]}
            for r in data["results"]
        ]

    return data


def extract_predictions(transcript_path: str, card_path: str = None, max_retries: int = 2) -> dict:
    """
    Extract fight predictions from a transcript using LLM.

    card_path can be a card JSON or a results JSON — either works
    for fighter name validation.
    """
    log.info("=== Prediction extraction: %s ===", os.path.basename(transcript_path))
    t0 = time.time()

    with open(transcript_path) as f:
        transcript = json.load(f)

    log.info("Transcript: \"%s\" by %s (%d chars, method=%s)",
             transcript["title"], transcript["uploader"],
             len(transcript["full_text"]), transcript.get("transcript_method", "unknown"))

    # Load fight list (from card or results file)
    card = None
    if card_path:
        card = _load_fight_list(card_path)
        log.info("Fight list loaded: %s (%d fights)",
                 card.get("event", "?"), len(card.get("fights", [])))

    # Build user prompt
    user_content = f"Video title: {transcript['title']}\nUploader: {transcript['uploader']}\n\n"

    if card:
        fights_list = "\n".join(
            f"- {fight['fighter1']} vs {fight['fighter2']}"
            for fight in card.get("fights", [])
        )
        user_content += f"OFFICIAL FIGHT CARD (use these exact names):\n{fights_list}\n\n"

    # Use both transcript sources if available for cross-reference
    if transcript.get("captions_text") and transcript.get("whisper_text"):
        user_content += f"Transcript (Whisper):\n{transcript['whisper_text']}\n\n"
        user_content += f"Transcript (YouTube captions, for cross-reference):\n{transcript['captions_text']}"
        log.info("Using dual transcript sources for cross-reference")
    else:
        user_content += f"Transcript:\n{transcript['full_text']}"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    # Initial extraction
    content = _call_llm(messages)
    predictions = _parse_json_response(content)
    n = len(predictions.get("predictions", []))
    log.info("Extracted %d prediction(s)", n)
    messages.append({"role": "assistant", "content": content})

    # Validate against card and retry if needed
    if card:
        for attempt in range(max_retries):
            unmatched = _validate_against_card(predictions, card)
            if not unmatched:
                log.info("All fighter names validated against card")
                break

            log.warning("Unmatched names: %s — requesting correction (retry %d/%d)",
                        unmatched, attempt + 1, max_retries)
            card_fights = "\n".join(
                f"- {f['fighter1']} vs {f['fighter2']}"
                for f in card.get("fights", [])
            )
            correction = CORRECTION_PROMPT.format(
                unmatched=", ".join(unmatched),
                card_fights=card_fights,
            )
            messages.append({"role": "user", "content": correction})

            content = _call_llm(messages)
            predictions = _parse_json_response(content)
            messages.append({"role": "assistant", "content": content})
        else:
            remaining = _validate_against_card(predictions, card)
            if remaining:
                log.error("Still unmatched after %d retries: %s", max_retries, remaining)

    # Attach video metadata
    predictions["video_id"] = transcript["video_id"]
    predictions["uploader"] = predictions.get("uploader") or transcript["uploader"]
    predictions["title"] = transcript["title"]
    predictions["url"] = transcript["url"]

    log.info("Prediction extraction complete: %d picks (%.1fs total)",
             len(predictions["predictions"]), time.time() - t0)
    return predictions


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if len(sys.argv) < 2:
        print("Usage: python extract_predictions.py <transcript.json> [card.json]")
        sys.exit(1)

    card_path = sys.argv[2] if len(sys.argv) > 2 else None
    result = extract_predictions(sys.argv[1], card_path)

    out_path = f"predictions/{result['video_id']}.json"
    os.makedirs("predictions", exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)

    log.info("Saved to %s", out_path)
    for p in result["predictions"]:
        method = f" by {p['method']}" if p.get("method") else ""
        log.info("  %s over %s%s (%s)", p["fighter_picked"], p["fighter_against"], method, p["confidence"])
