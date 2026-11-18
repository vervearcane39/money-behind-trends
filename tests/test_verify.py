"""The verification gate. The first three tests are the ones the spec says MUST reject."""
from factpage.config import load_config
from factpage.research import SourceDoc
from factpage.verify import Candidate, verify

CFG = load_config()

HINDU = SourceDoc("https://www.thehindu.com/a", "thehindu.com", "The Hindu",
                  "Producers said Ramayana: Part 1 was made on a budget of ₹550 crore in 2024, making it "
                  "one of the costliest Indian films ever made.", "t")
BBC = SourceDoc("https://www.bbc.com/b", "bbc.com", "BBC",
                "Ramayana: Part 1, which cost Rs 550 crore to make in 2024, opened this week to packed halls.", "t")
NO_NUMBER = SourceDoc("https://www.bbc.com/c", "bbc.com", "BBC",
                      "Ramayana: Part 1 opened in theatres in 2024 to strong crowds across India.", "t")
WIKI = SourceDoc("https://en.wikipedia.org/w/index.php?title=R&oldid=1", "wikipedia.org", "Wikipedia",
                 "Ramayana: Part 1 is an Indian epic film. Its production budget was ₹550 crore in 2024.", "t", 1)
WIKI_MOBILE = SourceDoc("https://en.m.wikipedia.org/wiki/R", "wikipedia.org", "Wikipedia",
                        "Ramayana: Part 1 is an Indian epic film. Its production budget was ₹550 crore in 2024.", "t")

QUOTE = "Producers said Ramayana: Part 1 was made on a budget of ₹550 crore in 2024"
CLAIM = "Ramayana: Part 1 was made on a budget of ₹550 crore in 2024."


class Verdict:
    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def json(self, role, system, user):
        self.calls += 1
        assert role == "verifier"
        return self.reply


OK = Verdict({"verdict": "SUPPORTED", "reason": "both excerpts state it"})


def failed_at(log):
    return next((k for k, (ok, _) in log.results.items() if not ok), None)


# ── the three required rejections ───────────────────────────────────────────

def test_rejects_number_off_by_one_digit():
    fact, log = verify(Candidate(CLAIM.replace("550", "560"), HINDU.url, QUOTE), [HINDU, BBC], OK, CFG)
    assert fact is None and failed_at(log) == "b_claim_in_quote"
    fact, log = verify(Candidate(CLAIM.replace("550", "560"), HINDU.url, QUOTE.replace("550", "560")),
                       [HINDU, BBC], OK, CFG)
    assert fact is None and failed_at(log) == "a_quote_verbatim"


def test_rejects_quote_not_in_page():
    fact, log = verify(Candidate(CLAIM, HINDU.url, "Ramayana: Part 1 was the most expensive film ever made in India"),
                       [HINDU, BBC], OK, CFG)
    assert fact is None and failed_at(log) == "a_quote_verbatim"


def test_rejects_number_only_on_wikipedia():
    wiki_quote = "Its production budget was ₹550 crore in 2024."
    claim = "Ramayana: Part 1 had a production budget of ₹550 crore in 2024."
    wq = "Ramayana: Part 1 is an Indian epic film. Its production budget was ₹550 crore in 2024."
    for docs in ([WIKI, WIKI_MOBILE], [WIKI, NO_NUMBER]):
        fact, log = verify(Candidate(claim, WIKI.url, wq), docs, OK, CFG)
        assert fact is None and failed_at(log) == "c_corroborated", docs
    assert len(wiki_quote.split()) >= 8


# ── owner-approved rule (2026-11-18): a corroborator's publication date may confirm the claim's year ──

OVAL_QUOTE = "In 2025, the owners of Mumbai Indians bought a 49% stake in the Oval Invincibles for £60 million"
OVAL_PRIMARY = SourceDoc("https://www.thehindu.com/oval", "thehindu.com", "The Hindu",
                         OVAL_QUOTE + ", officials confirmed on Tuesday.", "t")
OVAL_CLAIM = "In 2025, the owners of Mumbai Indians bought a 49% stake in the Oval Invincibles for £60 million."


def _bbc(published):
    return SourceDoc("https://www.bbc.com/oval", "bbc.com", "BBC",
                     "Last week, Surrey negotiated a £60m price with the owners of Mumbai Indians for a 49% stake "
                     "in Oval Invincibles.", "t", None, published)


def test_publication_date_confirms_year_missing_from_corroborator_text():
    fact, log = verify(Candidate(OVAL_CLAIM, OVAL_PRIMARY.url, OVAL_QUOTE), [OVAL_PRIMARY, _bbc("2025-03-04")], OK, CFG)
    assert fact is not None, log.results
    assert "publication date" in log.results["c_corroborated"][1]


def test_publication_date_from_another_year_does_not_confirm():
    fact, log = verify(Candidate(OVAL_CLAIM, OVAL_PRIMARY.url, OVAL_QUOTE), [OVAL_PRIMARY, _bbc("2024-11-01")], OK, CFG)
    assert fact is None and failed_at(log) == "c_corroborated"


def test_no_publication_date_and_no_year_in_text_does_not_confirm():
    fact, log = verify(Candidate(OVAL_CLAIM, OVAL_PRIMARY.url, OVAL_QUOTE), [OVAL_PRIMARY, _bbc(None)], OK, CFG)
    assert fact is None and failed_at(log) == "c_corroborated"


def test_publication_date_never_replaces_the_figures():
    bbc = SourceDoc("https://www.bbc.com/oval", "bbc.com", "BBC",
                    "Surrey sold a stake in Oval Invincibles to the owners of Mumbai Indians.", "t", None, "2025-03-04")
    fact, log = verify(Candidate(OVAL_CLAIM, OVAL_PRIMARY.url, OVAL_QUOTE), [OVAL_PRIMARY, bbc], OK, CFG)
    assert fact is None and failed_at(log) == "c_corroborated"


def test_verifier_is_told_the_corroborator_publication_date():
    seen = {}

    class Spy(Verdict):
        def json(self, role, system, user):
            seen["user"] = user
            return {"verdict": "SUPPORTED", "reason": "ok"}
    verify(Candidate(OVAL_CLAIM, OVAL_PRIMARY.url, OVAL_QUOTE), [OVAL_PRIMARY, _bbc("2025-03-04")], Spy(None), CFG)
    assert "2025-03-04" in seen["user"]


# ── the big number shown on the image ───────────────────────────────────────

def test_key_number_prefers_money_with_unit():
    from factpage.verify import key_number
    assert key_number("Ramayana: Part 1 cost ₹550 crore in 2024.") == "₹550 crore"
    assert key_number("Revenue rose 12% to $3 billion in 2024.") == "$3 billion"
    assert key_number("The stadium seats 50,000 people since 2019.") == "50,000"
    assert key_number("Founded in 1937.") is None


def test_key_number_none_for_ranges():
    from factpage.verify import key_number
    assert key_number("It would cost about £75 to £90 million to develop in 1962.") is None
    assert key_number("Costs rose to £1.5–2.1 billion in 1976.") is None


# ── the rest of the gate ────────────────────────────────────────────────────

def test_accepts_fully_supported_claim():
    fact, log = verify(Candidate(CLAIM, HINDU.url, QUOTE), [HINDU, BBC], OK, CFG)
    assert fact is not None, log.results
    assert fact.key_number == "₹550 crore"
    assert fact.corroborator is BBC and fact.primary is HINDU
    assert all(ok for ok, _ in log.results.values())


def test_wikipedia_primary_with_news_corroborator_passes():
    wq = "Ramayana: Part 1 is an Indian epic film. Its production budget was ₹550 crore in 2024."
    fact, _ = verify(Candidate("Ramayana: Part 1 had a production budget of ₹550 crore in 2024.", WIKI.url, wq),
                     [WIKI, BBC], OK, CFG)
    assert fact is not None and fact.corroborator is BBC


def test_quote_must_come_from_the_named_source():
    fact, log = verify(Candidate(CLAIM, BBC.url, QUOTE), [HINDU, BBC], OK, CFG)
    assert fact is None and failed_at(log) == "a_quote_verbatim"


def test_short_quote_rejected():
    fact, log = verify(Candidate(CLAIM, HINDU.url, "budget of ₹550 crore"), [HINDU, BBC], OK, CFG)
    assert fact is None and failed_at(log) == "a_quote_verbatim"


def test_verifier_unclear_rejected():
    fact, log = verify(Candidate(CLAIM, HINDU.url, QUOTE), [HINDU, BBC], Verdict({"verdict": "UNCLEAR"}), CFG)
    assert fact is None and failed_at(log) == "d_verifier"


def test_verifier_malformed_rejected():
    fact, log = verify(Candidate(CLAIM, HINDU.url, QUOTE), [HINDU, BBC], Verdict(None), CFG)
    assert fact is None and failed_at(log) == "d_verifier"


def test_verifier_not_called_when_code_checks_fail():
    v = Verdict({"verdict": "SUPPORTED"})
    verify(Candidate(CLAIM.replace("550", "560"), HINDU.url, QUOTE), [HINDU, BBC], v, CFG)
    assert v.calls == 0


def test_currently_rejected():
    claim = "Ramayana: Part 1 currently has a budget of ₹550 crore in 2024."
    fact, log = verify(Candidate(claim, HINDU.url, QUOTE), [HINDU, BBC], OK, CFG)
    assert fact is None and failed_at(log) == "e_dated"


def test_number_without_year_rejected():
    fact, log = verify(Candidate("Ramayana: Part 1 was made on a budget of ₹550 crore.", HINDU.url, QUOTE),
                       [HINDU, BBC], OK, CFG)
    assert fact is None and failed_at(log) == "e_dated"


def test_superlative_not_in_quote_rejected():
    claim = "Ramayana: Part 1 had the largest budget of ₹550 crore in 2024."
    fact, log = verify(Candidate(claim, HINDU.url, QUOTE), [HINDU, BBC], OK, CFG)
    assert fact is None and failed_at(log) == "b_claim_in_quote"


def test_proper_noun_not_in_quote_rejected():
    claim = "Netflix funded Ramayana: Part 1 with ₹550 crore in 2024."
    fact, log = verify(Candidate(claim, HINDU.url, QUOTE), [HINDU, BBC], OK, CFG)
    assert fact is None and failed_at(log) == "b_claim_in_quote"


def test_currency_added_by_claim_rejected():
    quote = "Ramayana: Part 1 opened in theatres in 2024 to strong crowds across India"
    fact, log = verify(Candidate("Ramayana: Part 1 opened to $2024 in India.", NO_NUMBER.url, quote),
                       [NO_NUMBER, HINDU], OK, CFG)
    assert fact is None and failed_at(log) == "b_claim_in_quote"


def test_too_long_claim_rejected():
    claim = ("Ramayana: Part 1 was made on a budget of ₹550 crore in 2024 and that is a very large amount of "
             "money for a film made in this way here")
    fact, log = verify(Candidate(claim, HINDU.url, QUOTE), [HINDU, BBC], OK, CFG)
    assert fact is None and failed_at(log) == "style"


def test_banned_phrase_rejected():
    claim = "in a fun fact, Ramayana: Part 1 was made on a budget of ₹550 crore in 2024."
    fact, log = verify(Candidate(claim, HINDU.url, QUOTE), [HINDU, BBC], OK, CFG)
    assert fact is None and failed_at(log) == "style"


def test_prediction_or_advice_rejected():
    claim = "Ramayana: Part 1 will earn back its ₹550 crore budget made in 2024."
    fact, log = verify(Candidate(claim, HINDU.url, QUOTE), [HINDU, BBC], OK, CFG)
    assert fact is None and failed_at(log) == "style"
