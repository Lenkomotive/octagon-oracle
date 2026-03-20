"""Classify whether a transcript is a UFC prediction video."""

import logging
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("classify")

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
MODEL = "deepseek/deepseek-chat-v3-0324"


def classify_video(transcript_text: str) -> bool:
    """LLM checks transcript: is this a prediction video for an upcoming UFC event?

    Uses first 1000 chars to save tokens.
    Returns True if prediction video, False otherwise.
    """
    sample = transcript_text[:1000]

    log.info("Classifying transcript (%d chars sample)...", len(sample))
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
                {"role": "system", "content": "Answer only 'yes' or 'no'."},
                {"role": "user", "content": f"Is this a video where someone makes fight predictions/picks for an upcoming UFC event? Transcript sample:\n\n{sample}"},
            ],
            "temperature": 0.0,
            "max_tokens": 5,
        },
    )

    if response.status_code != 200:
        log.error("LLM error: %d %s", response.status_code, response.text[:200])
        return False

    content = response.json()["choices"][0]["message"]["content"].strip().lower()
    is_prediction = "yes" in content

    log.info("Classification: %s (%.1fs)", "PREDICTION" if is_prediction else "NOT PREDICTION", time.time() - t0)
    return is_prediction
