from types import SimpleNamespace

import factpage.research as research
from factpage.config import load_config

CFG = load_config()
LONG = "Revenue rose sharply in the quarter. " * 40


def test_allowed_subdomain_of_allowlisted():
    assert research.allowed("https://www.reuters.com/business/x", CFG)
    assert research.allowed("https://sportstar.thehindu.com/x", CFG)


def test_unknown_domain_rejected():
    assert not research.allowed("https://randomfacts.net/x", CFG)


def test_denylist_beats_allowlist(monkeypatch):
    cfg = {**CFG, "sources": {**CFG["sources"], "allow": {**CFG["sources"]["allow"], "forbes.com": "Forbes"}}}
    assert not research.allowed("https://www.forbes.com/x", cfg)


def test_government_suffix_allowed():
    assert research.allowed("https://www.mca.gov.in/x", CFG)
    assert research.source_name("https://www.mca.gov.in/x", CFG) == "mca.gov.in"


def test_source_name_uses_most_specific_entry():
    assert research.source_name("https://economictimes.indiatimes.com/a", CFG) == "The Economic Times"


def test_paywall_jsonld_flag():
    html = '<script type="application/ld+json">{"isAccessibleForFree": false}</script>'
    assert research.is_paywalled(html, LONG, "https://www.thehindu.com/x", CFG)


def test_paywall_short_text():
    assert research.is_paywalled("<p>Subscribe</p>", "Subscribe to read.", "https://www.thehindu.com/x", CFG)


def test_paywall_domain_path_prefix():
    assert research.is_paywalled("", LONG, "https://economictimes.indiatimes.com/prime/x", CFG)
    assert not research.is_paywalled("", LONG, "https://economictimes.indiatimes.com/news/x", CFG)


def test_fetch_doc_none_when_fetch_fails(monkeypatch):
    monkeypatch.setattr(research.http, "get", lambda url, **kw: None)
    assert research.fetch_doc("https://www.thehindu.com/x", CFG) is None


def test_fetch_doc_none_when_redirected_off_allowlist(monkeypatch):
    monkeypatch.setattr(research.http, "get", lambda url, **kw: SimpleNamespace(url="https://spamfarm.biz/x", text="<p>hi</p>"))
    assert research.fetch_doc("https://www.thehindu.com/x", CFG) is None


def test_fetch_doc_none_for_disallowed_domain_without_fetching(monkeypatch):
    called = []
    monkeypatch.setattr(research.http, "get", lambda url, **kw: called.append(url))
    assert research.fetch_doc("https://randomfacts.net/x", CFG) is None
    assert called == []


WIKI_HTML = """<div class="mw-parser-output">
<p>Intro sentence about films. The film earned ₹550 crore in 2024.<sup class="reference"><a href="#cite_note-x-1">[1]</a></sup>
Another fact says 99% in 2020.<sup class="reference"><a href="#cite_note-y-2">[2]</a></sup></p>
<table><tr><td>Dangal</td><td>₹2,024 crore<sup class="reference"><a href="#cite_note-z-3">[3]</a></sup></td></tr></table>
<ol class="references">
<li id="cite_note-x-1"><span><a rel="nofollow" class="external text" href="https://www.bbc.com/a">BBC story</a></span></li>
<li id="cite_note-y-2"><a rel="nofollow" class="external text" href="https://www.cnn.com/b">CNN</a></li>
<li id="cite_note-z-3"><a rel="nofollow" class="external text" href="https://www.thehindu.com/c">Hindu</a></li>
</ol></div>"""


def test_cited_urls_follow_the_citation_of_the_matching_sentence_only():
    assert research.cited_urls(WIKI_HTML, "The film earned ₹550 crore in 2024.") == ["https://www.bbc.com/a"]


def test_cited_urls_work_in_table_rows():
    assert research.cited_urls(WIKI_HTML, "Dangal grossed ₹2,024 crore worldwide by 2017.") == ["https://www.thehindu.com/c"]


def test_cited_http_links_are_upgraded_to_https():
    html = WIKI_HTML.replace("https://www.bbc.com/a", "http://www.bbc.com/a")
    assert research.cited_urls(html, "The film earned ₹550 crore in 2024.") == ["https://www.bbc.com/a"]


ARCH = "https://web.archive.org/web/20160114100635/http://www.thehindu.com/business/x.ece"


def test_archive_links_are_judged_by_the_original_page():
    assert research.original_url(ARCH) == "https://www.thehindu.com/business/x.ece"
    assert research.allowed(ARCH, CFG)
    assert not research.allowed("https://web.archive.org/web/2016/http://randomfacts.net/x", CFG)
    assert not research.allowed("https://web.archive.org/web/2016/https://www.wsj.com/x", CFG) or \
        research.is_paywalled("", LONG, "https://web.archive.org/web/2016/https://www.wsj.com/x", CFG)


def test_cited_archive_links_use_the_raw_snapshot():
    html = WIKI_HTML.replace("https://www.bbc.com/a", "https://web.archive.org/web/20160114100635/http://www.bbc.com/a")
    assert research.cited_urls(html, "The film earned ₹550 crore in 2024.") == \
        ["https://web.archive.org/web/20160114100635id_/http://www.bbc.com/a"]


def test_archived_doc_counts_as_the_original_outlet(monkeypatch):
    page = "<html><body><article>" + "".join(
        f"<p>Report part {i}: the film earned ₹550 crore in 2024 at the box office in city number {i}.</p>"
        for i in range(30)) + "</article></body></html>"
    url = "https://web.archive.org/web/20160114100635id_/http://www.thehindu.com/business/x.ece"
    monkeypatch.setattr(research.http, "get", lambda u, **kw: SimpleNamespace(url=u, text=page))
    monkeypatch.setattr(research.http, "robots_allowed", lambda u: True)
    doc = research.fetch_doc(url, CFG)
    assert doc.domain == "thehindu.com" and doc.name == "The Hindu (archived)" and doc.url == url
    # an archive copy never gets around the original publisher's robots.txt
    monkeypatch.setattr(research.http, "robots_allowed", lambda u: "thehindu.com" not in u)
    assert research.fetch_doc(url, CFG) is None


def test_pages_without_declared_charset_are_read_as_utf8(monkeypatch):
    """BBC-style pages send no charset header; requests then guesses Latin-1 and '£60m' turns into 'Â£60m'."""
    page = "<html><body><article>" + "".join(
        f"<p>Part {i}: Surrey negotiated a £60m price for a 49% stake, sources in city {i} said.</p>"
        for i in range(30)) + "</article></body></html>"
    raw = page.encode("utf-8")
    resp = SimpleNamespace(url="https://www.bbc.com/sport/x", headers={"content-type": "text/html"},
                           content=raw, text=raw.decode("latin-1"))
    monkeypatch.setattr(research.http, "get", lambda u, **kw: resp)
    doc = research.fetch_doc("https://www.bbc.com/sport/x", CFG)
    assert "£60m" in doc.text and "Â" not in doc.text


def test_cited_urls_need_a_non_year_number():
    assert research.cited_urls(WIKI_HTML, "Dangal was released in 2016.") == []
    assert research.cited_urls("<p>broken", "It cost ₹550 crore in 2024.") == []


def test_cited_docs_fetches_only_allowlisted_untried_urls(monkeypatch):
    from factpage.research import SourceDoc
    monkeypatch.setattr(research, "_parse_html", lambda revid: WIKI_HTML)
    fetched = []
    monkeypatch.setattr(research, "fetch_doc", lambda u, c: fetched.append(u) or SourceDoc(u, "bbc.com", "BBC", "t", "t"))
    wiki = SourceDoc("https://en.wikipedia.org/w/index.php?oldid=7", "wikipedia.org", "Wikipedia", "", "t", 7)
    tried = set()
    docs = research.cited_docs(wiki, "The film earned ₹550 crore in 2024.", CFG, tried)
    assert [d.url for d in docs] == ["https://www.bbc.com/a"] and tried == {"https://www.bbc.com/a"}
    assert research.cited_docs(wiki, "The film earned ₹550 crore in 2024.", CFG, tried) == []  # never refetch
    assert fetched == ["https://www.bbc.com/a"]


def test_trim_keeps_paragraphs_with_terms_and_numbers():
    text = "Intro about weather.\n\nThe film cost ₹550 crore to make.\n\nUnrelated gossip.\n\nNvidia mentioned."
    out = research.trim(text, ["film"], max_chars=1000)
    assert "₹550 crore" in out and "weather" not in out
