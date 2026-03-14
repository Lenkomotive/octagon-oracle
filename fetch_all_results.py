#!/usr/bin/env python3
"""Bulk-fetch all UFC event results from UFC 280 onwards via ufcstats.com."""

import json
import logging
import os
import time
import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

UFCSTATS_ALL_EVENTS = "http://ufcstats.com/statistics/events/completed?page=all"


def get_event_list(since_event: str = "UFC 280") -> list[dict]:
    """Get list of all UFC events from ufcstats.com, filtered to since_event onwards."""
    log.info("Fetching event list from ufcstats.com...")
    r = requests.get(UFCSTATS_ALL_EVENTS, headers={"User-Agent": "Mozilla/5.0"})
    if r.status_code != 200:
        raise RuntimeError(f"Failed to fetch ufcstats events: {r.status_code}")

    soup = BeautifulSoup(r.text, "html.parser")

    events = []
    cutoff_found = False

    for a in soup.find_all("a", class_="b-link"):
        href = a.get("href", "")
        if "event-details" not in href:
            continue
        name = a.get_text(strip=True)
        if not name:
            continue

        events.append({"name": name, "ufcstats_url": href})

        if since_event.lower() in name.lower():
            cutoff_found = True
            break

    if not cutoff_found:
        log.warning("Could not find '%s' in event list, returning all %d events", since_event, len(events))

    log.info("Found %d events from '%s' to present", len(events), since_event)
    return events


def fetch_event_results(ufcstats_url: str) -> dict:
    """Scrape results for a single event from ufcstats.com."""
    r = requests.get(ufcstats_url, headers={"User-Agent": "Mozilla/5.0"})
    if r.status_code != 200:
        raise RuntimeError(f"Failed to fetch {ufcstats_url}: {r.status_code}")

    soup = BeautifulSoup(r.text, "html.parser")

    # Event name
    title_el = soup.find("span", class_="b-content__title-highlight")
    event_name = title_el.get_text(strip=True) if title_el else "Unknown"

    # Date
    date_items = soup.find_all("li", class_="b-list__box-list-item")
    event_date = None
    for item in date_items:
        text = item.get_text(strip=True)
        if "Date:" in text:
            event_date = text.replace("Date:", "").strip()
            break

    # Fights
    results = []
    rows = soup.find_all("tr", class_="b-fight-details__table-row")

    for row in rows[1:]:  # skip header
        cols = row.find_all("td")
        if len(cols) < 10:
            continue

        # col[0] = win/loss, col[1] = fighters
        outcome = cols[0].get_text(strip=True)
        fighters = cols[1].find_all("a")
        if len(fighters) < 2:
            continue

        f1 = fighters[0].get_text(strip=True)
        f2 = fighters[1].get_text(strip=True)

        # First fighter is winner when outcome = 'win'
        winner = f1 if outcome == "win" else None

        # Method (col 7), Round (col 8), Time (col 9)
        method_raw = cols[7].get_text(strip=True)
        rnd = cols[8].get_text(strip=True)
        fight_time = cols[9].get_text(strip=True)

        # Clean up method — ufcstats concatenates like "SUBRear Naked Choke"
        method = method_raw
        for prefix in ["KO/TKO", "SUB", "U-DEC", "S-DEC", "M-DEC", "DQ", "Overturned", "CNC"]:
            if method_raw.startswith(prefix):
                detail = method_raw[len(prefix):].strip()
                method = f"{prefix} ({detail})" if detail else prefix
                break

        results.append({
            "fighter1": f1,
            "fighter2": f2,
            "winner": winner,
            "method": method,
            "round": rnd,
            "time": fight_time,
        })

    return {
        "event": event_name,
        "date": event_date,
        "ufcstats_url": ufcstats_url,
        "results": results,
    }


def fetch_all(since_event: str = "UFC 280", delay: float = 0.5):
    """Fetch all results from since_event to present. Saves to results/ directory."""
    events = get_event_list(since_event)

    os.makedirs("results", exist_ok=True)
    all_results = {}
    failed = []

    for i, event in enumerate(events):
        slug = event["name"].replace(" ", "_").replace(":", "").replace(".", "")
        out_path = f"results/{slug}.json"

        # Skip if already fetched
        if os.path.isfile(out_path):
            log.debug("Already have: %s", event["name"])
            with open(out_path) as f:
                all_results[event["name"]] = json.load(f)
            continue

        log.info("[%d/%d] Fetching: %s", i + 1, len(events), event["name"])
        try:
            result = fetch_event_results(event["ufcstats_url"])
            with open(out_path, "w") as f:
                json.dump(result, f, indent=2)
            all_results[event["name"]] = result
            log.info("  %d fights, saved to %s", len(result["results"]), out_path)
        except Exception as e:
            log.error("  FAILED: %s", e)
            failed.append(event["name"])

        time.sleep(delay)  # be polite

    log.info("")
    log.info("Done: %d/%d events fetched", len(all_results), len(events))
    if failed:
        log.warning("Failed: %s", failed)

    # Save index
    index = [
        {"name": r["event"], "date": r.get("date"), "fights": len(r["results"]),
         "file": f"results/{r['event'].replace(' ', '_').replace(':', '').replace('.', '')}.json"}
        for r in all_results.values()
    ]
    with open("results/_index.json", "w") as f:
        json.dump(index, f, indent=2)
    log.info("Index saved to results/_index.json")

    return all_results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    fetch_all()
