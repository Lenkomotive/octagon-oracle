"""Extract fight predictions from a transcript using multiple LLMs.

Runs 4 models in parallel, uses consensus for final picks.
"""

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("extract_predictions")

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

MODELS = [
    "google/gemini-2.5-flash",
    "deepseek/deepseek-v3.2-20251201",
    "openai/gpt-oss-120b",
]

SYSTEM_PROMPT = """You are a UFC prediction extractor. Given a transcript from a YouTube video where someone discusses upcoming UFC fights and makes predictions, extract all fight predictions.

For each prediction, extract:
- "fighter_picked": the fighter the YouTuber thinks will win
- "fighter_against": the opponent
- "method": predicted method of victory if mentioned (e.g. "KO", "submission", "decision"), or null
- "confidence": "high", "medium", or "low" based on how confident they sound, default "medium"

IMPORTANT: If a fight card is provided, use those exact names. Match misspelled/mispronounced names to the closest fighter on the card.

Return ONLY valid JSON: {"predictions": [{"fighter_picked": "...", "fighter_against": "...", "method": "..." or null, "confidence": "..."}]}
If no predictions found, return {"predictions": []}."""


def _parse_json(content: str) -> dict:
    if content.startswith("```"):
        content = content.split("\n", 1)[1]
        content = content.rsplit("```", 1)[0].strip()
    return json.loads(content)


def _extract_with_model(model: str, user_content: str) -> tuple[str, list[dict]]:
    """Run extraction with a single model. Returns (model_name, predictions)."""
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
                    {"role": "user", "content": user_content},
                ],
                "temperature": 0.0,
            },
            timeout=120,
        )

        if response.status_code != 200:
            log.warning("[%s] HTTP %d: %s", model, response.status_code, response.text[:200])
            return model, []

        content = response.json()["choices"][0]["message"]["content"].strip()
        result = _parse_json(content)
        preds = result.get("predictions", [])
        log.info("[%s] %d predictions (%.1fs)", model, len(preds), time.time() - t0)
        return model, preds

    except Exception as e:
        log.warning("[%s] Failed: %s", model, e)
        return model, []


def _normalize_name(name: str) -> str:
    """Normalize fighter name for comparison."""
    return name.lower().strip().replace(".", "").replace("-", " ")


def _build_consensus(all_results: dict[str, list[dict]], fight_card: list[dict] = None) -> list[dict]:
    """Build consensus predictions from multiple model outputs.

    A pick is included if at least 2 models agree on the winner for a fight.
    Uses fight card names when available for normalization.
    """
    # Build card name lookup
    card_lookup = {}
    if fight_card:
        for f in fight_card:
            card_lookup[_normalize_name(f["fighter1"])] = f["fighter1"]
            card_lookup[_normalize_name(f["fighter2"])] = f["fighter2"]

    # Collect all picks per fight (keyed by sorted fighter pair)
    fight_picks = {}  # (fighter_a, fighter_b) -> {model: picked_fighter}

    for model, preds in all_results.items():
        for p in preds:
            picked = p["fighter_picked"]
            against = p["fighter_against"]

            # Normalize to card names if possible
            picked_norm = _normalize_name(picked)
            against_norm = _normalize_name(against)

            if card_lookup:
                picked = card_lookup.get(picked_norm, picked)
                against = card_lookup.get(against_norm, against)

            # Create a canonical fight key (sorted)
            fight_key = tuple(sorted([_normalize_name(picked), _normalize_name(against)]))

            if fight_key not in fight_picks:
                fight_picks[fight_key] = {"picks": {}, "methods": {}, "confidences": {},
                                          "names": (picked, against)}

            fight_picks[fight_key]["picks"][model] = picked
            fight_picks[fight_key]["methods"][model] = p.get("method")
            fight_picks[fight_key]["confidences"][model] = p.get("confidence", "medium")

    # Build consensus
    consensus = []
    for fight_key, data in fight_picks.items():
        picks = data["picks"]
        if not picks:
            continue

        # Count votes per fighter
        vote_counts = {}
        for model, picked in picks.items():
            norm = _normalize_name(picked)
            vote_counts[norm] = vote_counts.get(norm, 0) + 1

        # Winner is the one with most votes (need at least 2)
        best = max(vote_counts, key=vote_counts.get)
        if vote_counts[best] < 2:
            log.warning("No consensus for %s (votes: %s)", fight_key, vote_counts)
            continue

        # Get the proper-cased name
        winner_name = best
        for model, picked in picks.items():
            if _normalize_name(picked) == best:
                winner_name = picked
                break

        # Determine loser
        names = data["names"]
        loser_name = names[1] if _normalize_name(names[0]) == best else names[0]

        # Most common method
        methods = [m for m in data["methods"].values() if m]
        method = max(set(methods), key=methods.count) if methods else None

        # Confidence based on agreement
        agreement = vote_counts[best]
        total = len(picks)
        if agreement == total:
            confidence = "high"
        elif agreement >= total * 0.75:
            confidence = "medium"
        else:
            confidence = "low"

        consensus.append({
            "fighter_picked": winner_name,
            "fighter_against": loser_name,
            "method": method,
            "confidence": confidence,
            "models_agreed": agreement,
            "models_total": total,
        })

    return consensus


def extract_predictions(transcript_text: str, video_title: str, uploader: str,
                        fight_card: list[dict] = None) -> list[dict]:
    """Extract predictions using all models in parallel, return consensus.

    Args:
        transcript_text: full transcript
        video_title: video title for context
        uploader: channel name
        fight_card: list of {"fighter1": ..., "fighter2": ...} from DB

    Returns:
        list of consensus prediction dicts
    """
    log.info("=== Extracting predictions with %d models ===", len(MODELS))
    log.info("Title: \"%s\" by %s (%d chars)", video_title[:60], uploader, len(transcript_text))
    t0 = time.time()

    # Build user content
    user_content = f"Video title: {video_title}\nUploader: {uploader}\n\n"

    if fight_card:
        fights_list = "\n".join(f"- {f['fighter1']} vs {f['fighter2']}" for f in fight_card)
        user_content += f"OFFICIAL FIGHT CARD (use these exact names):\n{fights_list}\n\n"
        log.info("Fight card: %d fights", len(fight_card))

    user_content += f"Transcript:\n{transcript_text}"

    # Run all models in parallel
    all_results = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(_extract_with_model, m, user_content): m for m in MODELS}
        for future in as_completed(futures):
            model, preds = future.result()
            all_results[model] = preds

    # Build consensus
    consensus = _build_consensus(all_results, fight_card)

    log.info("Consensus: %d picks from %d models (%.1fs total)",
             len(consensus), len(all_results), time.time() - t0)

    # Log comparison
    for p in consensus:
        method = f" by {p['method']}" if p.get("method") else ""
        log.info("  [%d/%d] %s over %s%s",
                 p["models_agreed"], p["models_total"],
                 p["fighter_picked"], p["fighter_against"], method)

    return consensus
