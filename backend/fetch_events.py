#!/usr/bin/env python3
"""Fetch UFC events and results from Wikipedia.

Source: https://en.wikipedia.org/wiki/List_of_UFC_events

Usage:
    python fetch_events.py                    # Print upcoming + recent past events
    python fetch_events.py --results UFC_326  # Fetch results for a specific event
    python fetch_events.py --sync             # Sync all events to DB
"""

import logging
import re
import time
from datetime import datetime, date

import requests
from bs4 import BeautifulSoup

log = logging.getLogger("fetch_events")

WIKI_EVENTS_URL = "https://en.wikipedia.org/wiki/List_of_UFC_events"
WIKI_BASE = "https://en.wikipedia.org"
HEADERS = {"User-Agent": "Mozilla/5.0 (OctagonOracle/1.0)"}


# ── Event list ──────────────────────────────────────────────

def _parse_date(date_str: str) -> date | None:
    """Parse Wikipedia date formats like 'Mar 14, 2026'."""
    date_str = date_str.strip().rstrip("[0-9]").strip()
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    # Try removing footnote refs like [28]
    cleaned = re.sub(r'\[.*?\]', '', date_str).strip()
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _slugify(name: str) -> str:
    """Convert event name to a URL-friendly slug."""
    slug = name.lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug.strip('-')


def fetch_event_list() -> dict:
    """Fetch upcoming and past UFC events from Wikipedia.

    Returns:
        {
            "upcoming": [{"name", "date", "location", "wiki_path", "slug"}, ...],
            "past": [{"name", "date", "location", "wiki_path", "slug"}, ...],
            "fetched_at": "2026-03-20T21:00:00"
        }
    """
    log.info("Fetching event list from Wikipedia...")
    t0 = time.time()

    r = requests.get(WIKI_EVENTS_URL, headers=HEADERS)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    tables = soup.find_all("table", class_="wikitable")
    if len(tables) < 2:
        raise RuntimeError(f"Expected 2+ wikitables, found {len(tables)}")

    # Table 0 = upcoming, Table 1 = past
    upcoming = _parse_upcoming_table(tables[0])
    past = _parse_past_table(tables[1])

    log.info("Fetched %d upcoming, %d past events (%.1fs)",
             len(upcoming), len(past), time.time() - t0)

    return {
        "upcoming": upcoming,
        "past": past,
        "fetched_at": datetime.now().isoformat(),
    }


def _parse_upcoming_table(table) -> list[dict]:
    """Parse upcoming events table. Cols: Event, Date, Venue, Location, Ref."""
    events = []
    for row in table.find_all("tr")[1:]:
        cells = row.find_all(["td", "th"])
        if len(cells) < 4:
            continue

        name = cells[0].get_text(strip=True)
        date_str = cells[1].get_text(strip=True)
        location = cells[3].get_text(strip=True)

        # Get wiki link
        link = cells[0].find("a")
        wiki_path = link.get("href", "") if link else ""

        event_date = _parse_date(date_str)

        events.append({
            "name": name,
            "date": event_date.isoformat() if event_date else None,
            "location": location,
            "wiki_path": wiki_path,
            "slug": _slugify(name),
        })

    return events


def _parse_past_table(table, limit: int = 200) -> list[dict]:
    """Parse past events table. Cols: #, Event, Date, Venue, Location, Attendance, Ref."""
    events = []
    for row in table.find_all("tr")[1:limit + 1]:
        cells = row.find_all(["td", "th"])
        if len(cells) < 5:
            continue

        name = cells[1].get_text(strip=True)
        date_str = cells[2].get_text(strip=True)
        location = cells[4].get_text(strip=True)

        link = cells[1].find("a")
        wiki_path = link.get("href", "") if link else ""

        event_date = _parse_date(date_str)

        events.append({
            "name": name,
            "date": event_date.isoformat() if event_date else None,
            "location": location,
            "wiki_path": wiki_path,
            "slug": _slugify(name),
        })

    return events


# ── Event results ───────────────────────────────────────────

def fetch_event_results(wiki_path: str) -> dict | None:
    """Fetch fight results from a Wikipedia event page.

    Args:
        wiki_path: e.g. "/wiki/UFC_326"

    Returns:
        {
            "event": "UFC 326: Holloway vs. Oliveira 2",
            "fights": [
                {
                    "fighter1": "Charles Oliveira",  (winner)
                    "fighter2": "Max Holloway",
                    "winner": "Charles Oliveira",
                    "method": "Decision (unanimous)",
                    "round": 5,
                    "time": "5:00",
                    "weight_class": "Lightweight"
                }, ...
            ]
        }
    """
    if not wiki_path:
        return None

    url = f"{WIKI_BASE}{wiki_path}"
    log.info("Fetching results from %s", url)
    t0 = time.time()

    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # Get event name from page title
    title_el = soup.find("h1", id="firstHeading")
    event_name = title_el.get_text(strip=True) if title_el else wiki_path.split("/")[-1]

    # Find results tables — they have "def." in them
    fights = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 7:
                continue

            # Check for "def." pattern
            cell_texts = [c.get_text(strip=True) for c in cells]
            if "def." not in cell_texts:
                continue

            def_idx = cell_texts.index("def.")

            # Weight class is before fighter1
            weight_class = cell_texts[def_idx - 2] if def_idx >= 2 else ""
            fighter1 = cell_texts[def_idx - 1]  # winner
            fighter2 = cell_texts[def_idx + 1]   # loser

            # Clean fighter names — remove (c) championship marker
            fighter1 = re.sub(r'\(c\)', '', fighter1).strip()
            fighter2 = re.sub(r'\(c\)', '', fighter2).strip()

            method = cell_texts[def_idx + 2] if def_idx + 2 < len(cell_texts) else ""
            round_num = cell_texts[def_idx + 3] if def_idx + 3 < len(cell_texts) else ""
            fight_time = cell_texts[def_idx + 4] if def_idx + 4 < len(cell_texts) else ""

            try:
                round_int = int(round_num)
            except (ValueError, TypeError):
                round_int = None

            fights.append({
                "fighter1": fighter1,
                "fighter2": fighter2,
                "winner": fighter1,  # fighter before "def." is always the winner
                "method": method,
                "round": round_int,
                "time": fight_time,
                "weight_class": weight_class,
            })

    log.info("Parsed %d fights from %s (%.1fs)", len(fights), event_name, time.time() - t0)

    return {
        "event": event_name,
        "fights": fights,
    }


# ── Upcoming event card (no results yet) ────────────────────

def fetch_event_card(wiki_path: str) -> dict | None:
    """Fetch fight card for an upcoming event (no results yet).

    Returns same structure as fetch_event_results but winner/method/round/time are None.
    """
    if not wiki_path:
        return None

    url = f"{WIKI_BASE}{wiki_path}"
    log.info("Fetching card from %s", url)
    t0 = time.time()

    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    title_el = soup.find("h1", id="firstHeading")
    event_name = title_el.get_text(strip=True) if title_el else wiki_path.split("/")[-1]

    # For upcoming events, look for "vs." pattern
    fights = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 4:
                continue

            cell_texts = [c.get_text(strip=True) for c in cells]
            if "vs." not in cell_texts:
                continue

            vs_idx = cell_texts.index("vs.")
            weight_class = cell_texts[vs_idx - 2] if vs_idx >= 2 else ""
            fighter1 = cell_texts[vs_idx - 1]
            fighter2 = cell_texts[vs_idx + 1]

            fighter1 = re.sub(r'\(c\)', '', fighter1).strip()
            fighter2 = re.sub(r'\(c\)', '', fighter2).strip()

            fights.append({
                "fighter1": fighter1,
                "fighter2": fighter2,
                "winner": None,
                "method": None,
                "round": None,
                "time": None,
                "weight_class": weight_class,
            })

    log.info("Parsed %d fights from %s (%.1fs)", len(fights), event_name, time.time() - t0)

    return {
        "event": event_name,
        "fights": fights,
    }


# ── DB sync ─────────────────────────────────────────────────

def sync_events_to_db(session, since_event: str = "UFC 300"):
    """Sync Wikipedia events to the database.

    First run: imports all events from since_event to now + upcoming.
    Subsequent runs: only adds new events and updates fight cards/results.
    """
    from models import Event, Fight

    data = fetch_event_list()

    # Find cutoff in past events
    cutoff_idx = len(data["past"])
    for i, e in enumerate(data["past"]):
        if since_event.lower() in e["name"].lower():
            cutoff_idx = i + 1
            break

    past_events = data["past"][:cutoff_idx]
    all_events = data["upcoming"] + past_events

    added = 0
    updated = 0

    for ev in all_events:
        slug = ev["slug"]
        if not slug:
            continue

        existing = session.query(Event).filter_by(slug=slug).first()

        if not existing:
            # New event — add it
            event_date = None
            if ev.get("date"):
                try:
                    event_date = datetime.strptime(ev["date"], "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    pass

            event = Event(
                name=ev["name"],
                slug=slug,
                date=event_date,
                wiki_path=ev.get("wiki_path", ""),
            )
            session.add(event)
            session.flush()
            added += 1

            # Fetch fights (results for past, card for upcoming)
            if ev.get("wiki_path"):
                _sync_fights(session, event, ev["wiki_path"])
        else:
            # Existing event — check if we need to update fights
            has_fights = session.query(Fight).filter_by(event_id=existing.id).count() > 0
            has_results = session.query(Fight).filter(
                Fight.event_id == existing.id,
                Fight.winner.isnot(None),
            ).count() > 0

            # Update wiki_path if we didn't have it before
            if ev.get("wiki_path") and not existing.wiki_path:
                existing.wiki_path = ev["wiki_path"]

            if not has_fights and ev.get("wiki_path"):
                # No fights at all — fetch card or results
                _sync_fights(session, existing, ev["wiki_path"])
                updated += 1
            elif has_fights and not has_results and existing.date and existing.date < date.today():
                # Past event with card but no results — fetch results
                if ev.get("wiki_path"):
                    _sync_fights(session, existing, ev["wiki_path"], replace=True)
                    updated += 1

    session.commit()
    log.info("Sync complete: %d added, %d updated, %d total events",
             added, updated, len(all_events))


def _sync_fights(session, event, wiki_path: str, replace: bool = False):
    """Fetch fights from Wikipedia and save to DB."""
    from models import Fight

    if replace:
        session.query(Fight).filter_by(event_id=event.id).delete()

    # Try results first (past event), fall back to card (upcoming)
    data = fetch_event_results(wiki_path)
    if not data or not data.get("fights"):
        data = fetch_event_card(wiki_path)

    if not data or not data.get("fights"):
        log.warning("No fights found for %s", event.name)
        return

    for f in data["fights"]:
        fight = Fight(
            event_id=event.id,
            fighter1=f["fighter1"],
            fighter2=f["fighter2"],
            winner=f.get("winner"),
            method=f.get("method"),
            round=f.get("round"),
            time=f.get("time"),
            weight_class=f.get("weight_class"),
        )
        session.add(fight)

    log.info("  %s: %d fights", event.name, len(data["fights"]))


def refresh_upcoming(session):
    """Quick refresh — only check upcoming events and recently completed ones.
    Called by the monitor on each cycle."""
    from models import Event, Fight

    data = fetch_event_list()

    # Only process upcoming + last 3 past events
    events_to_check = data["upcoming"] + data["past"][:3]

    for ev in events_to_check:
        slug = ev["slug"]
        if not slug:
            continue

        existing = session.query(Event).filter_by(slug=slug).first()

        if not existing:
            event_date = None
            if ev.get("date"):
                try:
                    event_date = datetime.strptime(ev["date"], "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    pass

            event = Event(
                name=ev["name"],
                slug=slug,
                date=event_date,
                wiki_path=ev.get("wiki_path", ""),
            )
            session.add(event)
            session.flush()
            log.info("New event added: %s (%s)", ev["name"], ev.get("date"))

            if ev.get("wiki_path"):
                _sync_fights(session, event, ev["wiki_path"])
        else:
            # Check if past event needs results
            has_results = session.query(Fight).filter(
                Fight.event_id == existing.id,
                Fight.winner.isnot(None),
            ).count() > 0

            if not has_results and existing.date and existing.date < date.today() and ev.get("wiki_path"):
                log.info("Fetching results for completed event: %s", existing.name)
                _sync_fights(session, existing, ev["wiki_path"], replace=True)

    session.commit()


# ── CLI ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import json

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Fetch UFC events from Wikipedia")
    parser.add_argument("--results", help="Fetch results for event wiki path (e.g. /wiki/UFC_326)")
    parser.add_argument("--card", help="Fetch card for upcoming event wiki path")
    parser.add_argument("--upcoming", action="store_true", help="Show upcoming events")
    parser.add_argument("--past", type=int, default=0, help="Show N past events")
    parser.add_argument("--sync", action="store_true", help="First run: sync UFC 300+ to DB")
    parser.add_argument("--refresh", action="store_true", help="Quick refresh: upcoming + recent results")
    args = parser.parse_args()

    if args.sync:
        from models import SessionLocal
        session = SessionLocal()
        sync_events_to_db(session, since_event="UFC 300")
        session.close()

    elif args.refresh:
        from models import SessionLocal
        session = SessionLocal()
        refresh_upcoming(session)
        session.close()

    elif args.results:
        path = args.results if args.results.startswith("/wiki/") else f"/wiki/{args.results}"
        results = fetch_event_results(path)
        if results:
            print(f"\n{results['event']} — {len(results['fights'])} fights")
            for f in results["fights"]:
                print(f"  {f['fighter1']} def. {f['fighter2']} — {f['method']} R{f['round']} {f['time']}")
        else:
            print("No results found")

    elif args.card:
        path = args.card if args.card.startswith("/wiki/") else f"/wiki/{args.card}"
        card = fetch_event_card(path)
        if card:
            print(f"\n{card['event']} — {len(card['fights'])} fights")
            for f in card["fights"]:
                print(f"  {f['fighter1']} vs. {f['fighter2']} ({f['weight_class']})")
        else:
            print("No card found")

    else:
        data = fetch_event_list()

        if args.upcoming or not args.past:
            print(f"\n=== UPCOMING ({len(data['upcoming'])}) ===")
            for e in data["upcoming"]:
                print(f"  {e['date']} | {e['name']:<50} | {e['wiki_path']}")

        if args.past or not args.upcoming:
            n = args.past or 10
            print(f"\n=== PAST (last {n}) ===")
            for e in data["past"][:n]:
                print(f"  {e['date']} | {e['name']:<50} | {e['wiki_path']}")
