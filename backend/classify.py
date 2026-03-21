"""Classify whether a transcript is a UFC prediction video.

Runs 4 models in parallel, majority vote decides.
"""

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("classify")

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

MODELS = [
    "deepseek/deepseek-v3.2",
    "google/gemini-2.5-flash-lite",
    "meta-llama/llama-3.3-70b-instruct",
]

SYSTEM_PROMPT = "Answer only 'yes' or 'no'. A prediction video is one where someone picks winners for upcoming UFC fights. Look for phrases like 'I'm going with', 'my pick is', 'prediction', 'I think X beats Y', 'breakdown', etc."

USER_PROMPT = "Is this a UFC prediction video where someone picks winners for upcoming fights?\n\n{sample}"


def _classify_with_model(model: str, sample: str) -> tuple[str, bool | None]:
    """Run classification with a single model. Returns (model_name, result)."""
    try:
        t0 = time.time()
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": USER_PROMPT.format(sample=sample)},
                ],
                "temperature": 0.0,
                "max_tokens": 5,
            },
            timeout=30,
        )

        if response.status_code != 200:
            log.warning("[%s] HTTP %d", model, response.status_code)
            return model, None

        content = response.json()["choices"][0]["message"]["content"].strip().lower()
        result = "yes" in content
        log.info("[%s] %s (%.1fs)", model, "YES" if result else "NO", time.time() - t0)
        return model, result

    except Exception as e:
        log.warning("[%s] Failed: %s", model, e)
        return model, None


def classify_video(transcript_text: str) -> bool:
    """Run classification across all models, majority vote.

    Returns True if majority say it's a prediction video.
    """
    sample = transcript_text[:2000]
    log.info("Classifying with %d models...", len(MODELS))
    t0 = time.time()

    results = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(_classify_with_model, m, sample): m for m in MODELS}
        for future in as_completed(futures):
            model, result = future.result()
            if result is not None:
                results[model] = result

    yes_count = sum(1 for v in results.values() if v)
    total = len(results)
    is_prediction = yes_count > total / 2

    log.info("Vote: %d/%d YES → %s (%.1fs)",
             yes_count, total, "PREDICTION" if is_prediction else "NOT PREDICTION", time.time() - t0)

    return is_prediction
