"""Tests for scripts/run_whats_on.py. Place in the tests/ folder. Uses only made-up data."""
import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_whats_on as rw  # noqa: E402

SGT = ZoneInfo("Asia/Singapore")
TODAY = date(2026, 10, 14)
NOW = datetime(2026, 10, 14, 7, 0, tzinfo=SGT)

LD = """<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
 {"@type":"Event","name":"Lantern Walk","startDate":"2026-10-10","endDate":"2026-10-30",
  "location":{"name":"Demo Park"},"url":"https://demo.example.sg/lantern","isAccessibleForFree":true,
  "description":"<p>Evening <b>lanterns</b></p>"},
 {"@type":"Event","name":"Old Show","startDate":"2026-08-01","endDate":"2026-09-01"},
 {"@type":"Event","name":"Elsewhere","startDate":"2026-10-12","endDate":"2026-10-20","url":"https://evil.example.com/x"}
]}</script></head><body></body></html>"""

DEMO = {"demo": {"name": "Demo Venue", "url": "https://demo.example.sg/whats-on", "host": "demo.example.sg"}}


def ev(title, period, key="demo"):
    return {"title": title, "venue": "V", "period": period, "source_key": key, "status": "Ongoing", "statusClass": ""}


def test_end_date_forms():
    f = rw.finite_end_date_v2
    assert f("12 \u2013 27 Sep 2026") == date(2026, 9, 27)      # Mid-Autumn Festival style
    assert f("1 \u2013 30 Sep 2026") == date(2026, 9, 30)       # Crossing Borders style
    assert f("12 Aug \u2013 26 Oct 2026") == date(2026, 10, 26)
    assert f("9 Jul 2026 \u2013 26 Jan 2027") == date(2027, 1, 26)
    assert f("Selected Saturdays \u00b7 29 Aug 2026 \u2013 10 Jan 2027") == date(2027, 1, 10)
    assert f("2 Oct 2026") == date(2026, 10, 2)


def test_open_ended_periods_are_kept():
    for p in ("Permanent exhibition", "Daily", "Ongoing", "Various dates", "", "Check official information"):
        assert rw.finite_end_date_v2(p) is None


def test_status_short_range():
    with rw.patched(rw.BUILTIN):   # same conditions as a real refresh
        assert rw.status_for_v2("1 \u2013 20 Oct 2026", TODAY)[0] == "Ending Soon"
        assert rw.status_for_v2("20 \u2013 30 Oct 2026", TODAY)[0] == "Upcoming"
        assert rw.status_for_v2("1 \u2013 30 Sep 2026", TODAY)[0] == "Expired"


def test_load_sources_rules(tmp_path):
    good = {"sources": [
        {"id": "a1", "name": "A", "url": "https://www.a.example.sg/x", "enabled": True},
        {"id": "b1", "name": "B", "url": "http://insecure.example.sg", "enabled": True},
        {"id": "c1", "name": "C", "url": "https://c.example.sg", "enabled": False},
        {"name": "No Id", "url": "https://d.example.sg"},
    ]}
    p = tmp_path / "sources.json"
    p.write_text(json.dumps(good))
    s, w = rw.load_sources(p)
    assert list(s) == ["a1", "no_id"]
    assert s["a1"]["host"] == "a.example.sg"
    assert any("https" in x for x in w)


def test_load_sources_limit_and_fallback(tmp_path):
    many = {"sources": [{"id": f"s{i}", "name": f"S{i}", "url": f"https://s{i}.example.sg"} for i in range(20)]}
    p = tmp_path / "sources.json"
    p.write_text(json.dumps(many))
    s, w = rw.load_sources(p)
    assert len(s) == rw.MAX_SOURCES and w
    s2, w2 = rw.load_sources(tmp_path / "missing.json")
    assert set(s2) == set(rw.BUILTIN) and w2
    p.write_text("{not json")
    s3, _ = rw.load_sources(p)
    assert set(s3) == set(rw.BUILTIN)


def test_fresh_source_records_date_and_drops_old():
    prev = {"events": [ev("Stale", "1 \u2013 30 Sep 2026")], "sources": []}
    out = rw.run(prev, DEMO, today=TODAY, now=NOW, fetcher=lambda url: LD)
    titles = {e["title"] for e in out["events"]}
    assert titles == {"Lantern Walk", "Elsewhere"}           # Old Show finished; Stale removed
    row = out["sources"][0]
    assert row["status"] == "ok" and row["last_success"].startswith("2026-10-14T07:00")
    assert out["all_sources_failed"] is False
    lantern = next(e for e in out["events"] if e["title"] == "Lantern Walk")
    assert lantern["link"] == "https://demo.example.sg/lantern" and "Free" in lantern["adult"]
    other = next(e for e in out["events"] if e["title"] == "Elsewhere")
    assert other["link"] == DEMO["demo"]["url"]               # non-official link replaced


def test_failed_source_keeps_old_date_and_expires_finished():
    def boom(url):
        raise TimeoutError("read timed out")
    prev = {"events": [ev("Stale", "12 \u2013 27 Sep 2026"), ev("Still on", "1 Oct \u2013 30 Nov 2026"),
                       ev("Permanent", "Permanent exhibition")],
            "sources": [{"id": "demo", "last_success": "2026-10-05T06:46:00+08:00"}]}
    out = rw.run(prev, DEMO, today=TODAY, now=NOW, fetcher=boom)
    assert {e["title"] for e in out["events"]} == {"Still on", "Permanent"}
    row = out["sources"][0]
    assert row["status"] == "fallback" and row["last_success"] == "2026-10-05T06:46:00+08:00"
    assert out["all_sources_failed"] is True and "timed out" in row["error"]


def test_no_previous_date_stays_empty():
    def boom(url):
        raise TimeoutError("x")
    out = rw.run({"events": [ev("Still on", "1 Oct \u2013 30 Nov 2026")]}, DEMO, today=TODAY, now=NOW, fetcher=boom)
    assert out["sources"][0]["last_success"] is None


def test_removed_source_events_dropped_but_hand_added_kept():
    hand = {"title": "Hand added", "venue": "V", "period": "Permanent exhibition"}
    prev = {"events": [ev("From removed", "1 Oct \u2013 30 Nov 2026", key="gone"), hand]}
    out = rw.run(prev, DEMO, today=TODAY, now=NOW, fetcher=lambda url: LD)
    titles = {e["title"] for e in out["events"]}
    assert "From removed" not in titles and "Hand added" in titles


def test_patches_are_restored():
    import update_events as ue
    before = (ue.SOURCES, ue.finite_end_date, ue.status_for, ue.parse_source_html)
    rw.run({"events": []}, DEMO, today=TODAY, now=NOW, fetcher=lambda url: LD)
    assert (ue.SOURCES, ue.finite_end_date, ue.status_for, ue.parse_source_html) == before

def test_builtin_uses_nested_event_subtypes():
    html = """<script type="application/ld+json">{
    "@type":"ItemList","itemListElement":[{"@type":"ListItem","item":{
    "@type":"ExhibitionEvent","name":"Nested exhibition",
    "startDate":"2026-10-01","endDate":"2026-12-01",
    "url":"https://singaporeccc.org.sg/events/nested/"}}]}</script>"""
    out = rw.run({"events":[]}, {"sccc":rw.BUILTIN["sccc"]},
                 today=TODAY, now=NOW, fetcher=lambda url:html)
    assert [e["title"] for e in out["events"]] == ["Nested exhibition"]
    assert out["all_sources_failed"] is False

def test_listing_url_stays_on_configured_source_domain(tmp_path):
    path=tmp_path/"sources.json"
    path.write_text(json.dumps({"sources":[
        {"id":"visit_singapore","url":"https://www.visitsingapore.com/things-to-do/top-things-to-do/",
         "listing_url":"https://www.visitsingapore.com/whats-happening/all-happenings/"},
        {"id":"bad","url":"https://example.sg/","listing_url":"https://example.sg.evil.test/feed"}
    ]}))
    sources,_=rw.load_sources(path)
    assert sources["visit_singapore"]["listing_url"].endswith("/all-happenings/")
    assert "listing_url" not in sources["bad"]

def test_catch_structured_events_must_be_confirmed_free():
    config={"catch_sg":{"name":"Catch Free Events","url":"https://www.catch.sg/Event?EventCategory=Free%20Events","host":"catch.sg"}}
    html="""<script type="application/ld+json">[
      {"@type":"Event","name":"Free show","startDate":"2026-10-20","endDate":"2026-10-21",
       "url":"https://www.catch.sg/Event/free","isAccessibleForFree":true},
      {"@type":"Event","name":"Paid show","startDate":"2026-10-20","endDate":"2026-10-21",
       "url":"https://www.catch.sg/Event/paid","offers":{"price":20}}
    ]</script>"""
    with rw.patched(config):
        events=rw.parse_source_html_v2(html,"catch_sg",TODAY)
    assert [e["title"] for e in events] == ["Free show"]
