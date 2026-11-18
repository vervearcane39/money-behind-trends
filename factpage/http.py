"""All outbound HTTP. Web pages obey robots.txt; documented APIs (Wikimedia, Pexels, Groq, Instagram,
GitHub) are called with check_robots=False and follow their own API terms instead."""
import logging
import urllib.robotparser
from urllib.parse import urlsplit

import requests

from .config import load_config

log = logging.getLogger("factpage")
UA = load_config()["user_agent"]
session = requests.Session()
session.headers["User-Agent"] = UA
_robots: dict[str, urllib.robotparser.RobotFileParser] = {}


def robots_allowed(url: str) -> bool:
    p = urlsplit(url)
    origin = f"{p.scheme}://{p.netloc}"
    if origin not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = session.get(origin + "/robots.txt", timeout=15)
            if r.status_code in (401, 403) or r.status_code >= 500:
                rp.disallow_all = True  # can't read the rules → don't crawl
            elif r.status_code >= 400:
                rp.allow_all = True  # no robots.txt → allowed
            else:
                rp.parse(r.text.splitlines())
        except requests.RequestException:
            rp.disallow_all = True
        _robots[origin] = rp
    return _robots[origin].can_fetch(UA, url)


def get(url: str, *, timeout: int = 20, check_robots: bool = True, **kw) -> requests.Response | None:
    """GET with our User-Agent. Returns None (and logs why) on robots-disallow, network error or non-2xx."""
    if check_robots and not robots_allowed(url):
        log.info("robots.txt disallows %s", url)
        return None
    try:
        r = session.get(url, timeout=timeout, **kw)
    except requests.RequestException as e:
        log.info("fetch failed %s: %s", url, e)
        return None
    if check_robots and r.url != url and not robots_allowed(r.url):
        log.info("robots.txt disallows redirect target %s", r.url)
        return None
    if not r.ok:
        log.info("HTTP %s for %s", r.status_code, url)
        return None
    return r
