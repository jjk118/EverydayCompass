#!/usr/bin/env python3
"""
Everyday Compass - What's On updater.

Safety rules:
- Official sources only.
- Each source is isolated: failure/zero usable results falls back to that source's previous records.
- Expire only records with a reliably parsed finite end date before today (Singapore time).
- Permanent / Daily / Ongoing / unknown-end records are preserved.
- Deduplicate and prefer richer records.
- Never replace a valid non-empty feed with an empty feed.
- --dry-run never writes events.json.

This deliberately uses conservative extraction. Sites change; when a parser cannot confidently
extract events it preserves the previous valid records instead of guessing.
"""
from __future__ import annotations
import argparse, copy, hashlib, json, re, sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "events.json"
SGT = ZoneInfo("Asia/Singapore")
UA = "EverydayCompass-WhatsOn/1.0 (+official-source-refresh)"

SOURCES = {
    "sccc": {
        "name": "Singapore Chinese Cultural Centre",
        "url": "https://singaporeccc.org.sg/events/",
        "host": "singaporeccc.org.sg",
    },
    "gardens": {
        "name": "Gardens by the Bay",
        "url": "https://www.gardensbythebay.com.sg/en/things-to-do/calendar-of-events.html",
        "host": "gardensbythebay.com.sg",
    },
    "esplanade": {
        "name": "Esplanade",
        "url": "https://www.esplanade.com/whats-on",
        "host": "esplanade.com",
    },
    "national_museum": {
        "name": "National Museum of Singapore",
        "url": "https://www.nationalmuseum.nhb.gov.sg/whats-on/exhibition/exhibitions",
        "host": "nationalmuseum.nhb.gov.sg",
    },
    "national_gallery": {
        "name": "National Gallery Singapore",
        "url": "https://www.nationalgallery.sg/sg/en/whats-on.html",
        "host": "nationalgallery.sg",
    },
    "artscience": {
        "name": "ArtScience Museum",
        "url": "https://www.marinabaysands.com/museum/whats-on.html",
        "host": "marinabaysands.com",
    },
    "ura": {
        "name": "Urban Redevelopment Authority",
        "url": "https://www.ura.gov.sg/get-involved/events-and-exhibitions/",
        "host": "ura.gov.sg",
    },
    "nlb": {
        "name": "National Library Board",
        "url": "https://exhibitions.nlb.gov.sg/current-exhibitions/",
        "host": "exhibitions.nlb.gov.sg",
    },
}

DATE_RANGE = re.compile(
    r"(?P<start>\d{1,2}\s+[A-Za-z]{3,9}(?:\s+\d{4})?)\s*[–—-]\s*"
    r"(?P<end>\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})", re.I
)
ISO_RANGE = re.compile(r"(?P<start>\d{4}-\d{2}-\d{2})\s*(?:to|–|—|-)\s*(?P<end>\d{4}-\d{2}-\d{2})", re.I)

MONTH_FIRST_RANGE = re.compile(
    r"(?P<start>[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})\s*(?:to|[–—-])\s*"
    r"(?P<end>[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})", re.I
)
SHORT_DATE_RANGE = re.compile(
    r"(?<!\d)\d{1,2}\s*[–—-]\s*\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}", re.I
)
SINGLE_DATE = re.compile(
    r"\b(?:\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})\b", re.I
)

def extract_period(text):
    text = norm(text)
    for pattern in (MONTH_FIRST_RANGE, DATE_RANGE, ISO_RANGE, SHORT_DATE_RANGE):
        match = pattern.search(text)
        if match:
            return match.group(0)
    for word in ("Permanent", "Ongoing"):
        if re.search(r"\b" + word + r"\b", text, re.I):
            return word
    match = SINGLE_DATE.search(text)
    return match.group(0) if match else ""

def official_link(url, key):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    allowed = SOURCES[key]["host"]
    return parsed.scheme == "https" and (host == allowed or host.endswith("." + allowed))


def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip()

def load_previous(path=OUT):
    if not path.exists():
        return {"updated_at": None, "events": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        raise ValueError("Existing events.json is invalid")
    return data

def source_key(e):
    return e.get("source_key") or ""

def previous_for(previous, key):
    return [copy.deepcopy(e) for e in previous.get("events", []) if source_key(e) == key]

def parse_date(s, default_year=None):
    s = norm(s).replace(",", "")
    for fmt in ("%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    if default_year:
        for fmt in ("%d %b", "%d %B"):
            try:
                d = datetime.strptime(s, fmt)
                return date(default_year, d.month, d.day)
            except ValueError:
                pass
    return None

def finite_end_date(period):
    p = norm(period)
    if not p or re.search(r"\b(permanent|ongoing|daily|every\b|various dates|from\s+\d)", p, re.I):
        return None
    m = MONTH_FIRST_RANGE.search(p)
    if m:
        return parse_date(m.group("end"))
    m = ISO_RANGE.search(p)
    if m:
        return parse_date(m.group("end"))
    m = DATE_RANGE.search(p)
    if m:
        end = parse_date(m.group("end"))
        return end
    if SINGLE_DATE.fullmatch(p):
        return parse_date(p)
    # single exact dated event
    m = re.fullmatch(r"(?:[A-Za-z]{3},?\s*)?(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})", p, re.I)
    return parse_date(m.group(1)) if m else None

def is_expired(e, today):
    end = finite_end_date(e.get("period", ""))
    return bool(end and end < today)

def status_for(period, today):
    end = finite_end_date(period)
    if end and end < today:
        return "Expired", ""
    # Parse start where possible
    m = MONTH_FIRST_RANGE.search(norm(period)) or DATE_RANGE.search(norm(period))
    if m:
        end_d = parse_date(m.group("end"))
        start_d = parse_date(m.group("start"), end_d.year if end_d else today.year)
        if start_d and start_d > today:
            return "Upcoming", "upcoming"
        if end_d and 0 <= (end_d - today).days <= 14:
            return "Ending Soon", "ending"
    single = parse_date(norm(period))
    if single and single > today:
        return "Upcoming", "upcoming"
    if single and 0 <= (single - today).days <= 14:
        return "Ending Soon", "ending"
    return "Ongoing", ""

def richness(e):
    fields = ("title","category","overview","period","time","venue","mrt","adult","senior","child","link")
    return sum(bool(norm(str(e.get(k,"")))) for k in fields) + len(e.get("tags", []))/10

def event_identity(e):
    title = re.sub(r"[^a-z0-9]+", " ", norm(e.get("title","")).lower()).strip()
    venue = re.sub(r"[^a-z0-9]+", " ", norm(e.get("venue","")).lower()).strip()
    return (title, venue)

def dedupe(events):
    best = {}
    for e in events:
        k = event_identity(e)
        if not k[0]:
            continue
        if k not in best or richness(e) > richness(best[k]):
            best[k] = e
    return list(best.values())

def clean_event(e, key, today):
    x = copy.deepcopy(e)
    x["source_key"] = key
    x["source"] = SOURCES[key]["name"]
    x["title"] = norm(x.get("title"))
    x["category"] = norm(x.get("category")) or "Event"
    x["overview"] = norm(x.get("overview"))
    x["why"] = norm(x.get("why")) or "See the official organiser page for the latest visitor information."
    x["period"] = norm(x.get("period"))
    x["time"] = norm(x.get("time")) or "Check official information"
    x["venue"] = norm(x.get("venue")) or SOURCES[key]["name"]
    x["mrt"] = norm(x.get("mrt")) or "Check directions"
    x["duration"] = norm(x.get("duration")) or "Flexible"
    x["adult"] = norm(x.get("adult")) or "Check official information"
    x["senior"] = norm(x.get("senior")) or "Check official information"
    x["child"] = norm(x.get("child")) or "Check official information"
    x["link"] = norm(x.get("link")) or SOURCES[key]["url"]
    status, cls = status_for(x["period"], today)
    x["status"], x["statusClass"] = status, cls
    tags = set(x.get("tags") or [])
    tags.add("wheelchair") if "wheelchair" in (x["overview"]+" "+x["venue"]).lower() else None
    if status == "Upcoming": tags.add("upcoming")
    else: tags.add("ongoing")
    if status == "Ending Soon": tags.add("ending")
    x["tags"] = sorted(tags)
    return x

def jsonld_events(soup, key, today):
    out = []
    for node in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(node.string or "")
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            obj = stack.pop()
            if isinstance(obj, dict):
                if "@graph" in obj and isinstance(obj["@graph"], list):
                    stack.extend(obj["@graph"])
                typ = obj.get("@type")
                types = typ if isinstance(typ, list) else [typ]
                if "Event" in types:
                    loc = obj.get("location", {})
                    venue = loc.get("name","") if isinstance(loc, dict) else ""
                    start, end = obj.get("startDate",""), obj.get("endDate","")
                    period = ""
                    try:
                        sd = datetime.fromisoformat(str(start).replace("Z","+00:00")).date() if start else None
                        ed = datetime.fromisoformat(str(end).replace("Z","+00:00")).date() if end else sd
                        if sd and ed:
                            period = f"{sd.isoformat()} to {ed.isoformat()}"
                    except Exception:
                        pass
                    offers = obj.get("offers", {})
                    price = ""
                    if isinstance(offers, dict) and offers.get("price") is not None:
                        price = str(offers.get("price"))
                    out.append(clean_event({
                        "title": obj.get("name",""),
                        "category": "Event",
                        "overview": BeautifulSoup(str(obj.get("description","")), "html.parser").get_text(" "),
                        "period": period,
                        "time": "Check official information",
                        "venue": venue,
                        "adult": price or "Check official information",
                        "link": obj.get("url","") or SOURCES[key]["url"],
                    }, key, today))
            elif isinstance(obj, list):
                stack.extend(obj)
    return [e for e in out if e["title"]]

def text_blocks(soup):
    # Select the smallest usable card, including sites using compound class names.
    selectors = "article, [class*='card'], [class*='event'], [class*='listing'], .item, li"
    blocks = []
    seen = set()
    candidates = list(soup.select(selectors))
    # Some listings have no semantic card classes. Walk a bounded number of
    # ancestors from each event heading instead of treating the whole page as an event.
    for heading in soup.select("h2, h3, h4, h5"):
        candidates.extend(list(heading.parents)[:4])
    for el in candidates:
        if id(el) in seen or el.name in ("html", "body", "script", "style", "nav", "footer") or el.find_parent(["nav", "footer"]):
            continue
        seen.add(id(el))
        if len(el.find_all(["h1", "h2", "h3", "h4", "h5"])) > 1:
            continue
        txt = norm(el.get_text(" ", strip=True))
        if 25 <= len(txt) <= 2500:
            blocks.append((el, txt))
    return blocks

def source_specific_events(soup, key, today):
    """Extract only cards with a title, explicit dates and an official event link."""
    out = []
    seen = set()
    for el, txt in text_blocks(soup):
        period = extract_period(txt)
        if not period:
            continue
        heading = el.find(["h1", "h2", "h3", "h4", "h5", "strong"])
        if not heading:
            heading = el.find("a")
        title = norm(heading.get_text(" ", strip=True) if heading else "")
        if not title or len(title) > 180:
            continue
        lk = heading if heading.name == "a" and heading.get("href") else heading.find("a", href=True)
        if not lk:
            parent_link = heading.find_parent("a", href=True)
            lk = parent_link if parent_link and (parent_link is el or parent_link in el.descendants) else None
        if not lk:
            continue
        link = urljoin(SOURCES[key]["url"], lk["href"])
        if not official_link(link, key):
            continue
        if link.split("#")[0].rstrip("/") == SOURCES[key]["url"].split("#")[0].rstrip("/"):
            continue
        ident = (title.lower(), period.lower())
        if ident in seen:
            continue
        seen.add(ident)
        out.append(clean_event({
            "title": title,
            "category": "Event / Exhibition",
            "overview": txt[:500],
            "period": period,
            "time": "Check official information",
            "venue": SOURCES[key]["name"],
            "link": link,
        }, key, today))
    return out

def parse_source_html(html, key, today):
    soup = BeautifulSoup(html, "html.parser")
    events = jsonld_events(soup, key, today)
    if not events:
        events = source_specific_events(soup, key, today)
    return dedupe([e for e in events if not is_expired(e, today)])


def esplanade_detail_links(listing_html):
    """Return official Esplanade event/detail links found on a listing/festival page."""
    soup = BeautifulSoup(listing_html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(SOURCES["esplanade"]["url"], a["href"])
        if "esplanade.com/whats-on/" not in href:
            continue
        if href.rstrip("/") in {
            SOURCES["esplanade"]["url"].rstrip("/"),
            "https://www.esplanade.com/whats-on/festivals-and-series",
        }:
            continue
        if href not in links:
            links.append(href)
    return links

def parse_esplanade_detail(html, url, today):
    """Extract richer fields from an Esplanade event detail page conservatively."""
    soup = BeautifulSoup(html, "html.parser")
    text = norm(soup.get_text(" ", strip=True))
    h1 = soup.find("h1")
    title = norm(h1.get_text(" ", strip=True) if h1 else "")
    if not title:
        return None

    # Prefer JSON-LD if present, then enrich from visible detail-page text.
    candidates = jsonld_events(soup, "esplanade", today)
    event = candidates[0] if candidates else clean_event({
        "title": title, "category": "Event", "overview": "", "period": "",
        "time": "Check official information", "venue": "Esplanade – Theatres on the Bay",
        "link": url,
    }, "esplanade", today)
    event["title"] = title
    event["link"] = url

    # Esplanade detail pages visibly expose compact date, venue, duration, Free/Tickets from.
    date_patterns = [
        r"\b\d{1,2}\s*&\s*\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b",
        r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b",
        r"\b\d{1,2}\s*[–—-]\s*\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b",
    ]
    if not event.get("period"):
        for pat in date_patterns:
            m = re.search(pat, text)
            if m:
                event["period"] = m.group(0)
                break

    # Venue names on current Esplanade pages.
    venues = re.findall(
        r"\b(?:Esplanade (?:Concert Hall|Theatre|Concourse|Recital Studio|Annexe Studio)|"
        r"Singtel Waterfront Theatre at Esplanade|DBS Foundation Outdoor Theatre at Esplanade|"
        r"Chillout Stage \(Esplanade Concourse\)|Arena \(DBS Foundation Outdoor Theatre at Esplanade\))\b",
        text, re.I)
    if venues:
        event["venue"] = norm(venues[0])

    dm = re.search(r"\b(\d+\s*hrs?(?:\s*\d+\s*mins?)?|\d+\s*mins?)\b", text, re.I)
    if dm:
        event["duration"] = norm(dm.group(1))

    if re.search(r"\bFree\b", text[:1200], re.I):
        event["adult"] = event["senior"] = event["child"] = "Free"
        event["tags"] = sorted(set(event.get("tags", [])) | {"free"})
    else:
        tm = re.search(r"Tickets from\s*\$([0-9]+(?:\.[0-9]{1,2})?)", text, re.I)
        if tm:
            event["adult"] = f"From ${tm.group(1)}"
            # Do not invent concession prices.
            event["senior"] = "Check official information"
            event["child"] = "Check official information"

    # Synopsis: first substantial paragraph after a Synopsis heading, if available.
    syn = soup.find(lambda tag: tag.name in ("h2","h3") and "synopsis" in tag.get_text(" ",strip=True).lower())
    if syn:
        nxt = syn.find_next("p")
        if nxt:
            desc = norm(nxt.get_text(" ", strip=True))
            if len(desc) >= 40:
                event["overview"] = desc[:700]

    # Time: collect visible HH:MM AM/PM occurrences, unique.
    times=[]
    for m in re.finditer(r"\b\d{1,2}:\d{2}\s*(?:AM|PM)\b", text, re.I):
        v=norm(m.group(0))
        if v.lower() not in [x.lower() for x in times]:
            times.append(v)
    if times:
        event["time"]=", ".join(times[:6])

    event = clean_event(event, "esplanade", today)
    # Category/festival pages can contain unrelated prices and dates in navigation.
    # Require event-specific detail before allowing them into a production feed.
    if not event["overview"] or not event["period"] or not venues:
        return None
    return None if is_expired(event, today) else event

def fetch_esplanade_two_stage(listing_html, today, fetcher, max_details=80):
    """Discover detail links from Esplanade listing, fetch each detail page, keep usable current events."""
    links = esplanade_detail_links(listing_html)[:max_details]
    events=[]
    errors=[]
    for url in links:
        try:
            detail=fetcher(url)
            event=parse_esplanade_detail(detail,url,today)
            if event:
                events.append(event)
        except Exception as exc:
            errors.append((url,str(exc)))
    return dedupe(events), errors

def fetch(url, timeout=30):
    r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en-SG,en;q=0.9"}, timeout=timeout)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    print(f"Fetched {r.url}: HTTP {r.status_code}, {len(r.content)} bytes, "
          f"{len(text_blocks(soup))} candidate cards; title={norm(soup.title.get_text() if soup.title else '')[:100]}", flush=True)
    return r.text

def update(previous, today=None, fetcher=fetch):
    today = today or datetime.now(SGT).date()
    all_events = []
    report = {}
    for key, cfg in SOURCES.items():
        prev = previous_for(previous, key)
        try:
            html = fetcher(cfg["url"])
            if key == "esplanade":
                fresh, detail_errors = fetch_esplanade_two_stage(html, today, fetcher)
                # If no detail links/results are usable, fall back to conservative listing parser.
                if not fresh:
                    fresh = parse_source_html(html, key, today)
                if not fresh:
                    raise ValueError("zero usable Esplanade events; preserving previous source records")
                all_events.extend(fresh)
                report[key] = {"status":"fresh", "count":len(fresh),
                               "detail_errors":len(detail_errors)}
            else:
                fresh = parse_source_html(html, key, today)
                if not fresh:
                    raise ValueError("zero usable events; preserving previous source records")
                all_events.extend(fresh)
                report[key] = {"status":"fresh", "count":len(fresh)}
        except Exception as exc:
            fallback = [e for e in prev if not is_expired(e, today)]
            all_events.extend(fallback)
            report[key] = {"status":"fallback", "count":len(fallback), "error":str(exc)[:180]}

    merged = dedupe(all_events)
    # Preserve unknown/legacy-source records, subject only to reliable expiry.
    known = set(SOURCES)
    legacy = [copy.deepcopy(e) for e in previous.get("events", [])
              if source_key(e) not in known and not is_expired(e, today)]
    merged = dedupe(merged + legacy)

    if not merged and previous.get("events"):
        raise RuntimeError("Safety stop: refusing to replace a non-empty valid feed with an empty feed")

    payload = {
        "updated_at": datetime.now(SGT).isoformat(timespec="seconds"),
        "events": sorted(merged, key=lambda e: (e.get("status")=="Upcoming", e.get("title","").lower())),
        "source_report": report,
    }
    return payload

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--output", default=str(OUT))
    args = ap.parse_args(argv)
    path = Path(args.output)
    previous = load_previous(path)
    payload = update(previous)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.dry_run:
        print(json.dumps(payload["source_report"], indent=2))
        print(f"DRY RUN: {len(payload['events'])} events; {path} not modified")
        return 0
    if not payload["events"]:
        raise RuntimeError("Safety stop: refusing to create an empty production feed")
    path.write_text(encoded, encoding="utf-8")
    print(f"Wrote {len(payload['events'])} events to {path}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
