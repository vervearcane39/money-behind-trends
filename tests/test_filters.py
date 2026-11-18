import json
from datetime import datetime, timedelta, timezone

from factpage.config import load_config
from factpage.filters import Angle, blocklist_hit, classify_safety, pick, score_angles, shortlist
from factpage.history import History, topic_key
from factpage.trends import Trend

CFG = load_config()
NOW = datetime(2026, 11, 18, 6, 0, tzinfo=timezone.utc)


class FakeLLM:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def json(self, role, system, user):
        self.calls.append((role, user))
        return self.reply(user) if callable(self.reply) else self.reply


def T(title, signal=100):
    return Trend(title, "google_trends", "IN", ["https://www.thehindu.com/x"], signal)


def test_blocklist_whole_word_case_insensitive():
    words = CFG["blocklist"]
    assert blocklist_hit("Actor DIES in crash", words) in {"dies", "crash"}
    assert blocklist_hit("Prime Minister visits", words) in {"minister", "prime minister"}
    assert blocklist_hit("Fireworks sales", words) is None  # 'fire' must not match inside 'Fireworks'
    assert blocklist_hit("Ramayana box office", words) is None


def test_safety_unsure_is_dropped():
    llm = FakeLLM({"results": [{"title": "Ramayana", "label": "UNSURE", "reason": "religious epic?"}]})
    assert classify_safety(llm, [T("Ramayana")])["Ramayana"][0] == "UNSURE"


def test_safety_malformed_reply_marks_everything_unsure():
    llm = FakeLLM(None)
    out = classify_safety(llm, [T("Nvidia"), T("IPL auction")])
    assert {v[0] for v in out.values()} == {"UNSURE"}


def test_safety_missing_title_is_unsure():
    llm = FakeLLM({"results": [{"title": "Nvidia", "label": "SAFE", "reason": "company"}]})
    out = classify_safety(llm, [T("Nvidia"), T("IPL auction")])
    assert out["Nvidia"][0] == "SAFE" and out["IPL auction"][0] == "UNSURE"


def test_score_angles_parses_and_sanitises():
    llm = FakeLLM({"results": [{"title": "Nvidia", "score": 9, "angle": "market value", "name": "Nvidia",
                                "photo_query": "computer chips", "tags": ["#Chips!", "AI", "x y z", "3rd"]}]})
    a = score_angles(llm, [T("Nvidia")])["Nvidia"]
    assert a == Angle(9, "market value", "computer chips", ["chips", "ai"], "Nvidia")


def test_angle_name_rejected_if_claim_like():
    headline = "Nvidia says it won't reinstate Huang as firm reports bumper results"
    llm = FakeLLM({"results": [{"title": headline, "score": 8, "angle": "a", "photo_query": "chips", "tags": [],
                                "name": "Nvidia profit up 20 percent in 2026"}]})
    assert score_angles(llm, [T(headline)])[headline].name == ""


def test_score_angles_malformed_is_empty():
    assert score_angles(FakeLLM(None), [T("Nvidia")]) == {}


def _safe(*titles):
    return {t: ("SAFE", "ok") for t in titles}


def test_pick_highest_score_not_recently_used(tmp_path):
    h = History(tmp_path / "h.jsonl")
    h.append({"status": "published", "topic_key": topic_key("Nvidia"), "at": (NOW - timedelta(days=3)).isoformat()})
    trends = [T("Nvidia"), T("IPL auction")]
    angles = {"Nvidia": Angle(9, "a", "chips", []), "IPL auction": Angle(7, "b", "stadium", [])}
    trend, angle, decisions = pick(trends, _safe("Nvidia", "IPL auction"), angles, h, CFG, NOW)
    assert trend.title == "IPL auction"
    assert any(d.title == "Nvidia" and not d.kept and "7 days" in d.reason for d in decisions)


def test_pick_drops_blocklisted_even_if_llm_says_safe(tmp_path):
    trends = [T("Stadium stampede")]
    trend, _, decisions = pick(trends, _safe("Stadium stampede"), {"Stadium stampede": Angle(9, "a", "b", [])},
                               History(tmp_path / "h.jsonl"), CFG, NOW)
    assert trend is None or trend.source == "evergreen"
    assert decisions[0].reason.startswith("blocklist")


def test_pick_falls_back_to_evergreen_once_per_day(tmp_path):
    h = History(tmp_path / "h.jsonl")
    trend, angle, _ = pick([T("Nvidia")], _safe("Nvidia"), {"Nvidia": Angle(3, "weak", "chips", [])}, h, CFG, NOW)
    assert trend.source == "evergreen" and angle is None
    h.append({"status": "published", "fallback": True, "topic_key": topic_key(trend.title), "at": NOW.isoformat()})
    trend2, _, _ = pick([T("Nvidia")], _safe("Nvidia"), {"Nvidia": Angle(3, "weak", "chips", [])}, h, CFG, NOW)
    assert trend2 is None


def test_shortlist_drops_blocklisted_caps_and_prefers_trends():
    trends = [Trend(f"feed {i}", "feed", "", [], 0) for i in range(70)]
    trends += [Trend("Stadium stampede", "google_trends", "IN", [], 9999), Trend("Nvidia", "wikipedia", "", [], 5)]
    out = shortlist(trends, CFG)
    assert len(out) == CFG["max_candidates"]
    assert out[0].title == "Nvidia"
    assert all(t.title != "Stadium stampede" for t in out)


def test_shortlist_drops_non_latin_titles():
    trends = [Trend("ബോക്സ് ഓഫീസ്", "google_trends", "IN", [], 900), Trend("भारत बनाम", "google_trends", "IN", [], 800),
              Trend("Nvidia", "wikipedia", "", [], 5), Trend("Moussa Diabaté", "google_trends", "US", [], 4)]
    assert [t.title for t in shortlist(trends, CFG)] == ["Nvidia", "Moussa Diabaté"]


def test_gambling_topics_blocked():
    assert blocklist_hit("mega millions numbers", CFG["blocklist"])
    assert blocklist_hit("Powerball jackpot", CFG["blocklist"])


def test_safety_is_asked_in_batches_so_none_go_unanswered():
    llm = FakeLLM(lambda user: {"results": [{"title": t, "label": "SAFE", "reason": "ok"} for t in json.loads(user)]})
    trends = [T(f"Company {i}") for i in range(45)]
    out = classify_safety(llm, trends)
    assert len(llm.calls) == 3 and all(len(json.loads(u)) <= 20 for _, u in llm.calls)
    assert {v[0] for v in out.values()} == {"SAFE"} and len(out) == 45


def test_angles_are_asked_in_batches():
    llm = FakeLLM(lambda user: {"results": [{"title": t, "score": 7, "angle": "a", "photo_query": "q", "tags": [],
                                             "name": ""} for t in json.loads(user)]})
    out = score_angles(llm, [T(f"Company {i}") for i in range(25)])
    assert len(llm.calls) == 2 and len(out) == 25


def test_topic_that_failed_verification_rests_for_24_hours(tmp_path):
    h = History(tmp_path / "h.jsonl")
    h.append({"status": "skipped", "reason": "no fact passed verification", "topic_keys": [topic_key("Nvidia")],
              "at": (NOW - timedelta(hours=3)).isoformat()})
    trends = [T("Nvidia"), T("IPL auction")]
    angles = {"Nvidia": Angle(9, "a", "chips", []), "IPL auction": Angle(7, "b", "stadium", [])}
    trend, _, decisions = pick(trends, _safe("Nvidia", "IPL auction"), angles, h, CFG, NOW)
    assert trend.title == "IPL auction"
    assert any(d.title == "Nvidia" and "24" in d.reason for d in decisions)
    trend, _, _ = pick(trends, _safe("Nvidia", "IPL auction"), angles, h, CFG, NOW + timedelta(hours=25))
    assert trend.title == "Nvidia"


def test_pick_skips_excluded_titles(tmp_path):
    trends = [T("Nvidia"), T("IPL auction")]
    angles = {"Nvidia": Angle(9, "a", "chips", []), "IPL auction": Angle(7, "b", "stadium", [])}
    trend, _, decisions = pick(trends, _safe("Nvidia", "IPL auction"), angles, History(tmp_path / "h.jsonl"), CFG, NOW,
                               exclude={"Nvidia"})
    assert trend.title == "IPL auction"
    assert any(d.title == "Nvidia" and not d.kept for d in decisions)


def test_pick_non_latin_title_without_angle_is_dropped(tmp_path):
    title = "भारत बनाम"
    trend, _, decisions = pick([T(title)], _safe(title), {}, History(tmp_path / "h.jsonl"), CFG, NOW)
    assert (trend is None or trend.source == "evergreen")
    assert any(d.title == title and not d.kept for d in decisions)
