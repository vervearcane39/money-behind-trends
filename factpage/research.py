"""Research: fetch allowlisted, non-paywalled, robots-permitted pages + the Wikipedia article and its references."""
import functools
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import quote, urlsplit

import lxml.etree
import lxml.html
import trafilatura

from . import http
from .textnorm import missing_numbers, norm, numbers, registrable_domain, years
from .trends import Trend

log = logging.getLogger("factpage")
WIKI_API = "https://en.wikipedia.org/w/api.php"
MAX_DOCS = 8
MAX_FETCHES = 20


@dataclass
class SourceDoc:
    url: str
    domain: str
    name: str
    text: str
    fetched_at: str
    wiki_revid: int | None = None
    published: str | None = None  # YYYY-MM-DD from the page's own metadata; None if the page states none


_ARCHIVE = re.compile(r"^https?://web\.archive\.org/web/(\d+)(?:[a-z]{2}_)?/(.+)$")


def original_url(url: str) -> str:
    """For a Wayback Machine copy, the original page (over https); otherwise the URL itself.
    Archived copies are judged (allowlist, paywall, domain, robots) by the original publisher."""
    m = _ARCHIVE.match(url)
    return "https://" + m.group(2).split("://", 1)[-1] if m else url


def _raw_snapshot(url: str) -> str:
    """The `id_` form serves the page exactly as the publisher did, without the Wayback toolbar."""
    m = _ARCHIVE.match(url)
    return f"https://web.archive.org/web/{m.group(1)}id_/{m.group(2)}" if m else url


def _host(url: str) -> str:
    h = (urlsplit(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def _under(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def _allow_key(host: str, allow: dict) -> str | None:
    keys = [k for k in allow if _under(host, k)]
    return max(keys, key=len) if keys else None


def allowed(url: str, cfg: dict) -> bool:
    if urlsplit(url).scheme != "https":
        return False
    host, src = _host(original_url(url)), cfg["sources"]
    if any(_under(host, d) for d in src["deny"]):
        return False
    return bool(_allow_key(host, src["allow"])) or any(host.endswith(s) for s in src["allow_suffixes"])


def source_name(url: str, cfg: dict) -> str:
    orig = original_url(url)
    key = _allow_key(_host(orig), cfg["sources"]["allow"])
    name = cfg["sources"]["allow"][key] if key else registrable_domain(orig)
    return name + " (archived)" if orig != url else name


def is_paywalled(html: str, text: str, url: str, cfg: dict) -> bool:
    url = original_url(url)
    host_path = _host(url) + urlsplit(url).path
    for p in cfg["sources"]["paywall"]:
        if ("/" in p and (host_path == p or host_path.startswith(p.rstrip("/") + "/"))) or ("/" not in p and _under(_host(url), p)):
            return True
    if re.search(r'"isAccessibleForFree"\s*:\s*"?false"?', html, re.I):
        return True
    return len(text.split()) < 150


def _html_text(r) -> str:
    """Decode a page correctly. Without a charset header, requests assumes Latin-1, which turns £/₹/€
    into garbage like 'Â£' and silently breaks number matching. Use the header's charset if any, else the
    page's own <meta charset>, else UTF-8."""
    headers, raw = getattr(r, "headers", {}) or {}, getattr(r, "content", None)
    if raw is None or "charset=" in headers.get("content-type", "").lower():
        return r.text
    m = re.search(rb"""<meta[^>]+charset=["']?([\w-]+)""", raw[:4096], re.I)
    try:
        return raw.decode(m.group(1).decode() if m else "utf-8", errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def fetch_doc(url: str, cfg: dict) -> SourceDoc | None:
    if not allowed(url, cfg):
        log.info("skip (not allowlisted): %s", url)
        return None
    if original_url(url) != url and not http.robots_allowed(original_url(url)):
        log.info("skip (original publisher's robots.txt disallows): %s", url)
        return None
    r = http.get(url)
    if r is None:
        return None
    if not allowed(r.url, cfg):
        log.info("skip (redirected off allowlist): %s -> %s", url, r.url)
        return None
    page = _html_text(r)
    text = trafilatura.extract(page, include_comments=False, include_tables=True, favor_precision=True) or ""
    if is_paywalled(page, text, r.url, cfg):
        log.info("skip (paywalled/too short): %s", r.url)
        return None
    return SourceDoc(r.url, registrable_domain(original_url(r.url)), source_name(r.url, cfg), text,
                     datetime.now(timezone.utc).isoformat(), published=_published(page))


def _published(page: str) -> str | None:
    """Original publication date from the page's metadata, never a guess (strict htmldate settings)."""
    meta = trafilatura.extract_metadata(page, date_config={"original_date": True, "extensive_search": False})
    date = meta.date if meta else None
    return date if date and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) else None


def _wiki(params: dict) -> dict | None:
    r = http.get(WIKI_API, params={"format": "json", "formatversion": 2, "maxlag": 5, **params}, check_robots=False)
    return r.json() if r else None


def resolve_wiki_title(query: str) -> str | None:
    """Top search hit, accepted only if every word of its title appears in the query (avoids wrong articles)."""
    data = _wiki({"action": "query", "list": "search", "srsearch": query, "srlimit": 1})
    hits = (data or {}).get("query", {}).get("search", [])
    if not hits:
        return None
    title = hits[0]["title"]
    words = set(norm(re.sub(r"\(.*?\)", "", title)).split())
    return title if words and words <= set(norm(query).split()) else None


def wikipedia_doc(title: str) -> tuple[SourceDoc | None, list[str]]:
    data = _wiki({"action": "query", "prop": "extracts|revisions|extlinks", "explaintext": 1, "rvprop": "ids",
                  "ellimit": "max", "redirects": 1, "titles": title})
    pages = (data or {}).get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing") or not pages[0].get("extract"):
        resolved = resolve_wiki_title(title)
        return wikipedia_doc(resolved) if resolved and resolved != title else (None, [])
    page = pages[0]
    if "may refer to" in page["extract"][:300]:  # disambiguation page
        return None, []
    revid = (page.get("revisions") or [{}])[0].get("revid")
    url = f"https://en.wikipedia.org/w/index.php?title={quote(page['title'])}&oldid={revid}"
    refs = [e["url"] for e in page.get("extlinks", []) if e.get("url", "").startswith("https://")]
    return SourceDoc(url, "wikipedia.org", "Wikipedia", page["extract"], datetime.now(timezone.utc).isoformat(),
                     revid), refs


def gather(trend: Trend, cfg: dict) -> list[SourceDoc]:
    wiki, refs = wikipedia_doc(trend.title)
    docs = [wiki] if wiki else []
    seen, fetches = set(), 0
    for url in trend.urls + [u for u in refs if allowed(u, cfg)]:
        if len(docs) >= MAX_DOCS or fetches >= MAX_FETCHES:
            break
        if url in seen:
            continue
        seen.add(url)
        fetches += 1
        doc = fetch_doc(url, cfg)
        if doc and all(d.url != doc.url for d in docs):
            docs.append(doc)
    return docs


MAX_CITED_PER_CLAIM = 3


@functools.lru_cache(maxsize=8)
def _parse_html(revid: int) -> str:
    """Rendered HTML of the exact Wikipedia revision we read (citations are only in the HTML)."""
    data = _wiki({"action": "parse", "oldid": revid, "prop": "text"})
    return (data or {}).get("parse", {}).get("text", "") or ""


def cited_urls(html: str, claim: str) -> list[str]:
    """Sources Wikipedia cites for the sentence or table row that contains the claim's figures.
    Text between one citation marker and the next belongs to that marker's references."""
    ys = {Decimal(y) for y in years(claim)}
    targets = {n for n in numbers(claim) if not (n[1] == "" and n[0] in ys)}
    if not targets or not html:
        return []
    try:
        doc = lxml.html.fromstring(html)
    except (lxml.etree.ParserError, ValueError):
        return []
    def https(href):  # old citations often use http://; try the same page over https (fails safely if absent)
        return "https://" + href[7:] if href.startswith("http://") else href

    refs = {li.get("id"): [_raw_snapshot(https(a.get("href") or "")) for a in li.xpath('.//a[contains(@class,"external")]')
                           if (a.get("href") or "").startswith(("https://", "http://"))]
            for li in doc.xpath('//li[starts-with(@id,"cite_note")]')}
    for sup in doc.xpath('//sup[contains(@class,"reference")]'):
        ids = [h.lstrip("#") for h in sup.xpath('.//a/@href')]
        for child in list(sup):
            sup.remove(child)
        sup.text = "" + ",".join(ids) + ""  # private-use chars: valid XML, never in articles
    out = []
    for el in doc.xpath('//p | //tr | //li[not(starts-with(@id,"cite_note"))]'):
        text = " ".join(el.itertext())  # spaces between pieces, or table cells run together ("Dangal₹2,024")
        parts = re.split("([^]*)", text)
        for chunk, ids in zip(parts[0::2], parts[1::2]):
            if not missing_numbers(targets, numbers(chunk)):
                out += [u for i in ids.split(",") for u in refs.get(i, []) if u not in out]
    return out


def cited_docs(wiki: SourceDoc, claim: str, cfg: dict, tried: set) -> list[SourceDoc]:
    """Fetch the pages Wikipedia cites for this claim's figures (allowlisted, robots-permitted, not yet tried)."""
    if not wiki.wiki_revid:
        return []
    urls = [u for u in cited_urls(_parse_html(wiki.wiki_revid), claim) if u not in tried and allowed(u, cfg)]
    docs = []
    for url in urls[:MAX_CITED_PER_CLAIM]:
        tried.add(url)
        doc = fetch_doc(url, cfg)
        if doc:
            docs.append(doc)
    return docs


def trim(text: str, terms: list[str], max_chars: int = 12000) -> str:
    """Keep paragraphs mentioning a topic term or a money/percent figure, to fit free-tier token limits."""
    terms = [t.lower() for t in terms if len(t) >= 3]
    keep, size = [], 0
    for para in (p.strip() for p in re.split(r"\n+", text)):
        if not para:
            continue
        low = para.lower()
        if any(t in low for t in terms) or any(kind for _, kind in numbers(para)):
            if size + len(para) > max_chars:
                break
            keep.append(para)
            size += len(para) + 1
    return "\n".join(keep)
