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
    args = parser.parse_args()

    if args.results:
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
