import base64
from datetime import datetime, timedelta, timezone

from nacl.public import PrivateKey, SealedBox

from factpage.token import refresh_due, store_secret

NOW = datetime(2026, 11, 18, tzinfo=timezone.utc)


def test_refresh_due_after_7_days():
    assert refresh_due({"token_refreshed_at": (NOW - timedelta(days=8)).isoformat()}, NOW)
    assert not refresh_due({"token_refreshed_at": (NOW - timedelta(days=6)).isoformat()}, NOW)
    assert refresh_due({}, NOW)


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
