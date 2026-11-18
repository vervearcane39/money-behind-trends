"""Caption: fixed-template context line, verified facts verbatim with sources, photo credit, hashtags.
No model-written sentence ever reaches the caption."""
import re

_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


def copy_ok(text: str, cfg: dict) -> tuple[bool, str]:
    low = text.lower()
    hits = [p for p in cfg["copy"]["banned_phrases"] if p in low]
    if hits:
        return False, f"banned phrase: {hits}"
    if len(_EMOJI.findall(text)) > cfg["copy"]["max_emoji"]:
        return False, "too many emoji"
    return True, "ok"


def _display(title: str) -> str:
    return title if any(c.isupper() for c in title) else title.title()


def topic_label(trend, angle) -> str | None:
    """The subject name shown on images and in the caption. Feed headlines are never shown (unverified claims)."""
    if angle is not None and angle.name:
        return angle.name
    return None if trend.source == "feed" else _display(trend.title)


def _hashtag(label: str) -> str:
    return "#" + re.sub(r"[^A-Za-z0-9]", "", _display(label).title() if label.islower() else label.replace(" ", ""))


def build(trend, facts, photo, angle, cfg: dict) -> str:
    label = topic_label(trend, angle)
    context = {"google_trends": f"{label} is trending in {cfg['geos'].get(trend.geo, trend.geo)}.",
               "wikipedia": f"{label} is among the most-read articles on English Wikipedia.",
               "feed": f"{label} is in the business news.",
               "evergreen": f"The money behind {label}."}[trend.source]
    lines = [context, ""]
    for i, f in enumerate(facts, 1):
        lines.append(f"{i}. {f.claim}" if len(facts) > 1 else f.claim)
        names = [f.primary.name] + ([f.corroborator.name] if f.corroborator else [])
        lines.append(("Sources: " if len(names) > 1 else "Source: ") + ", ".join(names))
        lines.append("")
    if photo:
        extra = " (pexels.com)" if photo.provider == "Pexels" else (
            "" if photo.licence.lower().startswith(("cc0", "public", "pd")) else f" ({photo.licence})")
        lines.append(f"Photo: {photo.credit}{extra}")
    tags = []
    for t in cfg["copy"]["base_hashtags"] + [_hashtag(label)] + [f"#{t}" for t in (angle.tags if angle else [])]:
        if t.lower() not in (x.lower() for x in tags) and len(t) > 1:
            tags.append(t)
    lines.append(" ".join(tags[: cfg["copy"]["max_hashtags"]]))
    return "\n".join(lines).strip()
