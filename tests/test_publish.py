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


class FakeMe(FakeGraph):
    def request(self, method, url, params=None, data=None, timeout=None):
        if url.endswith("/me"):
            return Resp({"user_id": "1789", "username": "trendonomics.in", "id": "x"})
        return super().request(method, url.replace("/1789/", "/IGID/"), params, data, timeout)


def test_check_instagram_reports_account_and_quota_without_the_token():
    from factpage.publish import check_instagram
    lines = check_instagram("IGAAsecret123", "", "v27.0", session=FakeMe())
    text = "\n".join(lines)
    assert "trendonomics.in" in text and "1789" in text and "Instagram Login" in text
    assert "100" in text  # posting allowance read via content_publishing_limit
    assert "IGAAsecret123" not in text


def test_check_instagram_flags_wrong_token_kind_and_wrong_user_id():
    from factpage.publish import check_instagram
    with pytest.raises(PublishError, match="Facebook"):
        check_instagram("EAAsecret", "", "v27.0", session=FakeMe())
    with pytest.raises(PublishError, match="IG_USER_ID"):
        check_instagram("IGAAsecret", "9999", "v27.0", session=FakeMe())


# ── Facebook-login mode (owner decision 2026-11-22: use the EAA token via a Facebook Page) ──

class FakeFB(FakeGraph):
    """Fake graph.facebook.com: token exchange, the user's Pages, and the IG account behind the Page."""

    def __init__(self, pages=None, **kw):
        super().__init__(**kw)
        self.pages = pages if pages is not None else [
            {"id": "P1", "name": "Other Page", "access_token": "PAGE-TOKEN-OTHER", "instagram_business_account": {"id": "555", "username": "someoneelse"}},
            {"id": "P2", "name": "Trendonomics", "access_token": "PAGE-TOKEN-NEVER-EXPIRES",
             "instagram_business_account": {"id": "1789", "username": "trendonomics.in"}}]

    def request(self, method, url, params=None, data=None, timeout=None):
        assert "graph.facebook.com" in url
        if url.endswith("/oauth/access_token"):
            assert params["grant_type"] == "fb_exchange_token" and params["client_secret"] == "SECRET"
            return Resp({"access_token": "EAA-LONG-LIVED-USER", "token_type": "bearer"})
        if url.endswith("/me/accounts"):
            return Resp({"data": self.pages})
        if url.endswith("/1789") and method == "GET":
            return Resp({"id": "1789", "username": "trendonomics.in"})
        return super().request(method, url.replace("/1789/", "/IGID/"), params, data, timeout)


def test_publisher_uses_facebook_host_in_facebook_mode():
    g = FakeFB()
    InstagramPublisher("PAGE", "IGID", "v27.0", session=g, sleep=lambda s: None, host="graph.facebook.com").publish(
        ["https://x/1.jpg"], "cap", ["a"])
    assert g.calls[-1][1] == "IGID/media_publish"


def test_facebook_setup_stores_never_expiring_page_token_and_ig_id_without_printing_them():
    from factpage.publish import facebook_setup
    stored = {}
    lines = facebook_setup("EAA-SHORT", "APPID", "SECRET", "@trendonomics.in", "v27.0",
                           store=lambda name, value: stored.update({name: value}), session=FakeFB())
    assert stored == {"IG_ACCESS_TOKEN": "PAGE-TOKEN-NEVER-EXPIRES", "IG_USER_ID": "1789"}
    text = "\n".join(lines)
    assert "Trendonomics" in text and "trendonomics.in" in text and "1789" in text
    assert "PAGE-TOKEN" not in text and "EAA" not in text and "SECRET" not in text


def test_facebook_setup_explains_when_no_page_links_the_account():
    from factpage.publish import facebook_setup
    with pytest.raises(PublishError, match="someoneelse"):
        facebook_setup("EAA-SHORT", "APPID", "SECRET", "@trendonomics.in", "v27.0", store=lambda n, v: None,
                       session=FakeFB(pages=[{"id": "P1", "name": "Other", "access_token": "T",
                                              "instagram_business_account": {"id": "555", "username": "someoneelse"}}]))


def test_check_in_facebook_mode_confirms_account_and_permission():
    from factpage.publish import check_instagram
    lines = check_instagram("EAAPAGE", "1789", "v27.0", session=FakeFB(), login="facebook", handle="@trendonomics.in")
    text = "\n".join(lines)
    assert "trendonomics.in" in text and "100" in text and "EAAPAGE" not in text
    with pytest.raises(PublishError, match="Instagram Login token"):
        check_instagram("IGAAx", "1789", "v27.0", session=FakeFB(), login="facebook", handle="@trendonomics.in")


def test_check_urls_requires_jpeg():
    class S:
        def head(self, url, allow_redirects=True, timeout=None):
            return Resp({}, 200, {"content-type": "text/html"})
    with pytest.raises(PublishError):
        check_urls(["https://x/1.jpg"], session=S(), sleep=lambda s: None)
