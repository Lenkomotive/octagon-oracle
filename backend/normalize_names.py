"""Normalize fighter names from LLM outputs to official card names.

For each fight on the card, finds all matching names across model outputs
and maps them to the official names. Each fight is matched independently.
"""

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("normalize_names")

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
MODEL = "google/gemini-2.5-flash-lite"


def _match_fight(fighter1: str, fighter2: str, all_names: list[str]) -> dict[str, str]:
    """Ask LLM to match raw names to one fight's two fighters.

    Returns mapping of raw_name -> card_name for any matches found.
    """
    prompt = f"""Which of these names refer to either "{fighter1}" or "{fighter2}"?

Names:
{chr(10).join(f'- {n}' for n in all_names)}

Return ONLY a JSON object mapping matched names to the correct fighter.
Example: {{"Chanel Dyer": "{fighter1}", "some other name": "{fighter2}"}}
Only include names that actually match one of the two fighters.
If a name doesn't match either fighter, do NOT include it."""

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": "You are a name matching tool. Return only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.0,
                "max_tokens": 500,
            },
            timeout=15,
        )

        if response.status_code != 200:
            return {}

        content = response.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1]
            content = content.rsplit("```", 1)[0].strip()

        return json.loads(content)

    except Exception as e:
        log.warning("Failed to match %s vs %s: %s", fighter1, fighter2, e)
        return {}


def normalize_predictions(all_results: dict[str, list[dict]],
                          fight_card: list[dict]) -> dict[str, list[dict]]:
    """Normalize all fighter names across all model outputs to card names.

    Matches per-fight in parallel for speed and accuracy.
    """
    # Collect all unique names from all models
    all_names = sorted(set(
        name
        for preds in all_results.values()
        for p in preds
        for name in [p["fighter_picked"], p["fighter_against"]]
    ))

    log.info("Normalizing %d unique names against %d fights...", len(all_names), len(fight_card))
    t0 = time.time()

    # Match each fight in parallel
    full_mapping = {}
    with ThreadPoolExecutor(max_workers=len(fight_card)) as executor:
        futures = {
            executor.submit(_match_fight, f["fighter1"], f["fighter2"], all_names): f
            for f in fight_card
        }
        for future in as_completed(futures):
            mapping = future.result()
            full_mapping.update(mapping)

    # Log changes
    for original, mapped in sorted(full_mapping.items()):
        if original != mapped:
            log.info("  %s → %s", original, mapped)

    log.info("Normalized %d name mappings (%.1fs)", len(full_mapping), time.time() - t0)

    # Apply mapping to all results
    normalized = {}
    for model, preds in all_results.items():
        normalized[model] = []
        for p in preds:
            normalized[model].append({
                **p,
                "fighter_picked": full_mapping.get(p["fighter_picked"], p["fighter_picked"]),
                "fighter_against": full_mapping.get(p["fighter_against"], p["fighter_against"]),
            })

    return normalized
