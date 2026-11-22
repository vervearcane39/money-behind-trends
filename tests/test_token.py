import base64
import json
from datetime import datetime, timedelta, timezone

from nacl.public import PrivateKey, SealedBox

from factpage.token import refresh_due, refresh_if_due, store_secret

NOW = datetime(2026, 11, 18, tzinfo=timezone.utc)


def test_refresh_due_after_7_days():
    assert refresh_due({"token_refreshed_at": (NOW - timedelta(days=8)).isoformat()}, NOW)
    assert not refresh_due({"token_refreshed_at": (NOW - timedelta(days=6)).isoformat()}, NOW)


def test_first_run_records_baseline_instead_of_refreshing(tmp_path):
    """A brand-new token is < 24 h old, and Meta refuses to refresh those. So the first run must not try."""
    state = tmp_path / "state.json"
    state.write_text("{}")
    calls = []
    msg = refresh_if_due(state, "TOKEN", NOW, refresh_fn=lambda t: calls.append(t) or "NEW",
                         store_fn=lambda v: calls.append(v))
    assert calls == [] and "first" in msg
    assert json.loads(state.read_text())["token_refreshed_at"] == NOW.isoformat()


def test_refresh_after_7_days_stores_new_token(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"token_refreshed_at": (NOW - timedelta(days=8)).isoformat()}))
    stored = []
    refresh_if_due(state, "OLD", NOW, refresh_fn=lambda t: "NEW", store_fn=stored.append)
    assert stored == ["NEW"]
    assert json.loads(state.read_text())["token_refreshed_at"] == NOW.isoformat()


def test_store_secret_encrypts_for_github():
    sk = PrivateKey.generate()

    class Resp:
        def __init__(self, payload=None, status=200):
            self.payload, self.status_code, self.ok = payload, status, status < 400

        def json(self):
            return self.payload

    class S:
        put_body = None

        def get(self, url, headers=None, timeout=None):
            assert url.endswith("/repos/owner/repo/actions/secrets/public-key")
            return Resp({"key_id": "K1", "key": base64.b64encode(bytes(sk.public_key)).decode()})

        def put(self, url, headers=None, json=None, timeout=None):
            assert url.endswith("/actions/secrets/IG_ACCESS_TOKEN")
            S.put_body = json
            return Resp(status=204)

    store_secret("owner/repo", "IG_ACCESS_TOKEN", "new-token-value", "PAT", session=S())
    assert S.put_body["key_id"] == "K1"
    assert SealedBox(sk).decrypt(base64.b64decode(S.put_body["encrypted_value"])).decode() == "new-token-value"
