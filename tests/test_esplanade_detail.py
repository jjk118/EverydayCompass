import importlib.util
from datetime import date
from pathlib import Path

P=Path(__file__).resolve().parents[1]/"scripts"/"update_events.py"
spec=importlib.util.spec_from_file_location("ue",P)
u=importlib.util.module_from_spec(spec); spec.loader.exec_module(u)
TODAY=date(2026,9,25)

LISTING="""
<html><body>
<a href="/whats-on/2026/test-paid-show">Test Paid Show</a>
<a href="/whats-on/festivals-and-series/crossing-borders/2026/test-free-show">Test Free Show</a>
</body></html>
"""

PAID="""
<html><body><h1>Test Paid Show</h1>
<div>Music</div><div>25 & 26 Sep 2026</div><div>Esplanade Concert Hall</div>
<div>2hrs 10mins</div><div>Tickets from $10.50</div>
<h2>Synopsis</h2><p>A sufficiently detailed official synopsis for the paid performance at Esplanade.</p>
<h2>Date & Time</h2><div>Time 7:30 PM</div>
</body></html>
"""

FREE="""
<html><body><h1>Test Free Show</h1>
<div>25 Sep 2026</div><div>DBS Foundation Outdoor Theatre at Esplanade</div>
<div>45mins</div><div>Free</div>
<h2>Synopsis</h2><p>A sufficiently detailed official synopsis for this free Esplanade programme.</p>
<div>Time 7:15 PM</div><div>Time 8:30 PM</div>
</body></html>
"""

def test_discovers_esplanade_detail_links():
    links=u.esplanade_detail_links(LISTING)
    assert len(links)==2
    assert all(x.startswith("https://www.esplanade.com/whats-on/") for x in links)

def test_category_page_with_incidental_free_text_is_rejected():
    html = "<h1>Music</h1><nav>Free programmes</nav><p>5mins</p>"
    assert u.parse_esplanade_detail(html, "https://www.esplanade.com/whats-on/music", TODAY) is None

def test_festival_landing_page_is_not_a_performance():
    html = "<h1>Crossing Borders 2026</h1><p>21 &amp; 30 Sep 2026</p><p>Free 5mins</p>"
    assert u.parse_esplanade_detail(html, "https://www.esplanade.com/whats-on/festivals-and-series/crossing-borders/2026", TODAY) is None

def test_paid_detail_enrichment():
    e=u.parse_esplanade_detail(PAID,"https://www.esplanade.com/whats-on/2026/test-paid-show",TODAY)
    assert e["title"]=="Test Paid Show"
    assert e["period"]=="25 & 26 Sep 2026"
    assert e["venue"]=="Esplanade Concert Hall"
    assert e["duration"]=="2hrs 10mins"
    assert e["adult"]=="From $10.50"
    assert e["senior"]=="Check official information"
    assert "7:30 PM" in e["time"]

def test_free_detail_enrichment():
    e=u.parse_esplanade_detail(FREE,"https://www.esplanade.com/whats-on/festivals-and-series/crossing-borders/2026/test-free-show",TODAY)
    assert e["adult"]=="Free" and e["senior"]=="Free" and e["child"]=="Free"
    assert "free" in e["tags"]
    assert e["venue"]=="DBS Foundation Outdoor Theatre at Esplanade"
    assert "7:15 PM" in e["time"] and "8:30 PM" in e["time"]

def test_two_stage_fetch():
    pages={
      "https://www.esplanade.com/whats-on/2026/test-paid-show":PAID,
      "https://www.esplanade.com/whats-on/festivals-and-series/crossing-borders/2026/test-free-show":FREE,
    }
    got,errors=u.fetch_esplanade_two_stage(LISTING,TODAY,lambda url:pages[url])
    assert len(got)==2 and errors==[]

def test_detail_failure_does_not_destroy_other_details():
    pages={"https://www.esplanade.com/whats-on/2026/test-paid-show":PAID}
    def f(url):
        if url in pages:return pages[url]
        raise RuntimeError("detail unavailable")
    got,errors=u.fetch_esplanade_two_stage(LISTING,TODAY,f)
    assert len(got)==1 and len(errors)==1

def test_update_esplanade_zero_details_falls_back_previous():
    previous={"events":[{
      "title":"Previous Esplanade","period":"Permanent","source_key":"esplanade",
      "venue":"Esplanade","overview":"previous valid","category":"Event","time":"7pm",
      "mrt":"Esplanade MRT","duration":"60 min","adult":"Free","senior":"Free","child":"Free",
      "link":"https://www.esplanade.com/whats-on/old","tags":[]
    }]}
    def f(url):
        if url==u.SOURCES["esplanade"]["url"]: return "<html>No links or parseable event</html>"
        raise RuntimeError("offline")
    got=u.update(previous,TODAY,fetcher=f)
    assert any(e["title"]=="Previous Esplanade" for e in got["events"])
    assert got["source_report"]["esplanade"]["status"]=="fallback"

def test_festival_discovery_follows_performance_links():
    festival="https://www.esplanade.com/whats-on/festivals-and-series/demo/2026"
    detail="https://www.esplanade.com/whats-on/2026/test-paid-show"
    pages={festival:'<h1>Demo festival</h1><a href="'+detail+'">Paid show</a>',detail:PAID}
    got, errors=u.fetch_esplanade_two_stage('<a href="'+festival+'">Festival</a>',TODAY,lambda url:pages[url])
    assert [e["title"] for e in got] == ["Test Paid Show"]
    assert errors == []
