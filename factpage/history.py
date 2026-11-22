"""Append-only run history (data/history.jsonl): topic 7-day dedupe, forever fact dedupe, fallback-per-day."""
import hashlib
import json
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path

from .textnorm import norm, numbers, proper_nouns


def topic_key(title: str) -> str:
    return norm(title)


def fact_key(claim: str) -> str:
    nums = sorted(f"{v.normalize():f}{k}" for v, k in numbers(claim))
    basis = nums + sorted(proper_nouns(claim)) if nums else [norm(claim)]
    return hashlib.sha1(json.dumps(basis).encode()).hexdigest()


class History:
    def __init__(self, path, count_dry_runs: bool = False):
        self.path = Path(path)
        self.used = {"published", "dry_run"} if count_dry_runs else {"published"}

    def records(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _used(self):
        return [r for r in self.records() if r.get("status") in self.used]

    def append(self, record: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def topic_used_within(self, key: str, days: int, now: datetime) -> bool:
        since = now - timedelta(days=days)
        return any((r.get("topic_key") == key or key in r.get("topic_keys", []))
                   and datetime.fromisoformat(r["at"]) >= since for r in self._used())

    def topic_failed_within(self, key: str, hours: int, now: datetime) -> bool:
        """A slot already researched this topic and no fact passed: let it rest instead of retrying every slot."""
        since = now - timedelta(hours=hours)
        return any(r.get("status") == "skipped" and key in r.get("topic_keys", [])
                   and datetime.fromisoformat(r["at"]) >= since for r in self.records())

    def fact_seen(self, key: str) -> bool:
        return any(key in r.get("fact_keys", []) for r in self._used())

    def fallback_used_on(self, day: date, tz: tzinfo = timezone.utc) -> bool:
        return any(r.get("fallback") and datetime.fromisoformat(r["at"]).astimezone(tz).date() == day
                   for r in self._used())
