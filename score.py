"""Score predictions against actual UFC results."""

import json
import logging
import os

log = logging.getLogger(__name__)


def _normalize(name: str) -> str:
    return name.lower().strip().replace(".", "")


def score_predictions(predictions: dict, results: dict) -> dict:
    """Compare a prediction set against actual results.

    Returns a scored dict with each prediction marked correct/incorrect/unmatched,
    plus summary stats.
    """
    # Build lookup: normalized fighter name -> result dict
    results_by_fight = {}
    for r in results.get("results", []):
        if not r.get("winner"):
            continue
        f1 = _normalize(r["fighter1"])
        f2 = _normalize(r["fighter2"])
        results_by_fight[f1] = r
        results_by_fight[f2] = r

    scored = []
    correct = 0
    incorrect = 0
    unmatched = 0

    for pred in predictions.get("predictions", []):
        picked = pred["fighter_picked"]
        against = pred["fighter_against"]
        picked_norm = _normalize(picked)
        against_norm = _normalize(against)

        # Find the matching result
        result = results_by_fight.get(picked_norm) or results_by_fight.get(against_norm)

        if not result:
            log.warning("No result found for: %s vs %s", picked, against)
            scored.append({**pred, "result": "unmatched", "actual_winner": None})
            unmatched += 1
            continue

        actual_winner = result["winner"]
        is_correct = _normalize(actual_winner) == picked_norm

        if is_correct:
            correct += 1
            log.info("  CORRECT: %s over %s (actual: %s by %s)",
                     picked, against, actual_winner, result.get("method", "?"))
        else:
            incorrect += 1
            log.info("  WRONG:   %s over %s (actual winner: %s by %s)",
                     picked, against, actual_winner, result.get("method", "?"))

        # Check method accuracy too
        method_correct = None
        if pred.get("method") and result.get("method"):
            pred_method = pred["method"].lower()
            actual_method = result["method"].lower()
            if pred_method == "ko":
                method_correct = "ko" in actual_method or "tko" in actual_method
            elif pred_method == "submission":
                method_correct = "submission" in actual_method
            elif pred_method == "decision":
                method_correct = "decision" in actual_method

        scored.append({
            **pred,
            "result": "correct" if is_correct else "incorrect",
            "actual_winner": actual_winner,
            "actual_method": result.get("method"),
            "method_correct": method_correct,
        })

    total = correct + incorrect
    accuracy = (correct / total * 100) if total > 0 else 0

    summary = {
        "uploader": predictions.get("uploader"),
        "event": predictions.get("event") or results.get("event"),
        "video_id": predictions.get("video_id"),
        "correct": correct,
        "incorrect": incorrect,
        "unmatched": unmatched,
        "total_scored": total,
        "accuracy_pct": round(accuracy, 1),
        "scored_predictions": scored,
    }

    log.info("Score: %s — %d/%d correct (%.1f%%)",
             predictions.get("uploader", "?"), correct, total, accuracy)

    return summary


def score_from_files(prediction_path: str, results_path: str) -> dict:
    """Load prediction and result files, score them."""
    with open(prediction_path) as f:
        predictions = json.load(f)
    with open(results_path) as f:
        results = json.load(f)

    return score_predictions(predictions, results)


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if len(sys.argv) < 3:
        print("Usage: python score.py <predictions.json> <results.json>")
        sys.exit(1)

    result = score_from_files(sys.argv[1], sys.argv[2])

    print(f"\n{result['uploader']} — {result['event']}")
    print(f"Score: {result['correct']}/{result['total_scored']} ({result['accuracy_pct']}%)")
    print()
    for p in result["scored_predictions"]:
        icon = "+" if p["result"] == "correct" else "-" if p["result"] == "incorrect" else "?"
        method_note = ""
        if p.get("method_correct") is True:
            method_note = " (method correct too)"
        elif p.get("method_correct") is False:
            method_note = f" (predicted {p.get('method')}, actual {p.get('actual_method')})"
        print(f"  [{icon}] {p['fighter_picked']} over {p['fighter_against']}{method_note}")

    # Save
    os.makedirs("scores", exist_ok=True)
    out_path = f"scores/{result.get('video_id', 'unknown')}.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nSaved to {out_path}")
