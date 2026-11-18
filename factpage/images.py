"""Licensed background photos: Pexels first, then Wikimedia Commons (public domain / CC0 / CC BY only)."""
import html
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

import cv2

from . import http

log = logging.getLogger("factpage")
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
_FACES = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")


@dataclass
class Photo:
    path: Path
    credit: str
    licence: str
    source_url: str
    provider: str


def commons_licence_ok(short_name: str) -> bool:
    s = short_name.lower().replace("-", " ").strip()
    if not s or re.search(r"\b(sa|nc|nd)\b|share", s):
        return False
    return s.startswith(("cc0", "public domain", "pd")) or bool(re.fullmatch(r"cc by( \d(\.\d)?)?", s))


def rejected_by_tags(text: str, cfg: dict) -> bool:
    low = text.lower()
    return any(re.search(rf"\b{re.escape(t)}\b", low) for t in cfg["images"]["reject_tags"])


def has_face(path: Path) -> bool:
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return True  # unreadable → treat as unsafe
    return len(_FACES.detectMultiScale(img, scaleFactor=1.1, minNeighbors=6, minSize=(60, 60))) > 0


def _strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s or ""))).strip()


def _pexels(query: str) -> list[dict]:
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        return []
    r = http.get("https://api.pexels.com/v1/search", check_robots=False, headers={"Authorization": key},
                 params={"query": query, "orientation": "portrait", "per_page": 15})
    out = []
    for p in (r.json().get("photos", []) if r else []):
        out.append({"url": p["src"]["large2x"], "text": p.get("alt") or "", "provider": "Pexels",
                    "credit": f"{p['photographer']} / Pexels", "licence": "Pexels License", "page": p["url"]})
    return out


def _commons(query: str) -> list[dict]:
    r = http.get(COMMONS_API, check_robots=False, params={
        "action": "query", "format": "json", "formatversion": 2, "generator": "search",
        "gsrsearch": f"{query} filetype:bitmap", "gsrnamespace": 6, "gsrlimit": 20,
        "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": 1600})
    out = []
    for page in (r.json().get("query", {}).get("pages", []) if r else []):
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        lic = meta.get("LicenseShortName", {}).get("value", "")
        if not commons_licence_ok(lic) or not info.get("thumburl"):
            continue
        artist = _strip_html(meta.get("Artist", {}).get("value", "")) or "Unknown author"
        changes = "" if lic.lower().startswith(("cc0", "public", "pd")) else ", cropped, text added"
        text = " ".join(_strip_html(meta.get(k, {}).get("value", "")) for k in ("ImageDescription", "Categories"))
        out.append({"url": info["thumburl"], "text": page.get("title", "") + " " + text, "provider": "Wikimedia Commons",
                    "credit": f"{artist[:80]} / Wikimedia Commons{changes}", "licence": lic,
                    "page": info.get("descriptionurl", "")})
    return out


def find_photo(query: str, cfg: dict, out_dir: Path) -> Photo | None:
    out_dir.mkdir(parents=True, exist_ok=True)
    tried = 0
    for c in _pexels(query) + _commons(query):
        if tried >= 8:
            break
        if rejected_by_tags(c["text"], cfg):
            continue
        tried += 1
        r = http.get(c["url"])
        if r is None or not r.headers.get("content-type", "").startswith("image/"):
            continue
        path = out_dir / f"photo_{tried}.jpg"
        path.write_bytes(r.content)
        if cfg["images"]["avoid_faces"] and has_face(path):
            log.info("photo rejected (face detected): %s", c["page"])
            continue
        return Photo(path, c["credit"], c["licence"], c["page"], c["provider"])
    return None
