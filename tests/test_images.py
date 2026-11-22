import numpy as np
from PIL import Image

from factpage.config import load_config
from factpage.images import commons_licence_ok, has_face, rejected_by_tags

CFG = load_config()


def test_commons_licences():
    assert commons_licence_ok("CC0")
    assert commons_licence_ok("Public domain")
    assert commons_licence_ok("CC BY 4.0")
    assert commons_licence_ok("CC BY 2.0")
    assert not commons_licence_ok("CC BY-SA 4.0")
    assert not commons_licence_ok("CC BY-NC 2.0")
    assert not commons_licence_ok("CC BY-ND 3.0")
    assert not commons_licence_ok("GFDL")
    assert not commons_licence_ok("")


def test_logo_tags_rejected():
    assert rejected_by_tags("Company logo on glass building", CFG)
    assert not rejected_by_tags("Empty cinema hall with red seats", CFG)


def test_plain_image_has_no_face(tmp_path):
    p = tmp_path / "flat.jpg"
    Image.fromarray(np.full((400, 400, 3), 120, dtype=np.uint8)).save(p)
    assert has_face(p) is False
