"""Long-lived Instagram token refresh, persisted back into the repo's GitHub Actions secret."""
import base64
import json
import os
from datetime import datetime, timedelta

import requests
from nacl.public import PublicKey, SealedBox

GH = "https://api.github.com"


def mask(value: str) -> None:
    """Hide a new secret value in GitHub Actions logs (only registered secrets are masked automatically)."""
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::add-mask::{value}")


def refresh_due(state: dict, now: datetime, days: int = 7) -> bool:
    ts = state.get("token_refreshed_at")
    return bool(ts) and now - datetime.fromisoformat(ts) >= timedelta(days=days)


def refresh_if_due(state_path, token: str, now: datetime, refresh_fn, store_fn) -> str:
    """First run only records today's date (Meta refuses to refresh tokens younger than 24 h);
    after that, refresh every 7 days and save the new token via store_fn."""
    state = json.loads(state_path.read_text(encoding="utf-8") or "{}")
    if not state.get("token_refreshed_at"):
        msg = "first run with this token: recorded today's date, will refresh in 7 days"
    elif not refresh_due(state, now):
        return f"token refreshed at {state['token_refreshed_at']}; not due yet"
    else:
        new = refresh_fn(token)
        mask(new)
        store_fn(new)
        msg = "token refreshed and saved to the IG_ACCESS_TOKEN secret"
    state["token_refreshed_at"] = now.isoformat()
    state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")
    return msg


def refresh(token: str, session=requests) -> str:
    r = session.get("https://graph.instagram.com/refresh_access_token",
                    params={"grant_type": "ig_refresh_token", "access_token": token}, timeout=30)
    body = r.json() if r.content else {}
    if not r.ok or "access_token" not in body:
        raise RuntimeError(f"token refresh failed: {str(body.get('error', {}).get('message', r.status_code))}")
    return body["access_token"]


def store_secret(repo: str, name: str, value: str, pat: str, session=requests) -> None:
    h = {"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    r = session.get(f"{GH}/repos/{repo}/actions/secrets/public-key", headers=h, timeout=30)
    if not r.ok:
        raise RuntimeError(f"could not read repo public key (HTTP {r.status_code}) — check GH_SECRETS_PAT")
    k = r.json()
    sealed = SealedBox(PublicKey(base64.b64decode(k["key"]))).encrypt(value.encode())
    r = session.put(f"{GH}/repos/{repo}/actions/secrets/{name}", headers=h, timeout=30,
                    json={"encrypted_value": base64.b64encode(sealed).decode(), "key_id": k["key_id"]})
    if not r.ok:
        raise RuntimeError(f"could not update secret {name} (HTTP {r.status_code}) — check GH_SECRETS_PAT")
