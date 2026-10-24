"""Regression checks for the museum source-loading failures."""
import importlib.util
from datetime import date
from pathlib import Path

P = Path(__file__).resolve().parents[1] / "scripts" / "update_events.py"
spec = importlib.util.spec_from_file_location("museum_reader", P)
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)
TODAY = date(2026, 10, 24)
LISTING = '<a href="/museum/exhibitions/into-the-ocean.html">Into the Ocean</a>'
DETAIL = """<main><h1>Into the Ocean: Journey Beneath</h1>
<p>6 Jun – 1 Nov 2026</p>
<p>This exhibition invites visitors on a journey into the ocean through art and scientific research,
exploring the connections between people and the marine environment.</p></main>"""


def museum_only(monkeypatch, key):
    cfg = dict(u.SOURCES[key])
    monkeypatch.setattr(u, "SOURCES", {key: cfg})
    return cfg


def no_browser(url):
    raise AssertionError("The browser should not run when static detail pages work")


def test_artscience_reads_details_before_rendering(monkeypatch):
    cfg = museum_only(monkeypatch, "artscience")
    calls = []
    def fetch(url):
        calls.append(url)
        return DETAIL if "/exhibitions/" in url else LISTING
    monkeypatch.setattr(u, "fetch", fetch)
    monkeypatch.setattr(u, "render_source", no_browser)
    got = u.update({"events": []}, TODAY, fetcher=fetch)
    assert got["source_report"]["artscience"]["status"] == "fresh"
    assert got["events"][0]["title"] == "Into the Ocean: Journey Beneath"
    assert calls == [cfg["url"], "https://www.marinabaysands.com/museum/exhibitions/into-the-ocean.html"]


def test_artscience_homepage_fallback_when_listing_times_out(monkeypatch):
    cfg = museum_only(monkeypatch, "artscience")
    def fetch(url):
        if url == cfg["url"]:
            raise TimeoutError("listing timed out")
        return DETAIL if "/exhibitions/" in url else LISTING
    monkeypatch.setattr(u, "fetch", fetch)
    monkeypatch.setattr(u, "render_source", no_browser)
    got = u.update({"events": []}, TODAY, fetcher=fetch)
    assert got["source_report"]["artscience"]["status"] == "fresh"
    assert len(got["events"]) == 1


def test_national_museum_browser_retry_can_read_normal_page(monkeypatch):
    cfg = museum_only(monkeypatch, "national_museum")
    detail = DETAIL.replace("Into the Ocean: Journey Beneath", "Museum Exhibition")
    listing = '<a href="/whats-on/exhibition/museum-exhibition">Museum Exhibition</a>'
    def fetch(url):
        if url == cfg["url"]:
            raise ValueError("HTTP 202 with no usable page")
        return detail
    monkeypatch.setattr(u, "fetch", fetch)
    monkeypatch.setattr(u, "render_source", lambda url: listing)
    got = u.update({"events": []}, TODAY, fetcher=fetch)
    assert got["source_report"]["national_museum"]["status"] == "fresh"
    assert got["events"][0]["title"] == "Museum Exhibition"


def test_national_museum_challenge_is_not_reported_as_success(monkeypatch):
    museum_only(monkeypatch, "national_museum")
    def fail(url):
        raise ValueError("Official source requires browser verification")
    monkeypatch.setattr(u, "fetch", fail)
    monkeypatch.setattr(u, "render_source", fail)
    previous = {"events": [{"title": "Preserved event", "period": "Permanent",
                            "source_key": "national_museum", "venue": "National Museum"}]}
    got = u.update(previous, TODAY, fetcher=fail)
    assert got["source_report"]["national_museum"]["status"] == "fallback"
    assert got["events"][0]["title"] == "Preserved event"
