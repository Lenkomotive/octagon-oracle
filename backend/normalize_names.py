"""Normalize fighter names from LLM outputs to official card names.

Takes raw predictions from multiple models and maps all fighter names
to the official fight card using an LLM.
"""

import json
import logging
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("normalize_names")

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
MODEL = "google/gemini-2.5-flash-lite"  # cheapest, fast, good at matching


def normalize_predictions(all_results: dict[str, list[dict]],
                          fight_card: list[dict]) -> dict[str, list[dict]]:
    """Normalize all fighter names across all model outputs to card names.

    Args:
        all_results: {model_name: [predictions]} from each model
        fight_card: [{"fighter1": ..., "fighter2": ...}] from DB

    Returns:
        Same structure but with all names matched to card names.
    """
    # Collect all unique names from all models
    all_names = set()
    for preds in all_results.values():
        for p in preds:
            all_names.add(p["fighter_picked"])
            all_names.add(p["fighter_against"])

    # Build card names list
    card_names = []
    for f in fight_card:
        card_names.append(f["fighter1"])
        card_names.append(f["fighter2"])

    log.info("Normalizing %d unique names against %d card fighters...", len(all_names), len(card_names))
    t0 = time.time()

    # Ask LLM to map names
    prompt = f"""Match each name on the left to the closest name on the right. Names may be misspelled, mispronounced, or use nicknames.

Names to match:
{chr(10).join(f'- {n}' for n in sorted(all_names))}

Official card names:
{chr(10).join(f'- {n}' for n in card_names)}

Return ONLY a JSON object mapping each input name to its matching card name.
Example: {{"Chanel Dyer": "Shanelle Dyer", "Shamrock": "Shaqueme Rock"}}
If a name already matches exactly, include it too.
Every input name must appear in the output."""

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
        },
        timeout=30,
    )

    if response.status_code != 200:
        log.error("LLM error: %d — falling back to no normalization", response.status_code)
        return all_results

    content = response.json()["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1]
        content = content.rsplit("```", 1)[0].strip()

    try:
        name_map = json.loads(content)
    except json.JSONDecodeError:
        log.error("Failed to parse name mapping — falling back to no normalization")
        return all_results

    # Log mappings that changed
    for original, mapped in name_map.items():
        if original != mapped:
            log.info("  %s → %s", original, mapped)

    log.info("Normalized %d names (%.1fs)", len(name_map), time.time() - t0)

    # Apply mapping to all results
    normalized = {}
    for model, preds in all_results.items():
        normalized[model] = []
        for p in preds:
            normalized[model].append({
                **p,
                "fighter_picked": name_map.get(p["fighter_picked"], p["fighter_picked"]),
                "fighter_against": name_map.get(p["fighter_against"], p["fighter_against"]),
            })

    return normalized
