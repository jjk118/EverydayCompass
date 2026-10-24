"""Conservative readers for free-event directories and the official GoLibrary calendar."""
import json
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

SGT = timezone(timedelta(hours=8))
KEYS = {"eventbrite", "allevents", "nlb_calendar"}

def walk(value):
    if isinstance(value, list):
        for item in value:
            yield from walk(item)
    elif isinstance(value, dict):
        yield value
        for key in ("@graph", "itemListElement", "item", "subEvent"):
            if key in value:
                yield from walk(value[key])

def free_status(node):
    offers = node.get("offers", [])
    offers = offers if isinstance(offers, list) else [offers]
    amounts = []
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        for key in ("price", "lowPrice", "highPrice"):
            raw = offer.get(key)
            if raw is None:
                continue
            try:
                amounts.append(float(raw))
            except (TypeError, ValueError):
                return None
    if any(value > 0 for value in amounts):
        return False
    if node.get("isAccessibleForFree") is True or amounts and all(value == 0 for value in amounts):
        # A zero lower bound alone does not establish that the event is free.
        if any("lowPrice" in o and "highPrice" not in o and "price" not in o for o in offers if isinstance(o, dict)):
            return None
        return True
    return None

def stamp(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.astimezone(SGT) if result.tzinfo else result.replace(tzinfo=SGT)
    except (TypeError, ValueError):
        return None

def clock(value):
    return f"{value.hour % 12 or 12}:{value.minute:02d}{'am' if value.hour < 12 else 'pm'}"

def allowed(url, key, cfg):
    host = (urlparse(url).hostname or "").lower()
    hosts = ["eventbrite.sg", "eventbrite.com"] if key == "eventbrite" else [cfg["host"]]
    return urlparse(url).scheme == "https" and any(host == h or host.endswith("." + h) for h in hosts)

def parse(html, key, today, cfg, clean_event, base_url=None):
    soup = BeautifulSoup(html, "html.parser")
    nodes = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            nodes.extend(walk(json.loads(script.string or script.get_text())))
        except (ValueError, TypeError):
            pass
    results = []
    for node in nodes:
        kinds = node.get("@type", [])
        kinds = kinds if isinstance(kinds, list) else [kinds]
        if not any(isinstance(kind, str) and kind.endswith("Event") for kind in kinds):
            continue
        if str(node.get("eventStatus", "")).endswith("EventCancelled"):
            continue
        start = stamp(node.get("startDate"))
        end = stamp(node.get("endDate")) or start
        if not start or not end or end.date() < today:
            continue
        loc = node.get("location") or {}
        if isinstance(loc, list):
            loc = next((item for item in loc if isinstance(item, dict)), {})
        if not isinstance(loc, dict):
            loc = {"name": str(loc)}
        address = loc.get("address") or {}
        address_text = " ".join(str(v) for v in address.values()) if isinstance(address, dict) else str(address)
        country = address.get("addressCountry", "") if isinstance(address, dict) else ""
        if isinstance(country, dict):
            country = country.get("name", "")
        venue = str(loc.get("name") or "").strip()
        location_text = venue + " " + address_text
        if "OnlineEventAttendanceMode" in str(node.get("eventAttendanceMode", "")) or "VirtualLocation" in str(loc.get("@type", "")):
            continue
        if re.search(r"\b(?:online|zoom|webinar|virtual event)\b", location_text, re.I):
            continue
        if country and str(country).lower() not in ("sg", "singapore"):
            continue
        if key != "nlb_calendar" and not country and "singapore" not in location_text.lower():
            continue
        free = free_status(node)
        if free is False or key != "nlb_calendar" and free is not True:
            continue
        title = BeautifulSoup(str(node.get("name") or ""), "html.parser").get_text(" ", strip=True)
        link = urljoin(base_url or cfg["url"], str(node.get("url") or base_url or ""))
        if not title or not allowed(link, key, cfg) or link.rstrip("/") == cfg["url"].rstrip("/"):
            continue
        description = BeautifulSoup(str(node.get("description") or ""), "html.parser").get_text(" ", strip=True)
        timing = clock(start) + (" – " + clock(end) if end != start else "") if re.search(r"T\d{2}:", str(node.get("startDate", ""))) else ""
        event = clean_event({
            "title": title, "overview": description[:700],
            "period": start.date().isoformat() + " to " + end.date().isoformat(),
            "start_date": start.date().isoformat(), "end_date": end.date().isoformat(),
            "time": timing, "venue": venue or address_text,
            "adult": "Free" if free is True else "Check official information",
            "category": "Event / Programme", "link": link,
            "tags": ["free"] if free is True else [],
        }, key, today)
        results.append(event)
    if key == "nlb_calendar" and not results and base_url and "/event/" in urlparse(base_url).path:
        event = parse_libcal_detail(soup, base_url, today, clean_event)
        if event:
            results.append(event)
    print(f"Directory {key}: {len(nodes)} structured objects; {len(results)} verified active in-person records", flush=True)
    return results

def parse_libcal_detail(soup, url, today, clean_event):
    fields = {}
    for term in soup.find_all("dt"):
        definition = term.find_next_sibling("dd")
        if definition:
            fields[term.get_text(" ", strip=True).lower().strip(": ")] = definition.get_text(" ", strip=True)
    def read_date(text):
        text = re.sub(r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s*", "", text or "")
        for pattern in ("%B %d, %Y", "%b %d, %Y", "%I:%M %p, %A, %B %d, %Y", "%I:%M%p, %A, %B %d, %Y"):
            try:
                return datetime.strptime(text, pattern).date()
            except ValueError:
                pass
        return None
    start = read_date(fields.get("from") or fields.get("date"))
    end = read_date(fields.get("to")) or start
    title = soup.find("h1")
    venue = fields.get("location", "") or fields.get("branch", "")
    if not start or not end or end < today or not title or not venue or re.search(r"\b(?:online|zoom)\b", venue, re.I):
        return None
    main = soup.find("main") or soup
    body = main.get_text(" ", strip=True)
    free = bool(re.search(r"\b(?:free admission|admission is free|free,? volunteer-led workshop)\b", body, re.I))
    heading = title.get_text(" ", strip=True).replace("In-Person", "").strip()
    paragraphs = [p.get_text(" ", strip=True) for p in main.find_all("p")]
    description = next((p for p in paragraphs if len(p) >= 60), "See the official GoLibrary event page for programme and registration details.")
    return clean_event({"title": heading, "overview": description[:700],
        "period": start.isoformat() + " to " + end.isoformat(),
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "time": fields.get("time", ""), "venue": venue, "category": "Library Programme",
        "adult": "Free" if free else "Check official information", "link": url,
        "tags": ["free"] if free else []}, "nlb_calendar", today)
