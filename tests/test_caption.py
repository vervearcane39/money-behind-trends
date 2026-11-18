from pathlib import Path

from factpage.caption import build, copy_ok, topic_label
from factpage.config import load_config
from factpage.filters import Angle
from factpage.images import Photo
from factpage.research import SourceDoc
from factpage.trends import Trend
from factpage.verify import VerifiedFact

CFG = load_config()
A = SourceDoc("https://www.thehindu.com/a", "thehindu.com", "The Hindu", "", "t")
B = SourceDoc("https://www.bbc.com/b", "bbc.com", "BBC", "", "t")
FACT = VerifiedFact("Ramayana: Part 1 was made on a budget of ₹550 crore in 2024.", "₹550 crore", A, "q", B, "e", "ok")
PHOTO = Photo(Path("p.jpg"), "Jane Doe / Pexels", "Pexels License", "https://www.pexels.com/photo/1", "Pexels")
ANGLE = Angle(9, "budget", "cinema hall", ["film", "boxoffice"], "Ramayana: Part 1")


def test_caption_contains_claim_verbatim_sources_credit_and_hashtags():
    cap = build(Trend("ramayana part 1", "google_trends", "IN", [], 1), [FACT], PHOTO, ANGLE, CFG)
    assert FACT.claim in cap
    assert "The Hindu" in cap and "BBC" in cap
    assert "Photo: Jane Doe / Pexels" in cap and "pexels.com" in cap
    assert cap.splitlines()[0] == "Ramayana: Part 1 is trending in India."
    tags = [w for w in cap.split() if w.startswith("#")]
    assert 3 <= len(tags) <= CFG["copy"]["max_hashtags"]
    assert copy_ok(cap, CFG)[0]


def test_caption_without_photo_has_no_credit_line():
    cap = build(Trend("Nvidia", "wikipedia", "", [], 1), [FACT], None, Angle(9, "a", "b", [], "Nvidia"), CFG)
    assert "Photo:" not in cap
    assert cap.splitlines()[0] == "Nvidia is among the most-read articles on English Wikipedia."


def test_feed_headline_never_used_as_label():
    headline = "Nvidia says it won't reinstate Huang as firm reports bumper results"
    t = Trend(headline, "feed", "", [], 0)
    assert topic_label(t, Angle(8, "a", "b", [], "Nvidia")) == "Nvidia"
    assert topic_label(t, Angle(8, "a", "b", [], "")) is None


def test_copy_rules():
    assert not copy_ok("Did you know this?", CFG)[0]
    assert not copy_ok("Wow!! big", CFG)[0]
    assert not copy_ok("🤯 numbers", CFG)[0]
    assert not copy_ok("📈 up 📉 down", CFG)[0]
    assert copy_ok("A plain sentence.", CFG)[0]
