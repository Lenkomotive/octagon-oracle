"""Score predictions against actual UFC fight results."""

import logging

from models import Event, Fight, Prediction, Score

log = logging.getLogger("score")


def score_prediction(session, prediction: Prediction, event: Event) -> Score | None:
    """Score a single prediction against actual fight results.

    Returns a Score object or None if fight not found / no results yet.
    """
    fights = session.query(Fight).filter_by(event_id=event.id).all()

    picked_norm = prediction.fighter_picked.lower().strip()
    against_norm = prediction.fighter_against.lower().strip()

    for fight in fights:
        f1 = fight.fighter1.lower().strip()
        f2 = fight.fighter2.lower().strip()

        if picked_norm not in (f1, f2) and against_norm not in (f1, f2):
            continue

        if not fight.winner:
            return None  # fight hasn't happened yet

        correct = fight.winner.lower().strip() == picked_norm

        method_correct = None
        if prediction.method and fight.method:
            pm = prediction.method.lower()
            am = fight.method.lower()
            if pm == "ko":
                method_correct = "ko" in am or "tko" in am
            elif pm == "submission":
                method_correct = "sub" in am
            elif pm == "decision":
                method_correct = "dec" in am

        score = Score(
            prediction_id=prediction.id,
            fight_id=fight.id,
            correct=correct,
            method_correct=method_correct,
        )

        icon = "CORRECT" if correct else "WRONG"
        log.info("  %s: %s over %s (actual: %s by %s)",
                 icon, prediction.fighter_picked, prediction.fighter_against,
                 fight.winner, fight.method)
        return score

    log.warning("  No matching fight for: %s vs %s",
                prediction.fighter_picked, prediction.fighter_against)
    return None


def score_unscored(session):
    """Find and score all predictions that don't have scores yet.

    Only scores predictions where the event has results (winners).
    Called by the monitor on each cycle (step 0a).
    """
    unscored = session.query(Prediction).filter(
        Prediction.event_id.isnot(None),
        ~Prediction.score.has(),
    ).all()

    if not unscored:
        return 0

    scored_count = 0
    for pred in unscored:
        event = session.query(Event).get(pred.event_id)
        if not event:
            continue

        has_results = session.query(Fight).filter(
            Fight.event_id == event.id,
            Fight.winner.isnot(None),
        ).count() > 0

        if not has_results:
            continue

        score = score_prediction(session, pred, event)
        if score:
            session.add(score)
            scored_count += 1

    if scored_count:
        session.commit()
        log.info("Scored %d previously unscored predictions", scored_count)

    return scored_count
