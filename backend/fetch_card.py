import json
import logging
import re
import time
import os
import sys
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
MODEL = "deepseek/deepseek-chat-v3-0324"


def fetch_card_from_ufc(event_url: str) -> dict:
    """Scrape the fight card from a UFC.com event page."""
    log.info("Fetching fight card from %s", event_url)
    t0 = time.time()

    response = requests.get(event_url, headers={"User-Agent": "Mozilla/5.0"})
    if response.status_code != 200:
        log.error("Failed to fetch %s: HTTP %d", event_url, response.status_code)
        raise RuntimeError(f"Failed to fetch {event_url}: {response.status_code}")

    log.debug("Page fetched: %d bytes", len(response.text))
    soup = BeautifulSoup(response.text, "html.parser")

    # Get event name
    title_tag = soup.find("div", class_="field--name-node-title")
    event_name = title_tag.get_text(strip=True) if title_tag else "Unknown"

    # Extract fights by finding paired red/blue corner names
    fights = []
    seen = set()
    for row in soup.find_all("div", class_="c-listing-fight__names-row"):
        red_corner = row.find("div", class_="c-listing-fight__corner-name--red")
        blue_corner = row.find("div", class_="c-listing-fight__corner-name--blue")
        if not red_corner or not blue_corner:
            continue

        # Build name from given + family spans, or fallback to full text
        def get_name(corner):
            given = corner.find("span", class_="c-listing-fight__corner-given-name")
            family = corner.find("span", class_="c-listing-fight__corner-family-name")
            if given and family:
                return f"{given.get_text(strip=True)} {family.get_text(strip=True)}"
            return corner.get_text(strip=True)

        f1 = get_name(red_corner)
        f2 = get_name(blue_corner)

        # Deduplicate (page repeats fights in different sections)
        key = f"{f1} vs {f2}"
        if key in seen:
            continue
        seen.add(key)

        # Try to get weight class
        weight_el = row.find_next("div", class_="c-listing-fight__class-text")
        weight_class = weight_el.get_text(strip=True) if weight_el else None

        fights.append({
            "fighter1": f1,
            "fighter2": f2,
            "weight_class": weight_class,
        })

    log.info("Card scraped: %s — %d fights (%.1fs)", event_name, len(fights), time.time() - t0)
    for fight in fights:
        wc = f" ({fight['weight_class']})" if fight.get("weight_class") else ""
        log.debug("  %s vs %s%s", fight["fighter1"], fight["fighter2"], wc)

    return {"event": event_name, "fights": fights}


def fetch_results_from_ufc(event_url: str) -> dict:
    """Scrape fight results from a completed UFC event page.

    Returns dict with event name and list of fight results, each containing:
      fighter1, fighter2, winner (or None for draw/NC), method, round, time
    """
    log.info("Fetching results from %s", event_url)
    t0 = time.time()

    response = requests.get(event_url, headers={"User-Agent": "Mozilla/5.0"})
    if response.status_code != 200:
        raise RuntimeError(f"Failed to fetch {event_url}: {response.status_code}")

    soup = BeautifulSoup(response.text, "html.parser")

    title_tag = soup.find("div", class_="field--name-node-title")
    event_name = title_tag.get_text(strip=True) if title_tag else "Unknown"

    def get_name(corner):
        given = corner.find("span", class_="c-listing-fight__corner-given-name")
        family = corner.find("span", class_="c-listing-fight__corner-family-name")
        if given and family:
            return f"{given.get_text(strip=True)} {family.get_text(strip=True)}"
        return corner.get_text(strip=True)

    results = []
    seen = set()

    for fight_div in soup.find_all("div", class_="c-listing-fight"):
        names_row = fight_div.find("div", class_="c-listing-fight__names-row")
        if not names_row:
            continue

        red = names_row.find("div", class_="c-listing-fight__corner-name--red")
        blue = names_row.find("div", class_="c-listing-fight__corner-name--blue")
        if not red or not blue:
            continue

        f1 = get_name(red)
        f2 = get_name(blue)

        key = f"{f1} vs {f2}"
        if key in seen:
            continue
        seen.add(key)

        # Determine winner
        red_body = fight_div.find("div", class_="c-listing-fight__corner-body--red")
        blue_body = fight_div.find("div", class_="c-listing-fight__corner-body--blue")

        winner = None
        if red_body and red_body.find("div", class_="c-listing-fight__outcome--win"):
            winner = f1
        elif blue_body and blue_body.find("div", class_="c-listing-fight__outcome--win"):
            winner = f2

        # Method, round, time
        method_el = fight_div.find("div", class_="c-listing-fight__result-text method")
        round_el = fight_div.find("div", class_="c-listing-fight__result-text round")
        time_el = fight_div.find("div", class_="c-listing-fight__result-text time")

        result = {
            "fighter1": f1,
            "fighter2": f2,
            "winner": winner,
            "method": method_el.get_text(strip=True) if method_el else None,
            "round": round_el.get_text(strip=True) if round_el else None,
            "time": time_el.get_text(strip=True) if time_el else None,
        }
        results.append(result)
        log.debug("  %s vs %s -> %s (%s R%s)",
                  f1, f2, winner or "DRAW/NC",
                  result["method"] or "?", result["round"] or "?")

    completed = sum(1 for r in results if r["winner"])
    log.info("Results scraped: %s — %d fights, %d completed (%.1fs)",
             event_name, len(results), completed, time.time() - t0)

    return {"event": event_name, "event_url": event_url, "results": results}


def detect_event_from_title(title: str) -> str | None:
    """Extract UFC event name from a video title.

    Handles patterns like:
      'UFC 315 Predictions ...'           -> 'UFC 315'
      'UFC Vegas 114 Betting Tips'        -> 'UFC Vegas 114'
      'UFC Fight Night Emmett vs Vallejos ...' -> 'UFC Fight Night Emmett vs Vallejos'
      'UFC Austin Predictions'            -> 'UFC Austin'
    """
    # Numbered PPV: "UFC 315"
    m = re.search(r'UFC\s+\d+', title, re.IGNORECASE)
    if m:
        return m.group(0)

    # Vegas/city + number: "UFC Vegas 114", "UFC Louisville 2"
    m = re.search(r'UFC\s+[A-Z][a-z]+\s+\d+', title)
    if m:
        return m.group(0)

    # "UFC X vs Y" (any format): "UFC Moreno vs Kavanagh", "UFC Emmett vs Vallejos"
    m = re.search(r'UFC\s+(\w+)\s+vs\.?\s+(\w+)', title, re.IGNORECASE)
    if m:
        return f"UFC {m.group(1)} vs {m.group(2)}"

    # Fight Night with city: "UFC Fight Night Austin"
    m = re.search(r'UFC Fight Night[:\s]+([A-Z][a-z]+)', title, re.IGNORECASE)
    if m:
        return f"UFC Fight Night {m.group(1)}"

    # Generic "UFC <City>": "UFC Austin"
    m = re.search(r'UFC\s+([A-Z][a-z]{2,})', title)
    if m:
        return m.group(0)

    return None


def _extract_event_links(html: str) -> list[str]:
    """Pull all /event/... paths from the UFC events page HTML."""
    return list(set(re.findall(r'/event/[a-z0-9\-]+', html)))


def _validate_url_response(text: str) -> str | None:
    """Extract a valid /event/... path from LLM response. Returns None if garbage."""
    text = text.strip()
    # Try to find a path anywhere in the response (LLM may add commentary)
    match = re.search(r'/event/[a-z0-9\-]+', text)
    if match:
        return match.group(0)
    return None


def resolve_event_url(event_name: str) -> str:
    """Convert an event name like 'UFC Vegas 114' to a UFC.com URL.

    Strategy:
      1. Scrape UFC events page for all event links
      2. Ask LLM to pick the best match from the actual link list
      3. Validate LLM response is a real URL path (not a paragraph)
      4. Retry once on failure
    """
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not set")

    log.info("Resolving event name: \"%s\"", event_name)
    log.info("Fetching UFC events page...")
    t0 = time.time()

    response = requests.get(
        "https://www.ufc.com/events",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    if response.status_code != 200:
        raise RuntimeError(f"Failed to fetch UFC events page: {response.status_code}")

    html = response.text

    # Extract actual event links to constrain LLM to real options
    event_links = _extract_event_links(html)
    log.info("Found %d event links on UFC page", len(event_links))

    if not event_links:
        raise RuntimeError("No event links found on UFC events page")

    links_list = "\n".join(event_links)

    for attempt in range(2):
        log.info("Calling LLM to match event (model=%s, attempt=%d)...", MODEL, attempt + 1)

        llm_response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": f"""Match the UFC event "{event_name}" to one of these event URL paths.

Available event paths:
{links_list}

Rules:
- Reply with ONLY the matching path, e.g. /event/ufc-315
- No explanation, no commentary, no extra text
- If no exact match exists, pick the closest one
- Your entire response must start with /event/""",
                    },
                ],
                "temperature": 0.0,
            },
        )

        if llm_response.status_code != 200:
            log.error("OpenRouter error %d: %s", llm_response.status_code, llm_response.text[:300])
            raise RuntimeError(f"OpenRouter error: {llm_response.status_code}")

        raw = llm_response.json()["choices"][0]["message"]["content"]
        log.debug("LLM raw response: %s", raw[:200])

        path = _validate_url_response(raw)
        if path:
            url = f"https://www.ufc.com{path}"
            log.info("Resolved: \"%s\" -> %s (%.1fs)", event_name, url, time.time() - t0)
            return url

        log.warning("LLM returned invalid response (attempt %d): %s", attempt + 1, raw[:150])

    raise RuntimeError(
        f"Could not resolve event \"{event_name}\" — LLM failed to return a valid URL. "
        f"Try passing a direct URL instead: --event https://www.ufc.com/event/..."
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if len(sys.argv) < 2:
        print("Usage: python fetch_card.py <event_url_or_name>")
        print("  e.g.: python fetch_card.py https://www.ufc.com/event/ufc-fight-night-march-14-2026")
        print("  e.g.: python fetch_card.py 'UFC Vegas 114'")
        sys.exit(1)

    arg = sys.argv[1]

    if arg.startswith("http"):
        event_url = arg
    else:
        event_url = resolve_event_url(arg)

    card = fetch_card_from_ufc(event_url)

    # Save to file
    os.makedirs("cards", exist_ok=True)
    event_name = card.get("event", "unknown").replace(" ", "_").replace(":", "")
    out_path = f"cards/{event_name}.json"
    with open(out_path, "w") as f:
        json.dump(card, f, indent=2)

    log.info("Saved to %s", out_path)
    for fight in card.get("fights", []):
        wc = f" ({fight['weight_class']})" if fight.get("weight_class") else ""
        log.info("  %s vs %s%s", fight["fighter1"], fight["fighter2"], wc)
