"""Extract fight predictions from a transcript using LLM."""

import json
import logging
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("extract_predictions")

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
MODEL = "deepseek/deepseek-chat-v3-0324"

SYSTEM_PROMPT = """You are a UFC prediction extractor. Given a transcript from a YouTube video where someone discusses upcoming UFC fights and makes predictions, extract all fight predictions.

For each prediction, extract:
- "fighter_picked": the fighter the YouTuber thinks will win
- "fighter_against": the opponent
- "method": predicted method of victory if mentioned (e.g. "KO", "submission", "decision"), or null
- "confidence": "high", "medium", or "low" based on how confident they sound, default "medium"

IMPORTANT: If a fight card is provided, use those exact names. Match misspelled/mispronounced names to the closest fighter on the card.

Return ONLY valid JSON: {"predictions": [{"fighter_picked": "...", "fighter_against": "...", "method": "..." or null, "confidence": "..."}]}
If no predictions found, return {"predictions": []}."""


def _call_llm(messages: list[dict], max_tokens: int = 2000) -> str:
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
            "max_tokens": max_tokens,
        },
    )
    if response.status_code != 200:
        raise RuntimeError(f"OpenRouter error: {response.status_code} {response.text[:300]}")

    data = response.json()
    content = data["choices"][0]["message"]["content"].strip()
    usage = data.get("usage", {})
    log.info("LLM: %d chars, %d/%d tokens (%.1fs)",
             len(content), usage.get("prompt_tokens", 0),
             usage.get("completion_tokens", 0), time.time() - t0)
    return content


def _parse_json(content: str) -> dict:
    if content.startswith("```"):
        content = content.split("\n", 1)[1]
        content = content.rsplit("```", 1)[0].strip()
    return json.loads(content)


def extract_predictions(transcript_text: str, video_title: str, uploader: str,
                        fight_card: list[dict] = None, max_retries: int = 1) -> list[dict]:
    """Extract predictions from transcript text.

    Args:
        transcript_text: full transcript
        video_title: video title for context
        uploader: channel name
        fight_card: list of {"fighter1": ..., "fighter2": ...} dicts from DB
        max_retries: retries for name validation

    Returns:
        list of prediction dicts with fighter_picked, fighter_against, method, confidence
    """
    log.info("=== Extracting predictions ===")
    log.info("Title: \"%s\" by %s (%d chars)", video_title[:60], uploader, len(transcript_text))
    t0 = time.time()

    user_content = f"Video title: {video_title}\nUploader: {uploader}\n\n"

    if fight_card:
        fights_list = "\n".join(f"- {f['fighter1']} vs {f['fighter2']}" for f in fight_card)
        user_content += f"OFFICIAL FIGHT CARD (use these exact names):\n{fights_list}\n\n"
        log.info("Fight card: %d fights", len(fight_card))

    user_content += f"Transcript:\n{transcript_text}"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    content = _call_llm(messages)
    result = _parse_json(content)
    predictions = result.get("predictions", [])
    log.info("Extracted %d prediction(s)", len(predictions))

    # Validate names against card
    if fight_card and predictions:
        card_names = set()
        for f in fight_card:
            card_names.add(f["fighter1"].lower().strip())
            card_names.add(f["fighter2"].lower().strip())

        for attempt in range(max_retries):
            unmatched = []
            for p in predictions:
                if p["fighter_picked"].lower().strip() not in card_names:
                    unmatched.append(p["fighter_picked"])
                if p["fighter_against"].lower().strip() not in card_names:
                    unmatched.append(p["fighter_against"])

            if not unmatched:
                log.info("All names validated against card")
                break

            log.warning("Unmatched: %s — correction retry %d/%d", set(unmatched), attempt + 1, max_retries)
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": f"These names don't match the card: {', '.join(set(unmatched))}\n\nCard:\n{fights_list}\n\nFix and return corrected JSON."})
            content = _call_llm(messages)
            result = _parse_json(content)
            predictions = result.get("predictions", [])

    log.info("Extraction complete: %d picks (%.1fs)", len(predictions), time.time() - t0)
    return predictions
