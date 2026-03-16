#!/usr/bin/env python3
"""Import existing JSON data into PostgreSQL."""

import json
import os
import glob
import logging
from datetime import datetime
from models import SessionLocal, Event, Fight, Channel, Video, Prediction, Score

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger(__name__)


def import_results(session):
    """Import event results from results/*.json and results/_index.json."""
    index_path = os.path.join(os.path.dirname(__file__), 'results', '_index.json')
    if os.path.isfile(index_path):
        with open(index_path) as f:
            index = json.load(f)
        log.info(f"Loading {len(index)} events from index")
    else:
        index = []

    count = 0
    for entry in index:
        # Get file path from index entry
        rel_path = entry.get('file', '')
        file_path = os.path.join(os.path.dirname(__file__), rel_path)
        if not os.path.isfile(file_path):
            log.warning(f"File not found: {file_path}")
            continue

        # Derive slug from filename
        slug = os.path.basename(rel_path).replace('.json', '')

        with open(file_path) as f:
            data = json.load(f)

        existing = session.query(Event).filter_by(slug=slug).first()
        if existing:
            continue

        # Parse date - handle "March 14, 2026" format
        event_date = None
        if entry.get('date'):
            try:
                event_date = datetime.strptime(entry['date'], '%B %d, %Y').date()
            except ValueError:
                try:
                    event_date = datetime.strptime(entry['date'], '%Y-%m-%d').date()
                except ValueError:
                    pass

        event = Event(
            name=data.get('event', entry.get('name', slug)),
            slug=slug,
            date=event_date,
            ufcstats_url=entry.get('url'),
        )
        session.add(event)
        session.flush()

        for r in data.get('results', []):
            fight = Fight(
                event_id=event.id,
                fighter1=r['fighter1'],
                fighter2=r['fighter2'],
                winner=r.get('winner'),
                method=r.get('method'),
                round=int(r['round']) if r.get('round') else None,
                time=r.get('time'),
                weight_class=r.get('weight_class'),
            )
            session.add(fight)

        count += 1

    session.commit()
    log.info(f"Imported {count} events with fights")


def import_channels(session):
    """Import channels from channels.json."""
    channels_path = os.path.join(os.path.dirname(__file__), 'channels.json')
    with open(channels_path) as f:
        data = json.load(f)

    count = 0
    for ch in data.get('channels', []):
        existing = session.query(Channel).filter_by(name=ch['name']).first()
        if existing:
            continue

        channel = Channel(
            name=ch['name'],
            youtube_url=ch['url'],
            keywords=','.join(ch.get('keywords', [])),
        )
        session.add(channel)
        count += 1

    session.commit()
    log.info(f"Imported {count} channels")


def import_predictions(session):
    """Import predictions and scores from predictions/*.json and scores/*.json."""
    pred_dir = os.path.join(os.path.dirname(__file__), 'predictions')
    score_dir = os.path.join(os.path.dirname(__file__), 'scores')

    if not os.path.isdir(pred_dir):
        log.info("No predictions directory found")
        return

    count = 0
    for pred_file in glob.glob(os.path.join(pred_dir, '*.json')):
        with open(pred_file) as f:
            data = json.load(f)

        vid = data.get('video_id', os.path.basename(pred_file).replace('.json', ''))

        existing = session.query(Video).filter_by(video_id=vid).first()
        if existing:
            continue

        # Find channel
        uploader = data.get('uploader', '')
        channel = session.query(Channel).filter_by(name=uploader).first()

        video = Video(
            video_id=vid,
            channel_id=channel.id if channel else None,
            title=data.get('title', ''),
            is_prediction=True,
        )
        session.add(video)
        session.flush()

        # Find event
        event_name = data.get('event', '')
        event = session.query(Event).filter(Event.name.ilike(f'%{event_name}%')).first() if event_name else None

        # Load scores if available
        score_file = os.path.join(score_dir, f'{vid}.json')
        scored_preds = {}
        if os.path.isfile(score_file):
            with open(score_file) as f:
                score_data = json.load(f)
            for sp in score_data.get('scored_predictions', []):
                key = (sp['fighter_picked'].lower(), sp['fighter_against'].lower())
                scored_preds[key] = sp.get('result') == 'correct'

        for p in data.get('predictions', []):
            pred = Prediction(
                video_id=video.id,
                event_id=event.id if event else None,
                fighter_picked=p['fighter_picked'],
                fighter_against=p['fighter_against'],
                method=p.get('method'),
                confidence=p.get('confidence'),
            )
            session.add(pred)
            session.flush()

            key = (p['fighter_picked'].lower(), p['fighter_against'].lower())
            if key in scored_preds:
                # Find the matching fight
                fight = None
                if event:
                    fight = session.query(Fight).filter(
                        Fight.event_id == event.id,
                        (Fight.fighter1.ilike(f'%{p["fighter_picked"]}%')) |
                        (Fight.fighter2.ilike(f'%{p["fighter_picked"]}%'))
                    ).first()

                score = Score(
                    prediction_id=pred.id,
                    fight_id=fight.id if fight else None,
                    correct=scored_preds[key],
                )
                session.add(score)

        count += 1

    session.commit()
    log.info(f"Imported predictions from {count} videos")


def main():
    session = SessionLocal()
    try:
        import_results(session)
        import_channels(session)
        import_predictions(session)
        log.info("Import complete")
    finally:
        session.close()


if __name__ == '__main__':
    main()
