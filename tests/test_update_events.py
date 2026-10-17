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

def test_nlb_heading_sections_do_not_mix_neighbouring_exhibitions():
    html = """<main><h2 id="one">The Albatross File</h2><ul>
    <li>Permanent exhibition</li><li>Level 10, National Library Building</li></ul>
    <p>A current exhibition describing Singapore's history through original documents and official records.</p>
    <hr><h2 id="two">A finished exhibition</h2><ul><li>1 Jan 2025 - 2 Jan 2025</li></ul>
    <p>This old exhibition has a long description but it should no longer appear in the current feed.</p></main>"""
    got = u.parse_source_html(html, "nlb", date(2026, 10, 18))
    assert [e["title"] for e in got] == ["The Albatross File"]
    assert got[0]["link"].endswith("#one")
    assert got[0]["venue"] == "Level 10, National Library Building"

def test_worded_date_range_not_mistaken_for_published_date():
    html = """<main><h1>Architecture Exhibition</h1><p>12 August 2026</p>
    <p>Discover the official architecture exhibition. Visit from 12 August to 26 October 2026 at The URA Centre.</p>
    <p>Date: 12 August to 26 October 2026</p></main>"""
    got = u.parse_official_detail(html, "https://www.ura.gov.sg/get-involved/events-and-exhibitions/test/", "ura", date(2026,10,18))
    assert len(got) == 1
    assert u.finite_end_date(got[0]["period"]) == date(2026,10,26)

def test_detail_without_visitor_dates_is_not_an_event():
    html = "<main><h1>Visit Us</h1><p>Published 12 August 2026</p><p>" + "Visitor information. " * 10 + "</p></main>"
    assert not u.parse_official_detail(html, "https://www.nationalgallery.sg/sg/en/exhibitions/test.html", "national_gallery", date(2026,10,18))

def test_visit_singapore_abbreviated_years():
    period=u.extract_period("30 APR ’26 - 01 NOV ’26")
    assert u.finite_end_date(period) == date(2026,11,1)

def test_rendered_gardens_cards_use_event_dates_not_weekday_labels():
    html="""<a class="programme-tile" href="/en/things-to-do/calendar-of-events/sunflower.html">
    <div class="title"><h6>Sunflower Surprise</h6></div><div class="detail">A seasonal floral display.</div>
    <span class="gbb-event">Fri, 9 Oct - Mon, 9 Nov 2026</span>
    <span class="gbb-hours">9.00am - 9.00pm</span><span class="gbb-location">Flower Dome</span></a>
    <a class="programme-tile" href="/en/things-to-do/calendar-of-events/jurassic.html">
    <div class="title"><h6>Jurassic World</h6></div><span class="gbb-event">Ongoing</span></a>"""
    got=u.parse_source_html(html,"gardens",date(2026,10,18))
    assert {e["title"] for e in got} == {"Sunflower Surprise", "Jurassic World"}
    event=next(e for e in got if e["title"]=="Sunflower Surprise")
    assert u.finite_end_date(event["period"]) == date(2026,11,9)
    assert event["venue"] == "Flower Dome"

def test_catch_reads_rendered_detail_and_checks_free_admission(monkeypatch):
    cfg={"name":"Catch","url":"https://www.catch.sg/Event?EventCategory=Free%20Events","host":"catch.sg"}
    monkeypatch.setitem(u.SOURCES,"catch_sg",cfg)
    monkeypatch.setattr(u,"fetch",lambda url:"<html><title>Loading</title></html>")
    html="""<main><h1>Community Exhibition</h1><p>
    An exhibition sharing local stories through art, original documents and community contributions.</p>
    <p>Event Details Date: 30 Apr 2026 - 11 Nov 2026</p><p>Admission is free.</p></main>"""
    monkeypatch.setattr(u,"render_source",lambda url:html)
    listing='<a href="/Event/Community-Exhibition-20260703092641">Community Exhibition</a>'
    got=u.fetch_official_details(listing,"catch_sg",date(2026,10,18),u.fetch)
    assert len(got)==1 and got[0]["adult"]=="Free"
    assert u.parse_official_detail(html.replace("Admission is free.","Tickets cost $20."),
                                  got[0]["link"],"catch_sg",date(2026,10,18)) == []

def test_catch_uses_page_metadata_not_hidden_account_modal(monkeypatch):
    monkeypatch.setitem(u.SOURCES, "catch_sg", {"name":"Catch", "url":"https://www.catch.sg/Event?EventCategory=Free%20Events", "host":"catch.sg"})
    html="""<html><head><meta property="og:title" content="Community Arts">
    <meta property="og:description" content="Discover a community exhibition of contemporary art and shared local stories."></head>
    <body><h1>My Catch Lists</h1><div>Date 18 Oct 2026 - 30 Oct 2026</div>
    <div>Tickets &amp; Prices Free</div></body></html>"""
    got=u.parse_official_detail(html,"https://www.catch.sg/Event/Community-Arts-20260703092641",
                               "catch_sg",date(2026,10,18))
    assert len(got)==1 and got[0]["title"]=="Community Arts"
    assert got[0]["adult"]=="Free"

def test_catch_uses_event_date_not_unrelated_page_campaign(monkeypatch):
    monkeypatch.setitem(u.SOURCES,"catch_sg",{"name":"Catch","url":"https://www.catch.sg/Event","host":"catch.sg"})
    html="""<html><head><meta property="og:title" content="BBQ Brew and Beats">
    <meta property="og:description" content="A community event with music, art and food at the venue."></head>
    <body><div>Site campaign 26 Jun - 31 Dec 2026</div>
    <div>Tickets &amp; Prices Free</div><div>Event Details Date 17 Oct 2026 Opening Hours Full Day Location Gillman Barracks</div></body></html>"""
    assert not u.parse_official_detail(html,"https://www.catch.sg/Event/BBQ-20261011090535","catch_sg",date(2026,10,18))
    current=html.replace("Date 17 Oct 2026", "Date 18 Oct 2026")
    got=u.parse_official_detail(current,"https://www.catch.sg/Event/BBQ-20261011090535","catch_sg",date(2026,10,18))
    assert len(got)==1 and got[0]["period"]=="18 Oct 2026"
