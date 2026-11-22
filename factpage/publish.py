"""Instagram Content Publishing API, via Instagram Login (graph.instagram.com) or a Facebook Page (graph.facebook.com).
Error messages never include the access token or request URLs (Actions logs of a public repo are public)."""
import time

import requests


class PublishError(Exception):
    pass


def check_urls(urls: list[str], session=requests, sleep=time.sleep, tries: int = 6) -> None:
    """Meta cURLs our images, so make sure each URL is live and served as image/jpeg first (Pages can lag)."""
    for url in urls:
        for attempt in range(tries):
            try:
                r = session.head(url, allow_redirects=True, timeout=20)
                if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/jpeg"):
                    break
            except requests.RequestException:
                pass
            sleep(15)
        else:
            raise PublishError(f"image not reachable as JPEG: {url}")


def check_instagram(token: str, expected_user_id: str, api_version: str, session=requests, login: str = "instagram",
                    handle: str = "") -> list[str]:
    """Read-only connection check: token kind, account, and publishing permission. Never posts or prints the token."""
    if login == "facebook":
        if token.startswith("IGAA"):
            raise PublishError("this is an Instagram Login token (IGAA); facebook mode needs the Facebook Page token "
                               "that the facebook-setup workflow saves")
        if not expected_user_id:
            raise PublishError("IG_USER_ID is not set; run the facebook-setup workflow first")
        pub = InstagramPublisher(token, expected_user_id, api_version, session=session, host="graph.facebook.com")
        username = pub._call("GET", expected_user_id, fields="username").get("username", "?")
        want = handle.lstrip("@").lower()
        if want and username.lower() != want:
            raise PublishError(f"this token posts to @{username}, but config.yaml's handle is @{want}")
        d = pub._call("GET", f"{expected_user_id}/content_publishing_limit", fields="quota_usage,config")["data"][0]
        return ["Token: valid Facebook Page token (does not expire)",
                f"Account: @{username} (Instagram user id {expected_user_id})",
                f"Publishing permission: OK; {d['quota_usage']} of {d['config']['quota_total']} posts used in the last 24 h"]
    if token.startswith("EAA"):
        raise PublishError("this is a Facebook Login token (starts with EAA); the system needs an Instagram Login "
                           "token (starts with IGAA) from 'API setup with Instagram login'")
    pub = InstagramPublisher(token, "", api_version, session=session)
    me = pub._call("GET", "me", fields="user_id,username")
    uid, username = str(me.get("user_id", "")), me.get("username", "?")
    if expected_user_id and expected_user_id != uid:
        raise PublishError(f"IG_USER_ID secret ({expected_user_id}) does not match this token's account ({uid})")
    pub.uid = uid
    d = pub._call("GET", f"{uid}/content_publishing_limit", fields="quota_usage,config")["data"][0]
    kind = "Instagram Login (IGAA...)" if token.startswith("IGAA") else "unrecognised prefix, but accepted by Instagram"
    return [f"Token: valid, {kind}",
            f"Account: @{username} (user id {uid})" + ("" if expected_user_id else "  <- use this number for IG_USER_ID"),
            f"Publishing permission: OK; {d['quota_usage']} of {d['config']['quota_total']} posts used in the last 24 h"]


def _fb_get(session, url: str, params: dict, hide: list[str]) -> dict:
    """GET on graph.facebook.com; errors never include tokens or the app secret."""
    try:
        r = session.request("GET", url, params=params, timeout=60)
        body = r.json()
    except (requests.RequestException, ValueError) as e:
        raise PublishError(f"network/parse error {type(e).__name__}") from None
    if not r.ok or "error" in body:
        msg = str(body.get("error", {}).get("message", r.status_code))
        for h in hide:
            msg = msg.replace(h, "***") if h else msg
        raise PublishError(msg)
    return body


def facebook_setup(user_token: str, app_id: str, app_secret: str, handle: str, api_version: str, store,
                   session=requests) -> list[str]:
    """One-time: long-lived user token -> the Facebook Page linked to `handle` -> its Page token (no expiry) and
    Instagram account ID, saved with `store(name, value)`. Returns a report without any token."""
    base, want, hide = f"https://graph.facebook.com/{api_version}", handle.lstrip("@").lower(), [user_token, app_secret]
    long = _fb_get(session, f"{base}/oauth/access_token", {"grant_type": "fb_exchange_token", "client_id": app_id,
                   "client_secret": app_secret, "fb_exchange_token": user_token}, hide)["access_token"]
    hide.append(long)
    pages = _fb_get(session, f"{base}/me/accounts", {"access_token": long,
                    "fields": "id,name,access_token,instagram_business_account{id,username}"}, hide).get("data", [])
    match = next((p for p in pages if (p.get("instagram_business_account") or {}).get("username", "").lower() == want), None)
    if match is None:
        found = [(p.get("instagram_business_account") or {}).get("username") or f"no Instagram on Page '{p.get('name')}'"
                 for p in pages] or ["no Facebook Pages"]
        raise PublishError(f"no Facebook Page you manage is linked to @{want} (found: {', '.join(found)}). Link the "
                           "Instagram account to a Facebook Page, and when generating the token grant pages_show_list, "
                           "pages_read_engagement, instagram_basic and instagram_content_publish")
    ig = match["instagram_business_account"]
    store("IG_ACCESS_TOKEN", match["access_token"])
    store("IG_USER_ID", ig["id"])
    return [f"Facebook Page: {match['name']}", f"Instagram: @{ig['username']} (user id {ig['id']})",
            "Saved IG_ACCESS_TOKEN (Facebook Page token, does not expire) and IG_USER_ID to GitHub secrets"]


class InstagramPublisher:
    def __init__(self, token: str, ig_user_id: str, api_version: str, session=requests, sleep=time.sleep,
                 host: str = "graph.instagram.com"):
        self.token, self.uid, self.session, self.sleep = token, ig_user_id, session, sleep
        self.base = f"https://{host}/{api_version}"  # graph.facebook.com when using a Facebook Page token

    def _call(self, method: str, path: str, **fields) -> dict:
        fields["access_token"] = self.token
        kw = {"data": fields} if method == "POST" else {"params": fields}
        try:
            r = self.session.request(method, f"{self.base}/{path}", timeout=60, **kw)
            body = r.json()
        except (requests.RequestException, ValueError) as e:
            raise PublishError(f"{path}: network/parse error {type(e).__name__}") from None
        if not r.ok or "error" in body:
            msg = str(body.get("error", {}).get("message", r.status_code)).replace(self.token, "***")
            raise PublishError(f"{path}: {msg}")
        return body

    def quota_left(self) -> int:
        d = self._call("GET", f"{self.uid}/content_publishing_limit", fields="quota_usage,config")["data"][0]
        return int(d["config"]["quota_total"]) - int(d["quota_usage"])

    def _wait(self, container_id: str) -> None:
        for attempt in range(5):  # Meta: query status once per minute, for no more than 5 minutes
            status = self._call("GET", container_id, fields="status_code").get("status_code")
            if status == "FINISHED":
                return
            if status in ("ERROR", "EXPIRED"):
                raise PublishError(f"container {container_id} status {status}")
            self.sleep(60)
        raise PublishError(f"container {container_id} not ready after 5 minutes")

    def publish(self, image_urls: list[str], caption: str, alt_texts: list[str]) -> str:
        if self.quota_left() < 1:
            raise PublishError("content publishing limit reached for the last 24 hours")
        if len(image_urls) == 1:
            cid = self._call("POST", f"{self.uid}/media", image_url=image_urls[0], caption=caption,
                             alt_text=alt_texts[0])["id"]
        else:
            children = []
            for url, alt in zip(image_urls, alt_texts):
                child = self._call("POST", f"{self.uid}/media", image_url=url, is_carousel_item="true", alt_text=alt)["id"]
                self._wait(child)
                children.append(child)
            cid = self._call("POST", f"{self.uid}/media", media_type="CAROUSEL", children=",".join(children),
                             caption=caption)["id"]
        self._wait(cid)
        return self._call("POST", f"{self.uid}/media_publish", creation_id=cid)["id"]
