import pytest

from factpage.publish import InstagramPublisher, PublishError, check_urls


class Resp:
    def __init__(self, payload, status=200, headers=None):
        self.payload, self.status_code, self.headers = payload, status, headers or {}
        self.ok = status < 400

    def json(self):
        return self.payload


class FakeGraph:
    """Minimal fake of graph.instagram.com that records every call."""

    def __init__(self, quota_used=0, status="FINISHED"):
        self.calls, self.quota_used, self.status, self.n = [], quota_used, status, 0

    def request(self, method, url, params=None, data=None, timeout=None):
        path = url.split("/v27.0/")[1]
        body = dict(data or params or {})
        body.pop("access_token", None)
        self.calls.append((method, path, body))
        if path.endswith("content_publishing_limit"):
            return Resp({"data": [{"quota_usage": self.quota_used, "config": {"quota_total": 100}}]})
        if path.endswith("/media") and method == "POST":
            self.n += 1
            return Resp({"id": f"c{self.n}"})
        if path.endswith("media_publish"):
            return Resp({"id": "MEDIA123"})
        if method == "GET":  # container status
            return Resp({"status_code": self.status})
        return Resp({"error": {"message": "unexpected"}}, 400)


def pub(g):
    return InstagramPublisher("TOKEN", "IGID", "v27.0", session=g, sleep=lambda s: None)


def test_single_image_flow():
    g = FakeGraph()
    assert pub(g).publish(["https://x/1.jpg"], "cap", ["alt 1"]) == "MEDIA123"
    posts = [(p, b) for m, p, b in g.calls if m == "POST"]
    assert posts[0] == ("IGID/media", {"image_url": "https://x/1.jpg", "caption": "cap", "alt_text": "alt 1"})
    assert posts[-1] == ("IGID/media_publish", {"creation_id": "c1"})
    assert len(posts) == 2


def test_carousel_flow():
    g = FakeGraph()
    pub(g).publish(["https://x/1.jpg", "https://x/2.jpg", "https://x/3.jpg"], "cap", ["a", "b", "c"])
    posts = [(p, b) for m, p, b in g.calls if m == "POST"]
    assert [b.get("is_carousel_item") for _, b in posts[:3]] == ["true", "true", "true"]
    assert "caption" not in posts[0][1]
    assert posts[3][1] == {"media_type": "CAROUSEL", "children": "c1,c2,c3", "caption": "cap"}
    assert posts[4] == ("IGID/media_publish", {"creation_id": "c4"})


def test_container_error_raises():
    with pytest.raises(PublishError):
        pub(FakeGraph(status="ERROR")).publish(["https://x/1.jpg"], "cap", ["a"])


def test_quota_exhausted_raises_before_creating_containers():
    g = FakeGraph(quota_used=100)
    with pytest.raises(PublishError, match="limit"):
        pub(g).publish(["https://x/1.jpg"], "cap", ["a"])
    assert not any(m == "POST" for m, _, _ in g.calls)


def test_error_message_never_contains_token():
    class Boom(FakeGraph):
        def request(self, method, url, params=None, data=None, timeout=None):
            return Resp({"error": {"message": "Invalid OAuth access token"}}, 400)
    with pytest.raises(PublishError) as e:
        pub(Boom()).quota_left()
    assert "TOKEN" not in str(e.value)


def test_check_urls_requires_jpeg():
    class S:
        def head(self, url, allow_redirects=True, timeout=None):
            return Resp({}, 200, {"content-type": "text/html"})
    with pytest.raises(PublishError):
        check_urls(["https://x/1.jpg"], session=S(), sleep=lambda s: None)
