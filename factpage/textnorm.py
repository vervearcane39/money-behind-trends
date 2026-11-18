"""Text normalisation shared by the verification gate: verbatim matching, numbers, names, domains."""
import re
import unicodedata
from decimal import Decimal

import tldextract

_QUOTES = str.maketrans({"‘": "'", "’": "'", "‚": "'", "“": '"', "”": '"', "„": '"', "«": '"', "»": '"',
                         "–": "-", "—": "-", "−": "-", "‐": "-", " ": " "})

_NUM_RE = re.compile(r"""
    (?<![\w.])
    (?:(?P<cur>₹|rs\.?|inr|us\$|usd|\$|€|eur|£|gbp)\s?)?
    (?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)
    (?:\s?(?P<unit>%|per\s?cent|percent|crores?|cr|lakhs?|thousand|k|million|mn|m|billion|bn|b|trillion|tn)(?![a-z]))?
""", re.I | re.X)

_MULT = {"crore": 10**7, "crores": 10**7, "cr": 10**7, "lakh": 10**5, "lakhs": 10**5, "thousand": 10**3, "k": 10**3,
         "million": 10**6, "mn": 10**6, "m": 10**6, "billion": 10**9, "bn": 10**9, "b": 10**9,
         "trillion": 10**12, "tn": 10**12}
_CUR = {"₹": "₹", "rs": "₹", "rs.": "₹", "inr": "₹", "$": "$", "us$": "$", "usd": "$",
        "€": "€", "eur": "€", "£": "£", "gbp": "£"}

_STOP = set("""a an the in on at as by for from of and but or nor with its it this that these those over after before
during since each every only more less about than then when while who whom which what where why how his her their they
he she we our you your also according some most all both to into under up until per via among within without across
however meanwhile despite between yet so if new last first next""".split())


def norm(text: str) -> str:
    """Lowercase, unify quotes/dashes, drop punctuation except inside numbers, collapse whitespace."""
    t = unicodedata.normalize("NFKC", text).translate(_QUOTES).lower()
    t = re.sub(r"(?<=\d)\.(?=\d)", "\x00", t)
    t = re.sub(r"(?<=\d),(?=\d)", "\x01", t)
    t = re.sub(r"[^\w\s%₹$€£\x00\x01]", " ", t)
    t = t.replace("\x00", ".").replace("\x01", ",")
    return re.sub(r"\s+", " ", t).strip()


def _matches(text: str):
    text = unicodedata.normalize("NFKC", text).translate(_QUOTES)
    for m in _NUM_RE.finditer(text):
        nxt = text[m.end():m.end() + 1]
        if not m.group("unit") and nxt.isalpha():  # "5G", "3rd": not a quantity we can verify
            continue
        yield m


def _canon(m) -> tuple[Decimal, str]:
    value = Decimal(m.group("num").replace(",", ""))
    unit = (m.group("unit") or "").lower().replace(" ", "")
    kind = _CUR.get((m.group("cur") or "").lower(), "")
    if unit == "%" or unit.startswith("per"):
        kind = "%"
    elif unit:
        value *= _MULT[unit]
    return value, kind


def numbers(text: str) -> set[tuple[Decimal, str]]:
    """Canonical (value, kind) for every number; kind is '', '%', '$', '₹', '€' or '£'."""
    return {_canon(m) for m in _matches(text)}


def number_spans(text: str) -> list[str]:
    """Numbers exactly as written (with currency and unit), in order."""
    return [m.group(0).strip() for m in _matches(text)]


def years(text: str) -> set[int]:
    out = set()
    for m in _matches(text):
        value, kind = _canon(m)
        if not kind and not m.group("unit") and value == value.to_integral() and 1800 <= value <= 2099:
            out.add(int(value))
    return out


def proper_nouns(text: str) -> set[str]:
    """Capitalised words/acronyms (incl. 'iPhone'), lowercased, minus stopwords and number spans."""
    t = _NUM_RE.sub(" ", unicodedata.normalize("NFKC", text).translate(_QUOTES))
    out = set()
    for w in re.findall(r"\b(?:[A-Z][\w&'.-]*|[a-z]+[A-Z][\w&'.-]*)", t):
        w = re.sub(r"('s|')$", "", w.rstrip(".-'")).lower()
        if w and w not in _STOP:
            out.add(w)
    return out


_tld = tldextract.TLDExtract(suffix_list_urls=())  # bundled public-suffix snapshot, no network


def registrable_domain(url: str) -> str:
    ext = _tld(url)
    return f"{ext.domain}.{ext.suffix}".lower() if ext.suffix else ext.domain.lower()
