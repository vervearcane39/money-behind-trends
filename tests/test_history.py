from datetime import datetime, timedelta, timezone

from factpage.history import History, fact_key, topic_key

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


def _hist(tmp_path, records, count_dry_runs=True):
    h = History(tmp_path / "history.jsonl", count_dry_runs=count_dry_runs)
    for r in records:
        h.append(r)
    return h


def test_topic_used_within_window(tmp_path):
    h = _hist(tmp_path, [{"status": "published", "topic_key": topic_key("Jensen Huang"),
                          "at": (NOW - timedelta(days=6)).isoformat()}])
    assert h.topic_used_within(topic_key("jensen huang"), 7, NOW)


def test_topic_outside_window(tmp_path):
    h = _hist(tmp_path, [{"status": "published", "topic_key": topic_key("Jensen Huang"),
                          "at": (NOW - timedelta(days=8)).isoformat()}])
    assert not h.topic_used_within(topic_key("Jensen Huang"), 7, NOW)


def test_skipped_runs_do_not_count_as_used(tmp_path):
    h = _hist(tmp_path, [{"status": "skipped", "topic_key": topic_key("Jensen Huang"),
                          "at": NOW.isoformat()}])
    assert not h.topic_used_within(topic_key("Jensen Huang"), 7, NOW)


def test_fact_key_same_fact_reworded():
    assert fact_key("Avatar earned $2.9 billion as of 2023") == fact_key("As of 2023, Avatar earned US$2,900 million")


def test_fact_seen_forever(tmp_path):
    k = fact_key("Avatar earned $2.9 billion as of 2023")
    h = _hist(tmp_path, [{"status": "dry_run", "fact_keys": [k], "at": "2020-01-01T00:00:00+00:00"}])
    assert h.fact_seen(k)
    assert not h.fact_seen(fact_key("Avatar earned $2.8 billion as of 2023"))


def test_live_mode_ignores_dry_run_facts(tmp_path):
    k = fact_key("Avatar earned $2.9 billion as of 2023")
    h = _hist(tmp_path, [{"status": "dry_run", "fact_keys": [k], "at": NOW.isoformat()}], count_dry_runs=False)
    assert not h.fact_seen(k)


def test_fact_key_no_numbers_uses_text():
    assert fact_key("Netflix owns Sony") != fact_key("Netflix licenses films from Sony")


def test_fallback_used_on(tmp_path):
    h = _hist(tmp_path, [{"status": "published", "fallback": True, "at": NOW.isoformat()}])
    assert h.fallback_used_on(NOW.date())
    assert not h.fallback_used_on((NOW + timedelta(days=1)).date())


def test_missing_file_is_empty(tmp_path):
    h = History(tmp_path / "nope.jsonl")
    assert not h.fact_seen("x")
