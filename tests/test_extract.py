from factpage.config import load_config
from factpage.extract import extract_candidates
from factpage.research import SourceDoc

CFG = load_config()
DOC = SourceDoc("https://www.thehindu.com/a", "thehindu.com", "The Hindu",
                "The film was made on a budget of ₹550 crore in 2024.", "t")


class Fake:
    def __init__(self, reply):
        self.reply, self.seen = reply, None

    def json(self, role, system, user):
        assert role == "extractor"
        self.seen = user
        return self.reply


def test_malformed_reply_gives_no_candidates():
    assert extract_candidates(Fake(None), DOC, "Ramayana", "budget", CFG) == []
    assert extract_candidates(Fake({"facts": "nope"}), DOC, "Ramayana", "budget", CFG) == []


def test_source_url_is_set_by_code_not_model():
    reply = {"facts": [{"claim": "c1", "quote": "q1", "source_url": "https://evil.example/x"},
                       {"claim": 5, "quote": "bad type"}]}
    out = extract_candidates(Fake(reply), DOC, "Ramayana", "budget", CFG)
    assert [(c.claim, c.source_url, c.quote) for c in out] == [("c1", DOC.url, "q1")]


def test_source_text_reaches_the_prompt():
    f = Fake({"facts": []})
    extract_candidates(f, DOC, "Ramayana", "budget", CFG)
    assert "₹550 crore" in f.seen
