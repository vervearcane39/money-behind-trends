import json
from datetime import datetime, timezone

from PIL import Image

from factpage.config import load_config
from factpage.history import History
from factpage.llm import RateLimited
from factpage.pipeline import run_slot
from factpage.research import SourceDoc
from factpage.trends import Trend

NOW = datetime(2026, 11, 18, 7, 37, tzinfo=timezone.utc)
HINDU = SourceDoc("https://www.thehindu.com/a", "thehindu.com", "The Hindu",
                  "Producers said Ramayana: Part 1 was made on a budget of ₹550 crore in 2024, making it "
                  "one of the costliest Indian films ever made.", "t")
BBC = SourceDoc("https://www.bbc.com/b", "bbc.com", "BBC",
                "Ramayana: Part 1, which cost Rs 550 crore to make in 2024, opened this week to packed halls.", "t")
GOOD = {"claim": "Ramayana: Part 1 was made on a budget of ₹550 crore in 2024.",
        "quote": "Producers said Ramayana: Part 1 was made on a budget of ₹550 crore in 2024"}
BAD = {"claim": "Ramayana: Part 1 was made on a budget of ₹560 crore in 2024.", "quote": GOOD["quote"]}


class FakeLLM:
    def __init__(self, fact=GOOD, verdict="SUPPORTED", rate_limited=False):
        self.fact, self.verdict, self.rate_limited = fact, verdict, rate_limited

    def json(self, role, system, user):
        if self.rate_limited:
            raise RateLimited("429")
        if role == "classifier":
            return {"results": [{"title": t, "label": "SAFE", "reason": "film"} for t in [i["title"] for i in json.loads(user)]]}
        if role == "angle":
            return {"results": [{"title": t, "score": 9, "angle": "budget", "photo_query": "cinema hall",
                                 "tags": ["film"], "name": "Ramayana: Part 1"} for t in [i["title"] for i in json.loads(user)]]}
        if role == "extractor":
            return {"facts": [self.fact]} if "thehindu" in user or "The Hindu" in user else {"facts": []}
        return {"verdict": self.verdict, "reason": "ok"}


def fake_render(slides, out_dir, cfg):
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, _ in enumerate(slides, 1):
        p = out_dir / f"slide_{i}.jpg"
        Image.new("RGB", (1080, 1350)).save(p, "JPEG")
        paths.append(p)
    return paths


def run(tmp_path, *, cfg_over=None, dry_run=True, trends=None, llm=None):
    cfg = {**load_config(), "max_fact_age_years": None, **(cfg_over or {})}
    return run_slot(cfg, dry_run=dry_run, root=tmp_path, now=NOW, llm=llm or FakeLLM(),
                    collect=lambda c, n: trends if trends is not None else [Trend("Ramayana: Part 1", "google_trends", "IN", [HINDU.url, BBC.url], 500)],
                    gather=lambda t, c: [HINDU, BBC], find_photo=lambda q, c, o: None, render=fake_render)


def history(tmp_path):
    return History(tmp_path / "data/history.jsonl", count_dry_runs=True).records()


def test_no_trends_is_a_logged_skip_not_a_crash(tmp_path):
    rec = run(tmp_path, trends=[])
    assert rec["status"] == "skipped" and "no trends" in rec["reason"]
    assert history(tmp_path)[-1]["status"] == "skipped"
    assert list((tmp_path / "reports").rglob("*.md"))


def test_all_facts_fail_verification_skips_with_reasons(tmp_path):
    rec = run(tmp_path, llm=FakeLLM(fact=BAD))
    assert rec["status"] == "skipped" and "verification" in rec["reason"]
    assert any("b_claim_in_quote" in json.dumps(c) for c in rec["checks"])


def test_rate_limit_skips_slot(tmp_path):
    rec = run(tmp_path, llm=FakeLLM(rate_limited=True))
    assert rec["status"] == "skipped" and "rate limited" in rec["reason"]


def test_happy_path_dry_run_writes_images_and_report_but_no_pending(tmp_path):
    rec = run(tmp_path)
    assert rec["status"] == "dry_run", rec["reason"]
    assert rec["facts"][0]["claim"] == GOOD["claim"]
    assert (tmp_path / "out" / rec["run_id"] / "slide_1.jpg").exists()
    report = next((tmp_path / "reports").rglob("*.md")).read_text(encoding="utf-8")
    assert GOOD["quote"] in report and HINDU.url in report and BBC.url in report
    assert not (tmp_path / "out" / "pending.json").exists()


def test_same_fact_not_repeated_in_next_run(tmp_path):
    assert run(tmp_path)["status"] == "dry_run"
    rec = run(tmp_path, trends=[Trend("Ramayana box office", "google_trends", "IN", [HINDU.url, BBC.url], 500)])
    assert rec["status"] == "skipped"


def test_live_writes_pending_json(tmp_path):
    rec = run(tmp_path, cfg_over={"publishing_enabled": True, "handle": "@test"}, dry_run=False)
    assert rec["status"] == "ready", rec["reason"]
    pending = json.loads((tmp_path / "out" / "pending.json").read_text(encoding="utf-8"))
    assert pending["images"] == [f"{rec['run_id']}/slide_1.jpg"]
    assert (tmp_path / "out" / "site" / rec["run_id"] / "slide_1.jpg").exists()
    assert GOOD["claim"] in pending["caption"] and len(pending["alt_texts"]) == 1


def test_dry_run_flag_beats_publishing_enabled(tmp_path):
    rec = run(tmp_path, cfg_over={"publishing_enabled": True, "handle": "@test"}, dry_run=True)
    assert rec["status"] == "dry_run"
    assert not (tmp_path / "out" / "pending.json").exists()


class FakePublisher:
    def __init__(self):
        self.args = None

    def publish(self, urls, caption, alt_texts):
        self.args = (urls, caption, alt_texts)
        return "MEDIA9"


def test_publish_pending_records_media_id(tmp_path):
    from factpage.pipeline import publish_pending
    cfg = {**load_config(), "publishing_enabled": True, "handle": "@test"}
    rec = run(tmp_path, cfg_over={"publishing_enabled": True, "handle": "@test"}, dry_run=False)
    pub, checked = FakePublisher(), []
    media = publish_pending(cfg, tmp_path, tmp_path / "out/pending.json", "https://u.github.io/repo/",
                            pub, check=checked.extend, now=NOW)
    assert media == "MEDIA9"
    assert checked == [f"https://u.github.io/repo/{rec['run_id']}/slide_1.jpg"]
    last = History(tmp_path / "data/history.jsonl").records()[-1]
    assert last["status"] == "published" and last["media_id"] == "MEDIA9" and last["fact_keys"]
    assert "MEDIA9" in (tmp_path / rec["report"]).read_text(encoding="utf-8")
    assert History(tmp_path / "data/history.jsonl").fact_seen(last["fact_keys"][0])


def test_publish_pending_refuses_when_kill_switch_off(tmp_path):
    import pytest
    from factpage.pipeline import publish_pending
    run(tmp_path, cfg_over={"publishing_enabled": True, "handle": "@test"}, dry_run=False)
    pub = FakePublisher()
    with pytest.raises(SystemExit):
        publish_pending({**load_config(), "publishing_enabled": False}, tmp_path, tmp_path / "out/pending.json",
                        "https://u.github.io/repo", pub, check=lambda u: None, now=NOW)
    assert pub.args is None


def test_missing_or_rejected_key_fails_loudly_but_still_logs(tmp_path):
    import pytest
    from factpage.llm import MissingKey

    class NoKey(FakeLLM):
        def json(self, role, system, user):
            raise MissingKey("GROQ_API_KEY")
    with pytest.raises(MissingKey):
        run(tmp_path, llm=NoKey())
    assert history(tmp_path)[-1]["status"] == "error"


def test_unexpected_crash_is_logged_as_error_with_cause(tmp_path):
    import pytest
    cfg = {**load_config(), "max_fact_age_years": None}

    def boom(t, c):
        raise RuntimeError("browser died")
    with pytest.raises(RuntimeError):
        run_slot(cfg, dry_run=True, root=tmp_path, now=NOW, llm=FakeLLM(),
                 collect=lambda c, n: [Trend("Ramayana: Part 1", "google_trends", "IN", [], 500)],
                 gather=boom, find_photo=lambda q, c, o: None, render=fake_render)
    last = history(tmp_path)[-1]
    assert last["status"] == "error" and "browser died" in last["reason"]


def test_same_subject_via_different_trend_title_is_on_cooldown(tmp_path):
    assert run(tmp_path)["status"] == "dry_run"  # posts about "Ramayana: Part 1"
    rec = run(tmp_path, trends=[Trend("ramayana part 1 collection", "google_trends", "IN", [HINDU.url], 500)])
    assert rec["topic"] != "Ramayana: Part 1"  # fell back to an evergreen topic instead
    assert any(d["title"] == "ramayana part 1 collection" and not d["kept"] and "7 days" in d["reason"]
               for d in rec["decisions"])


def test_tries_runner_up_when_top_topic_has_too_few_sources(tmp_path):
    cfg = {**load_config(), "max_fact_age_years": None}

    class TwoLLM(FakeLLM):
        def json(self, role, system, user):
            if role == "angle":
                return {"results": [{"title": t, "score": 9 if t == "Empty topic" else 8, "angle": "budget",
                                     "photo_query": "cinema", "tags": [], "name": ""} for t in [i["title"] for i in json.loads(user)]]}
            return super().json(role, system, user)
    rec = run_slot(cfg, dry_run=True, root=tmp_path, now=NOW, llm=TwoLLM(),
                   collect=lambda c, n: [Trend("Empty topic", "google_trends", "IN", [], 900),
                                         Trend("Ramayana: Part 1", "google_trends", "IN", [], 500)],
                   gather=lambda t, c: [] if t.title == "Empty topic" else [HINDU, BBC],
                   find_photo=lambda q, c, o: None, render=fake_render)
    assert rec["status"] == "dry_run" and rec["topic"] == "Ramayana: Part 1"
    assert any(d["title"] == "Empty topic" and "source" in d["reason"] for d in rec["decisions"])


def test_failed_corroboration_follows_wikipedia_citation(tmp_path):
    no_number = SourceDoc("https://www.cnn.com/z", "cnn.com", "CNN", "Ramayana: Part 1 opened to crowds in 2024.", "t")
    wiki = SourceDoc("https://en.wikipedia.org/w/index.php?oldid=7", "wikipedia.org", "Wikipedia",
                     "Ramayana: Part 1 cost ₹550 crore in 2024.", "t", 7)
    calls = []

    def cite(w, claim, cfg, tried):
        calls.append(claim)
        return [BBC]
    rec = run_slot({**load_config(), "max_fact_age_years": None, "require_second_source": True}, dry_run=True, root=tmp_path, now=NOW, llm=FakeLLM(),
                   collect=lambda c, n: [Trend("Ramayana: Part 1", "google_trends", "IN", [], 500)],
                   gather=lambda t, c: [HINDU, no_number, wiki], find_photo=lambda q, c, o: None,
                   render=fake_render, cite=cite)
    assert rec["status"] == "dry_run", rec["reason"]
    assert rec["facts"][0]["corroborator_url"] == BBC.url
    assert calls == [GOOD["claim"]]
    assert any(s["url"] == BBC.url for s in rec["sources"])


def test_citation_not_followed_when_already_corroborated(tmp_path):
    calls = []
    rec = run_slot({**load_config(), "max_fact_age_years": None}, dry_run=True, root=tmp_path, now=NOW, llm=FakeLLM(),
                   collect=lambda c, n: [Trend("Ramayana: Part 1", "google_trends", "IN", [], 500)],
                   gather=lambda t, c: [HINDU, BBC], find_photo=lambda q, c, o: None, render=fake_render,
                   cite=lambda *a: calls.append(a) or [])
    assert rec["status"] == "dry_run" and calls == []


def test_one_news_article_is_enough_to_try_a_topic(tmp_path):
    rec = run(tmp_path, cfg_over={"require_second_source": False})
    assert rec["status"] == "dry_run"
    rec = run_slot({**load_config(), "max_fact_age_years": None}, dry_run=True, root=tmp_path / "b", now=NOW,
                   llm=FakeLLM(), collect=lambda c, n: [Trend("Ramayana: Part 1", "google_trends", "IN", [], 500)],
                   gather=lambda t, c: [HINDU], find_photo=lambda q, c, o: None, render=fake_render)
    assert rec["status"] == "dry_run", rec["reason"]


def test_wikipedia_alone_is_not_enough_to_try_a_topic(tmp_path):
    wiki = SourceDoc("https://en.wikipedia.org/w/index.php?oldid=7", "wikipedia.org", "Wikipedia", "x", "t", 7)
    rec = run_slot({**load_config(), "max_fact_age_years": None}, dry_run=True, root=tmp_path, now=NOW,
                   llm=FakeLLM(), collect=lambda c, n: [Trend("Ramayana: Part 1", "google_trends", "IN", [], 500)],
                   gather=lambda t, c: [wiki], find_photo=lambda q, c, o: None, render=fake_render)
    assert rec["status"] == "skipped" and "news source" in rec["reason"]


def test_newest_news_is_read_first_and_wikipedia_last(tmp_path):
    page = "Ramayana film budget news.\n" * 5
    wiki = SourceDoc("https://en.wikipedia.org/w/index.php?oldid=7", "wikipedia.org", "Wikipedia", page, "t", 7)
    old = SourceDoc("https://www.cnn.com/old", "cnn.com", "CNN", page, "t", None, "2016-04-05")
    new = SourceDoc("https://www.bbc.com/new", "bbc.com", "BBC", page, "t", None, "2026-11-18")
    order = []

    class Order(FakeLLM):
        def json(self, role, system, user):
            if role == "extractor":
                order.append(json.loads(user)["SOURCE"])
                return {"facts": []}
            return super().json(role, system, user)
    run_slot({**load_config(), "max_fact_age_years": None}, dry_run=True, root=tmp_path, now=NOW, llm=Order(),
             collect=lambda c, n: [Trend("Ramayana: Part 1", "google_trends", "IN", [], 500)],
             gather=lambda t, c: [wiki, old, new], find_photo=lambda q, c, o: None, render=fake_render)
    assert order[0] == "BBC" and order[-1] == "Wikipedia", order


def test_silence_watchdog(tmp_path):
    from factpage.pipeline import silent_too_long
    h = History(tmp_path / "data/history.jsonl", count_dry_runs=True)
    for _ in range(12):
        h.append({"status": "skipped", "at": NOW.isoformat()})
    assert silent_too_long(h, 12)
    h.append({"status": "dry_run", "at": NOW.isoformat()})
    assert not silent_too_long(h, 12)


def test_history_line_omits_topic_decisions(tmp_path):
    run(tmp_path)
    assert "decisions" not in history(tmp_path)[-1]


def test_live_refuses_without_handle(tmp_path):
    rec = run(tmp_path, cfg_over={"publishing_enabled": True, "handle": ""}, dry_run=False)
    assert rec["status"] == "skipped" and "handle" in rec["reason"]
    assert not (tmp_path / "out" / "pending.json").exists()
