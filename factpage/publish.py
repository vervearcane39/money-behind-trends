"""Instagram Content Publishing API (Instagram API with Instagram Login). Official endpoints only.
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


class InstagramPublisher:
    def __init__(self, token: str, ig_user_id: str, api_version: str, session=requests, sleep=time.sleep):
        self.token, self.uid, self.session, self.sleep = token, ig_user_id, session, sleep
        self.base = f"https://graph.instagram.com/{api_version}"

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
