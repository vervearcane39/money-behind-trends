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


def test_trim_keeps_paragraphs_with_terms_and_numbers():
    text = "Intro about weather.\n\nThe film cost ₹550 crore to make.\n\nUnrelated gossip.\n\nNvidia mentioned."
    out = research.trim(text, ["film"], max_chars=1000)
    assert "₹550 crore" in out and "weather" not in out
