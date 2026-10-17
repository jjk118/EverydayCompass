import json
from datetime import date
from pathlib import Path
import importlib.util, tempfile

P = Path(__file__).resolve().parents[1] / "scripts" / "update_events.py"
spec = importlib.util.spec_from_file_location("u", P)
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)

TODAY = date(2026,9,25)

def ev(title, period, source_key="sccc", venue="Venue", overview="Useful overview"):
    return {"title":title,"period":period,"source_key":source_key,"venue":venue,
            "overview":overview,"category":"Exhibition","time":"10am","mrt":"MRT",
            "duration":"60 min","adult":"Free","senior":"Free","child":"Free",
            "link":"https://example.com","tags":[]}

def test_expiry_finite_dates_only():
    assert u.is_expired(ev("Old","1 Jan 2026 – 2 Jan 2026"), TODAY)
    assert not u.is_expired(ev("Current","1 Sep 2026 – 30 Sep 2026"), TODAY)
    assert not u.is_expired(ev("Permanent","Permanent"), TODAY)
    assert not u.is_expired(ev("Ongoing","Ongoing"), TODAY)
    assert not u.is_expired(ev("Daily","Daily"), TODAY)

def test_status():
    assert u.status_for("1 Oct 2026 – 10 Oct 2026", TODAY)[0] == "Upcoming"
    assert u.status_for("1 Sep 2026 – 30 Sep 2026", TODAY)[0] == "Ending Soon"
    assert u.status_for("Permanent", TODAY)[0] == "Ongoing"

def test_dedupe_prefers_richer():
    a=ev("Same","1 Sep 2026 – 30 Sep 2026", overview="")
    b=ev("Same","1 Sep 2026 – 30 Sep 2026", overview="Much richer description")
    b["why"]="Useful"; b["senior"]="Free"
    got=u.dedupe([a,b])
    assert len(got)==1 and got[0]["overview"]=="Much richer description"

def test_jsonld_event_parser():
    html="""<html><script type="application/ld+json">
    {"@context":"https://schema.org","@type":"Event","name":"Test Exhibition",
    "startDate":"2026-09-20","endDate":"2026-10-20",
    "location":{"@type":"Place","name":"Test Venue"},"description":"Official description",
    "url":"https://singaporeccc.org.sg/events/test/"}
    </script></html>"""
    got=u.parse_source_html(html,"sccc",TODAY)
    assert len(got)==1
    assert got[0]["title"]=="Test Exhibition"
    assert got[0]["venue"]=="Test Venue"

def test_source_failure_preserves_previous():
    previous={"events":[ev("Keep Me","1 Sep 2026 – 30 Oct 2026","sccc")]}
    def fail(url): raise RuntimeError("network down")
    got=u.update(previous,TODAY,fetcher=fail)
    assert any(x["title"]=="Keep Me" for x in got["events"])
    assert got["source_report"]["sccc"]["status"]=="fallback"

def test_zero_result_preserves_previous():
    previous={"events":[ev("Keep Me","Permanent","sccc")]}
    def empty(url): return "<html><body>No parseable events</body></html>"
    got=u.update(previous,TODAY,fetcher=empty)
    assert any(x["title"]=="Keep Me" for x in got["events"])

def test_expired_fallback_removed():
    previous={"events":[ev("Expired","1 Jan 2026 – 2 Jan 2026","sccc"),
                        ev("Keep","Permanent","sccc")]}
    def fail(url): raise RuntimeError("fail")
    got=u.update(previous,TODAY,fetcher=fail)
    titles={x["title"] for x in got["events"]}
    assert "Expired" not in titles and "Keep" in titles

def test_never_replace_nonempty_with_empty():
    previous={"events":[ev("Expired","1 Jan 2026 – 2 Jan 2026","sccc")]}
    def fail(url): raise RuntimeError("fail")
    try:
        u.update(previous,TODAY,fetcher=fail)
    except RuntimeError as e:
        assert "refusing" in str(e)
    else:
        raise AssertionError("Safety stop did not trigger")

def test_legacy_unknown_source_preserved():
    previous={"events":[ev("Legacy","Permanent","old_source")]}
    def fail(url): raise RuntimeError("fail")
    got=u.update(previous,TODAY,fetcher=fail)
    assert any(x["title"]=="Legacy" for x in got["events"])

def test_dry_run_byte_identical(monkeypatch, tmp_path):
    p=tmp_path/"events.json"
    original=json.dumps({"events":[ev("Keep","Permanent","sccc")]},indent=2)+"\n"
    p.write_text(original,encoding="utf-8")
    monkeypatch.setattr(u,"fetch",lambda url: (_ for _ in ()).throw(RuntimeError("offline")))
    # main resolves global fetch as default at function definition; directly verify no-write contract
    before=p.read_bytes()
    previous=u.load_previous(p)
    u.update(previous,TODAY,fetcher=lambda url: (_ for _ in ()).throw(RuntimeError("offline")))
    after=p.read_bytes()
    assert before==after


def test_empty_first_run_leaves_feed_absent(monkeypatch, tmp_path):
    import pytest
    path = tmp_path / "events.json"
    monkeypatch.setattr(u, "update", lambda previous: {"events": [], "source_report": {}})
    with pytest.raises(RuntimeError, match="empty production feed"):
        u.main(["--output", str(path)])
    assert not path.exists()


def test_actual_dry_run_leaves_missing_feed_absent(monkeypatch, tmp_path):
    path = tmp_path / "events.json"
    monkeypatch.setattr(u, "update", lambda previous: {"events": [], "source_report": {}})
    assert u.main(["--dry-run", "--output", str(path)]) == 0
    assert not path.exists()

def test_month_first_listing_dates_and_expiry():
    html = """<div class="event-list"><div class="event-tile">
    <span>Oct 01, 2026 - Dec 30, 2027</span>
    <h3><a href="/events/dance/">Dance Connections</a></h3>
    <p>Guided dance sessions at the cultural centre.</p></div>
    <div class="event-tile"><span>Oct 01, 2025 - Oct 02, 2025</span>
    <h3><a href="/events/old/">Finished event</a></h3></div></div>"""
    got = u.parse_source_html(html, "sccc", date(2026, 10, 18))
    assert [e["title"] for e in got] == ["Dance Connections"]
    assert u.finite_end_date(got[0]["period"]) == date(2027, 12, 30)
    assert got[0]["link"] == "https://singaporeccc.org.sg/events/dance/"

def test_unclassified_card_single_date_and_nonofficial_link():
    html = """<section><div><h3><a href="/events/talk/">Culture Talk</a></h3>
    <p>Nov 14, 2026</p><p>A talk by the official organiser.</p></div></section>
    <article><h3><a href="https://singaporeccc.org.sg.evil.example/show">Bad host</a></h3>
    <p>Nov 14, 2026</p></article>"""
    got = u.parse_source_html(html, "sccc", date(2026, 10, 18))
    assert [e["title"] for e in got] == ["Culture Talk"]
    assert u.finite_end_date(got[0]["period"]) == date(2026, 11, 14)
    assert got[0]["status"] == "Upcoming"

def test_listing_does_not_combine_separate_events_or_navigation():
    html = """<div class="event-list"><div><h3>Undated heading</h3></div>
    <div><p>Nov 14, 2026</p><a href="/events/talk/">Details</a></div></div>
    <nav><li><h3><a href="/events/">All Events</a></h3><p>Nov 14, 2026</p></li></nav>"""
    # The dated "Details" link may be a card, but must never borrow the unrelated heading.
    got = u.parse_source_html(html, "sccc", date(2026, 10, 18))
    assert not any(e["title"] in ("Undated heading", "All Events") for e in got)
