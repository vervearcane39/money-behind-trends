"""Trend collection: Google Trends RSS, Wikipedia top pageviews, publisher business RSS feeds."""
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import feedparser

from . import http
from .history import topic_key


@dataclass
class Trend:
    title: str
    source: str  # google_trends | wikipedia | feed | evergreen
    geo: str
    urls: list[str] = field(default_factory=list)
    signal: int = 0
    news: list[str] = field(default_factory=list)  # today's headlines about it (context for the AI)


_HT = {"ht": "https://trends.google.com/trending/rss"}
_WIKI_NS = ("Special:", "Wikipedia:", "File:", "Portal:", "Talk:", "Template:", "Help:", "Category:", "User:",
            "Draft:", "Module:", "MediaWiki:", "Main_Page", "-")
_MONEY_LIST = re.compile(r"grossing|expensive|valuable|revenue|richest|largest_companies", re.I)


def parse_google_trends(xml: bytes, geo: str) -> list[Trend]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        traffic = int(re.sub(r"\D", "", item.findtext("ht:approx_traffic", "0", _HT)) or 0)
        urls = [u.text.strip() for u in item.iterfind("ht:news_item/ht:news_item_url", _HT) if u.text]
        news = [h.text.strip() for h in item.iterfind("ht:news_item/ht:news_item_title", _HT) if h.text]
        if title:
            out.append(Trend(title, "google_trends", geo, urls, traffic, news))
    return out


def parse_wiki_top(all_access: dict, desktop: dict | None = None) -> list[Trend]:
    def views(d):
        return {a["article"]: a["views"] for a in d["items"][0]["articles"]} if d else {}

    desk = views(desktop)
    out = []
    for a in all_access["items"][0]["articles"]:
        t = a["article"]
        if t.startswith(_WIKI_NS) or (t.startswith("List_of_") and not _MONEY_LIST.search(t)):
            continue
        # ponytail: humans read mostly on mobile, so >90% desktop views ≈ automated spike.
        # Upgrade path: compare against the article's own 7-day history.
        if desk.get(t, 0) > 0.9 * a["views"]:
            continue
        out.append(Trend(t.replace("_", " "), "wikipedia", "", [], a["views"]))
    return out


def parse_feed(xml: bytes, name: str, limit: int = 5) -> list[Trend]:
    d = feedparser.parse(xml)
    return [Trend(e.title.strip(), "feed", "", [e.link], 0)
            for e in d.entries[:limit] if e.get("title") and e.get("link", "").startswith("https://")]


def merge(trends: list[Trend]) -> list[Trend]:
    by_key: dict[str, Trend] = {}
    for t in trends:
        k = topic_key(t.title)
        if k not in by_key:
            by_key[k] = Trend(t.title, t.source, t.geo, list(t.urls), t.signal, list(t.news))
        else:
            m = by_key[k]
            m.urls += [u for u in t.urls if u not in m.urls]
            m.news += [h for h in t.news if h not in m.news]
            m.signal = max(m.signal, t.signal)
    return list(by_key.values())


def collect(cfg: dict, now: datetime | None = None) -> list[Trend]:
    now = now or datetime.now(timezone.utc)
    out: list[Trend] = []
    for geo in cfg["geos"]:
        r = http.get(f"https://trends.google.com/trending/rss?geo={geo}")
        if r:
            out += parse_google_trends(r.content, geo)
    if cfg.get("wikipedia_top"):
        base = "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia"
        for days_back in (1, 2):  # yesterday's file can be missing early in the UTC day
            day = (now - timedelta(days=days_back)).strftime("%Y/%m/%d")
            r = http.get(f"{base}/all-access/{day}", check_robots=False)
            if r:
                d = http.get(f"{base}/desktop/{day}", check_robots=False)
                out += parse_wiki_top(r.json(), d.json() if d else None)[: cfg["wikipedia_top"]]
                break
    for f in cfg.get("feeds") or []:
        r = http.get(f["url"])
        if r:
            out += parse_feed(r.content, f["name"], f.get("limit", 5))
    return merge(out)
