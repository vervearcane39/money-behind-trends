import re

from PIL import Image

from factpage.config import load_config
from factpage.render import Slide, headline_for, render_slides

CFG = load_config()


def test_headline_never_has_digits_and_fits():
    for topic in ["Ramayana: Part 1", "nvidia", "Indian Premier League auction season highlights again"]:
        h = headline_for(topic, CFG)
        assert len(h.split()) <= CFG["copy"]["max_headline_words"]
        assert not re.search(r"\d", h)


def test_lowercase_search_query_is_title_cased():
    assert headline_for("mcx gold", CFG) == "The money behind Mcx Gold"


def test_fact_slide_photo_fills_full_width(tmp_path):
    from factpage.images import Photo
    white = tmp_path / "white.jpg"
    Image.new("RGB", (1080, 1350), "white").save(white)
    photo = Photo(white, "x", "CC0", "u", "test")
    [p] = render_slides([Slide("fact", "T", "", "Fact text here.", "48%", ["A"], "@h", photo)], tmp_path / "o", CFG)
    r, g, b = Image.open(p).getpixel((1050, 300))
    assert r > 80, "right edge shows background instead of the photo"


def test_renders_into_relative_folder(tmp_path, monkeypatch):
    from pathlib import Path
    monkeypatch.chdir(tmp_path)
    [p] = render_slides([Slide("hook", "T", "Behind the numbers", "", None, [], "@h", None)], Path("rel/out"), CFG)
    assert p.exists()


def test_renders_baseline_jpegs_at_1080x1350(tmp_path):
    slides = [Slide("hook", "Sample", "The money behind Sample", "", None, [], "@handle", None),
              Slide("fact", "Sample", "", "Placeholder fact text for layout only, not a real claim.",
                    "₹1,200 crore", ["The Hindu", "BBC"], "@handle", None)]
    paths = render_slides(slides, tmp_path, CFG)
    assert len(paths) == 2
    for p in paths:
        im = Image.open(p)
        assert im.format == "JPEG" and im.size == (1080, 1350) and im.mode == "RGB"
        assert "progressive" not in im.info and "progression" not in im.info
