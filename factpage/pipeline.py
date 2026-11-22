"""One posting slot, end to end. Every outcome (post, dry-run or skip) leaves a history line and a report."""
import json
import re
import shutil
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import images, render, research, trends
from .caption import build, copy_ok, topic_label
from .extract import extract_candidates
from .filters import classify_safety, pick, score_angles, shortlist
from .history import History, fact_key, topic_key
from .llm import LLM, MissingKey, RateLimited
from .render import Slide, headline_for
from .report import render as render_report
from .trends import Trend
from .verify import mentions_all_names, on_topic, source_names, verify


MAX_TOPIC_TRIES = 3
MAX_CITED_FETCHES = 15  # extra pages per slot fetched by following Wikipedia citations


def _slides(label, facts, photo, cfg):
    head, handle = headline_for(label, cfg), cfg["handle"]
    if len(facts) == 1:
        f = facts[0]
        return [Slide("single", label, head, f.claim, f.key_number, source_names(f), handle, photo)]
    n = len(facts) + 1
    return [Slide("hook", label, head, "", None, [], handle, photo, f"1/{n}")] + [
        Slide("fact", label, "", f.claim, f.key_number, source_names(f), handle, photo, f"{i}/{n}")
        for i, f in enumerate(facts, 2)]


def _same_story_urls(found: list[Trend], trend: Trend, label: str) -> list[str]:
    """Today's coverage of the same subject from other outlets: links of every other collected headline or
    trend that names it. Read before Wikipedia's (mostly old) references."""
    if len(label) < 3:
        return []
    urls = []
    for t in found:
        if t is trend or t.title == trend.title:
            continue
        if mentions_all_names(t.title + " " + " ".join(t.news), label):  # "Target", not "beating target range"
            urls += [u for u in t.urls if u not in urls]
    return urls


def _alt(slide: Slide) -> str:
    return " ".join(x for x in (slide.headline, slide.fact) if x)


def silent_too_long(hist: History, runs: int) -> bool:
    """True if each of the last `runs` working slots was a skip (the page has gone quiet). Error runs
    (missing key, crash) already fail and email on their own, so they don't count toward the silence alarm."""
    slots = [r for r in hist.records() if r.get("status") in ("skipped", "dry_run", "ready")]
    return len(slots) >= runs and all(r["status"] == "skipped" for r in slots[-runs:])


def publish_pending(cfg: dict, root: Path, pending_path: Path, base_url: str, publisher, check, now: datetime) -> str:
    """Publish what run_slot prepared. Kill switch is re-checked here; success is logged to history + report."""
    if not cfg["publishing_enabled"]:
        raise SystemExit("publishing_enabled is false in config.yaml — refusing to publish")
    p = json.loads(Path(pending_path).read_text(encoding="utf-8"))
    urls = [base_url.rstrip("/") + "/" + img for img in p["images"]]
    check(urls)
    media_id = publisher.publish(urls, p["caption"], p["alt_texts"])
    History(root / "data/history.jsonl").append({
        "run_id": p["run_id"], "at": now.isoformat(), "status": "published", "media_id": media_id,
        "topic_key": p["topic_key"], "topic_keys": p["topic_keys"], "fact_keys": p["fact_keys"],
        "fallback": p["fallback"], "report": p["report"]})
    with (root / p["report"]).open("a", encoding="utf-8") as f:
        f.write(f"\n## Published\n- Instagram media ID: {media_id}\n- Time (UTC): {now.isoformat()}\n")
    return media_id


def _source_row(d) -> dict:
    return {"url": d.url, "name": d.name, "domain": d.domain, "words": len(d.text.split()),
            "wiki_revid": d.wiki_revid, "fetched_at": d.fetched_at}


def run_slot(cfg: dict, *, dry_run: bool, root: Path, now: datetime, llm=None, collect=trends.collect,
             gather=research.gather, find_photo=images.find_photo, render=render.render_slides,
             cite=research.cited_docs) -> dict:
    tz = ZoneInfo(cfg["timezone"])
    live = bool(cfg["publishing_enabled"]) and not dry_run
    run_id = now.astimezone(tz).strftime("%Y%m%d-%H%M")
    out = root / "out" / run_id
    hist = History(root / "data/history.jsonl", count_dry_runs=not live)
    rec = {"run_id": run_id, "at": now.isoformat(), "mode": "live" if live else "dry_run", "status": "skipped",
           "reason": "", "topic": None, "decisions": [], "sources": [], "checks": [], "facts": []}

    def skip(reason):
        rec["reason"] = reason
        return rec

    try:
        llm = llm or LLM(cfg)
        found = collect(cfg, now)
        if not found:
            return skip("no trends collected (all sources down or empty)")
        pool = shortlist(found, cfg)
        safety = classify_safety(llm, pool)
        safe = [t for t in pool if safety[t.title][0] == "SAFE"]
        angles = score_angles(llm, safe) if safe else {}
        tried: dict[str, str] = {}
        for _ in range(MAX_TOPIC_TRIES):  # research costs no AI calls, so try the runner-up if sources are thin
            trend, angle, decisions = pick(pool, safety, angles, hist, cfg, now, exclude=tried)
            rec["decisions"] = [asdict(d) for d in decisions]
            if trend is None:
                return skip("no eligible topic")
            if angle is None:  # evergreen fallback
                angle = score_angles(llm, [trend]).get(trend.title)
                if angle is None:
                    return skip("no angle for fallback topic")
            label = topic_label(trend, angle)
            if not label:
                tried[trend.title] = "no clean topic name for a news headline"
                continue
            urls = trend.urls + [u for u in _same_story_urls(found, trend, label) if u not in trend.urls]
            docs = gather(Trend(label if trend.source == "feed" else trend.title, trend.source, trend.geo,
                                urls, trend.signal), cfg)
            news = [d for d in docs if d.domain != "wikipedia.org"]  # Wikipedia alone can never support a fact
            enough = len(news) >= 1 and (len(docs) >= 2 or not cfg.get("require_second_source", True))
            if enough:
                break
            tried[trend.title] = f"only {len(news)} usable news source(s)"
        else:
            rec["decisions"] = [asdict(d) for d in pick(pool, safety, angles, hist, cfg, now, exclude=tried)[2]]
            return skip(f"not enough usable news source for the top {MAX_TOPIC_TRIES} topics")
        rec.update(topic=label, trend_title=trend.title, trend_source=trend.source, geo=trend.geo,
                   topic_key=topic_key(trend.title), topic_keys=sorted({topic_key(trend.title), topic_key(label)}),
                   fallback=trend.source == "evergreen", angle=asdict(angle))
        rec["sources"] = [_source_row(d) for d in docs]

        facts, keys = [], set()
        wiki = next((d for d in docs if d.wiki_revid), None)
        tried = {d.url for d in docs}
        # Read the newest news first, undated news next, Wikipedia last (it can never support a fact alone).
        # Cited pages fetched later only corroborate; they are never extracted from.
        reading_order = sorted(docs, key=lambda d: (d.domain == "wikipedia.org", -int((d.published or "0").replace("-", ""))))
        for doc in reading_order:
            for cand in extract_candidates(llm, doc, label, angle.angle, cfg, year=now.astimezone(tz).year):
                if len(facts) >= cfg["copy"]["max_facts"]:
                    break
                if not on_topic(cand.claim, label):  # e.g. an Anthropic fact must never appear on a Target post
                    rec["checks"].append({"claim": cand.claim, "quote": cand.quote, "source_url": cand.source_url,
                                          "results": {"g_on_topic": (False, f"fact does not name the topic '{label}'")}})
                    continue
                k = fact_key(cand.claim)
                if k in keys or hist.fact_seen(k):
                    rec["checks"].append({"claim": cand.claim, "skipped": "fact already used"})
                    continue
                fact, log = verify(cand, docs, llm, cfg, today=now.astimezone(tz).date())
                only_c_failed = log.results.get("c_corroborated", (True,))[0] is False
                if only_c_failed and wiki and len(tried) < len(docs) + MAX_CITED_FETCHES:
                    # follow the source Wikipedia cites for this exact figure, then re-run every check
                    extra = [d for d in cite(wiki, cand.claim, cfg, tried) if all(d.url != x.url for x in docs)]
                    if extra:
                        docs = docs + extra
                        rec["sources"] += [_source_row(d) for d in extra]
                        fact, log = verify(cand, docs, llm, cfg, today=now.astimezone(tz).date())
                rec["checks"].append({"claim": cand.claim, "quote": cand.quote, "source_url": cand.source_url,
                                      "results": log.results})
                if fact:
                    facts.append(fact)
                    keys.add(k)
        if not facts:
            return skip("no fact passed verification")

        photo = find_photo(angle.photo_query or label, cfg, out / "photos")
        slides = _slides(label, facts, photo, cfg)
        caption = build(trend, facts, photo, angle, cfg)
        ok, why = copy_ok(caption, cfg)
        if not ok:
            return skip(f"caption failed copy rules: {why}")
        paths = render(slides, out, cfg)
        rec.update(caption=caption, images=[p.name for p in paths], fact_keys=sorted(keys),
                   facts=[{"claim": f.claim, "key_number": f.key_number, "primary_url": f.primary.url,
                           "primary_quote": f.primary_quote,
                           "corroborator_url": f.corroborator.url if f.corroborator else None,
                           "corroborator_excerpt": f.corroborator_excerpt,
                           "corroborator_published": f.corroborator.published if f.corroborator else None,
                           "verifier": f.verifier_reason}
                          for f in facts],
                   photo={"credit": photo.credit, "licence": photo.licence, "source_url": photo.source_url,
                          "provider": photo.provider} if photo else None)
        if not live:
            rec["status"] = "dry_run"
            return rec
        if not cfg["handle"]:
            return skip("live publishing needs `handle` set in config.yaml")
        site = root / "out" / "site" / run_id
        site.mkdir(parents=True, exist_ok=True)
        for p in paths:
            shutil.copy(p, site / p.name)
        rec["status"] = "ready"
        return rec
    except RateLimited:
        return skip("rate limited by AI provider (checks never loosened; slot skipped)")
    except MissingKey as e:
        rec["status"], rec["reason"] = "error", f"AI key problem: {e}"
        raise  # configuration errors fail the run so GitHub emails the owner
    except Exception as e:
        rec["status"], rec["reason"] = "error", f"unexpected {type(e).__name__}: {e}"[:300]
        raise
    finally:
        slug = re.sub(r"[^a-z0-9]+", "-", (rec["topic"] or "skipped").lower()).strip("-")[:40] or "topic"
        local = now.astimezone(tz)
        report = root / "reports" / local.strftime("%Y/%m") / f"{local:%d-%H%M}-{slug}.md"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(render_report(rec), encoding="utf-8")
        rec["report"] = report.relative_to(root).as_posix()
        hist.append({k: v for k, v in rec.items() if k != "decisions"})  # decisions live in the report only
        if rec["status"] == "ready":
            (root / "out" / "pending.json").write_text(json.dumps({
                "run_id": run_id, "images": [f"{run_id}/{n}" for n in rec["images"]], "caption": rec["caption"],
                "alt_texts": [_alt(s) for s in slides], "report": rec["report"], "topic_key": rec["topic_key"],
                "topic_keys": rec["topic_keys"], "fact_keys": rec["fact_keys"], "fallback": rec["fallback"]},
                ensure_ascii=False, indent=1),
                encoding="utf-8")
