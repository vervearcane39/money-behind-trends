"""One OpenAI-compatible chat client. Swap provider by changing base_url/model/key_env in config.yaml."""
import json
import logging
import os
import re
import time

import requests

log = logging.getLogger("factpage")


class RateLimited(Exception):
    """Provider kept returning 429 after all retries → the slot is skipped, checks are never loosened."""


class MissingKey(Exception):
    pass


class LLM:
    def __init__(self, cfg: dict):
        self.roles = cfg["llm"]
        self.retries = cfg["llm"].get("max_retries", 3)

    def json(self, role: str, system: str, user: str) -> dict | None:
        """Return the model's JSON object, or None if the reply isn't a JSON object."""
        r = self.roles[role]
        key = os.environ.get(r["key_env"])
        if not key:
            raise MissingKey(r["key_env"])
        body = {"model": r["model"], "temperature": 0, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                **r.get("extra", {})}
        for attempt in range(self.retries + 1):
            try:
                resp = requests.post(f"{r['base_url']}/chat/completions", json=body, timeout=90,
                                     headers={"Authorization": f"Bearer {key}"})
            except requests.RequestException as e:
                log.info("LLM %s network error: %s", role, e)
                return None
            if resp.status_code == 429:
                if attempt == self.retries:
                    raise RateLimited(f"{role}: {resp.text[:200]}")
                wait = float(resp.headers.get("retry-after") or 5 * 2 ** attempt)
                log.info("LLM %s rate limited, waiting %.0fs", role, wait)
                time.sleep(min(wait, 120))
                continue
            if not resp.ok:
                log.info("LLM %s HTTP %s: %s", role, resp.status_code, resp.text[:200])
                return None
            return parse_json_object(resp.json()["choices"][0]["message"].get("content") or "")
        return None


def parse_json_object(text: str) -> dict | None:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    text = re.sub(r"^```(?:json)?|```$", "", text).strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None
