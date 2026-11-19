import json
from pathlib import Path

from factpage.trends import Trend, merge, parse_feed, parse_google_trends, parse_wiki_top

FIX = Path(__file__).parent / "fixtures"


def test_google_trends_fixture_parses_all_news_urls():
    trends = parse_google_trends((FIX / "trends_in.xml").read_bytes(), "IN")
    assert len(trends) == 10
    assert all(t.source == "google_trends" and t.geo == "IN" for t in trends)
    assert sum(len(t.urls) for t in trends) == 30
    assert trends[0].signal >= 100


def test_google_trends_keeps_todays_headlines_as_context():
    trends = parse_google_trends((FIX / "trends_in.xml").read_bytes(), "IN")
    assert sum(len(t.news) for t in trends) == 30
    assert all(isinstance(h, str) and h for t in trends for h in t.news)


def test_wiki_top_drops_non_articles():
    titles = [t.title for t in parse_wiki_top(json.loads((FIX / "wiki_top.json").read_text()))]
    assert "Main Page" not in titles
    assert not any(t.startswith(("Special:", "Wikipedia:", "File:", "Portal:")) for t in titles)
    assert "Robert Pattinson" in titles  # underscores become spaces


def test_wiki_top_keeps_money_lists_drops_other_lists():
    data = {"items": [{"articles": [
        {"article": "List_of_highest-grossing_Indian_films", "views": 9000, "rank": 1},
        {"article": "List_of_Nazi_concentration_camps", "views": 8000, "rank": 2}]}]}
    titles = [t.title for t in parse_wiki_top(data)]
    assert titles == ["List of highest-grossing Indian films"]


def test_wiki_bot_spike_dropped_when_almost_all_desktop():
    all_access = {"items": [{"articles": [{"article": "Botty", "views": 100000, "rank": 1},
                                          {"article": "Human", "views": 100000, "rank": 2}]}]}
    desktop = {"items": [{"articles": [{"article": "Botty", "views": 97000, "rank": 1},
                                       {"article": "Human", "views": 30000, "rank": 2}]}]}
    titles = [t.title for t in parse_wiki_top(all_access, desktop)]
    assert titles == ["Human"]


def test_feed_items_become_trends_with_link():
    trends = parse_feed((FIX / "bbc_business.xml").read_bytes(), "BBC Business", limit=5)
    assert len(trends) == 5
    assert trends[0].urls and trends[0].urls[0].startswith("https://")


def test_old_feed_items_are_dropped():
    from datetime import datetime, timezone
    xml = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>
    <item><title>SpiceJet approves Rs 5,500 crore raise</title><link>https://www.bbc.com/new</link>
      <pubDate>Wed, 18 Nov 2026 10:00:00 GMT</pubDate></item>
    <item><title>ICICI Pru Life Q4 net profit falls 26%</title><link>https://www.bbc.com/old</link>
      <pubDate>Tue, 24 Apr 2018 10:00:00 GMT</pubDate></item>
    <item><title>Undated item</title><link>https://www.bbc.com/undated</link></item>
    </channel></rss>"""
    now = datetime(2026, 11, 19, 6, 0, tzinfo=timezone.utc)
    titles = [t.title for t in parse_feed(xml, "X", limit=5, max_age_days=2, now=now)]
    assert titles == ["SpiceJet approves Rs 5,500 crore raise", "Undated item"]


def test_merge_combines_same_topic_across_sources():
    a = Trend("Jensen Huang", "google_trends", "US", ["https://a.com/1"], 500)
    b = Trend("jensen huang", "wikipedia", "", ["https://b.com/2"], 900)
    merged = merge([a, b])
    assert len(merged) == 1
    assert set(merged[0].urls) == {"https://a.com/1", "https://b.com/2"}
    assert merged[0].signal == 900


def test_garbage_xml_gives_empty_list():
    assert parse_google_trends(b"<html>oops", "IN") == []
    assert parse_feed(b"not a feed", "X") == []
