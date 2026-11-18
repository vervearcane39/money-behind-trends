"""HTML/CSS template → Playwright PNG → baseline JPEG. render_slide is pure per slide so a v2 Reel can
render frames from the same template and stitch them with ffmpeg."""
import html
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from string import Template

from PIL import Image
from playwright.sync_api import sync_playwright

from .images import Photo

PKG = Path(__file__).resolve().parent
TEMPLATE = Template((PKG / "templates" / "slide.html").read_text(encoding="utf-8"))


@dataclass
class Slide:
    kind: str  # hook | fact | single
    topic: str
    headline: str
    fact: str
    key_number: str | None
    sources: list[str] = field(default_factory=list)
    handle: str = ""
    photo: Photo | None = None
    index: str = ""  # e.g. "2/3"


def display_topic(topic: str) -> str:
    return topic if any(c.isupper() for c in topic) else topic.title()


def headline_for(topic: str, cfg: dict) -> str:
    t = display_topic(topic)
    for tpl in cfg["brand"]["headlines"]:
        h = tpl.format(topic=t)
        if len(h.split()) <= cfg["copy"]["max_headline_words"] and not re.search(r"\d", h):
            return h
    return "Behind the numbers"


def _html(s: Slide, cfg: dict) -> str:
    b, e = cfg["brand"], html.escape
    big_head = s.kind == "hook"
    return TEMPLATE.substitute(
        font_head=(PKG / "fonts" / f"{b['headline_font']}.ttf").as_uri(),
        font_body=(PKG / "fonts" / f"{b['body_font']}.ttf").as_uri(),
        accent=b["accent"], text=b["text"], bg=b["background"], margin=b["margin_px"],
        kind=s.kind, plain="" if s.photo else "plain",
        photo_tag=f'<img class="photo" src="{s.photo.path.resolve().as_uri()}">' if s.photo else "",
        topic=e(display_topic(s.topic)),
        count_tag=f'<div class="count">{e(s.index)}</div>' if s.index else "",
        headline_tag=f'<h1 class="headline" data-fit="{560 if big_head else 200}">{e(s.headline)}</h1>' if s.headline else "",
        rule_tag='<div class="rule"></div>' if s.kind == "hook" else "",
        number_tag=f'<div class="number" data-fit="200">{e(s.key_number)}</div>' if s.key_number else "",
        fact_tag=f'<p class="fact" data-fit="420">{e(s.fact)}</p>' if s.fact else "",
        sources=e("Source: " + ", ".join(s.sources)) if s.sources else "",
        handle=e(s.handle))


def render_slides(slides: list[Slide], out_dir: Path, cfg: dict) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=1)
        for i, s in enumerate(slides, 1):
            src = out_dir / f"slide_{i}.html"
            src.write_text(_html(s, cfg), encoding="utf-8")
            page.goto(src.as_uri())
            page.wait_for_selector("body[data-ready='1']", timeout=15000)
            png = page.screenshot(type="png")
            jpg = out_dir / f"slide_{i}.jpg"
            Image.open(io.BytesIO(png)).convert("RGB").save(jpg, "JPEG", quality=90, optimize=True, progressive=False)
            paths.append(jpg)
        browser.close()
    return paths
