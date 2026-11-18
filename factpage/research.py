"""Research: fetch allowlisted, non-paywalled, robots-permitted pages + the Wikipedia article and its references."""
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

import trafilatura

from . import http
from .textnorm import norm, numbers, registrable_domain
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
    host, src = _host(url), cfg["sources"]
    if any(_under(host, d) for d in src["deny"]):
        return False
    return bool(_allow_key(host, src["allow"])) or any(host.endswith(s) for s in src["allow_suffixes"])


def source_name(url: str, cfg: dict) -> str:
    key = _allow_key(_host(url), cfg["sources"]["allow"])
    return cfg["sources"]["allow"][key] if key else registrable_domain(url)


def is_paywalled(html: str, text: str, url: str, cfg: dict) -> bool:
    host_path = _host(url) + urlsplit(url).path
    for p in cfg["sources"]["paywall"]:
        if ("/" in p and (host_path == p or host_path.startswith(p.rstrip("/") + "/"))) or ("/" not in p and _under(_host(url), p)):
            return True
    if re.search(r'"isAccessibleForFree"\s*:\s*"?false"?', html, re.I):
        return True
    return len(text.split()) < 150


def fetch_doc(url: str, cfg: dict) -> SourceDoc | None:
    if not allowed(url, cfg):
        log.info("skip (not allowlisted): %s", url)
        return None
    r = http.get(url)
    if r is None:
        return None
    if not allowed(r.url, cfg):
        log.info("skip (redirected off allowlist): %s -> %s", url, r.url)
        return None
    text = trafilatura.extract(r.text, include_comments=False, include_tables=True, favor_precision=True) or ""
    if is_paywalled(r.text, text, r.url, cfg):
        log.info("skip (paywalled/too short): %s", r.url)
        return None
    return SourceDoc(r.url, registrable_domain(r.url), source_name(r.url, cfg), text,
                     datetime.now(timezone.utc).isoformat())


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
