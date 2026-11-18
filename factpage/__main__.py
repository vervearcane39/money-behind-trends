"""CLI: python -m factpage <command>. Run with --help for the list."""
import argparse
import logging
import sys
from datetime import datetime, timezone

from .config import ROOT, load_config


def cmd_candidates(args, cfg):
    from .filters import blocklist_hit, classify_safety, pick, score_angles, shortlist
    from .history import History
    from .llm import LLM
    from .trends import collect

    now = datetime.now(timezone.utc)
    trends = collect(cfg, now)
    print(f"{len(trends)} candidates collected\n")
    if args.no_llm:
        for t in trends:
            hit = blocklist_hit(t.title, cfg["blocklist"])
            print(f"{'DROP' if hit else 'ok  '}  [{t.source}{':' + t.geo if t.geo else ''}] {t.title}"
                  f"{'  — blocklist: ' + hit if hit else ''}")
        return 0
    pool = shortlist(trends, cfg)
    llm = LLM(cfg)
    safety = classify_safety(llm, pool)
    safe = [t for t in pool if safety[t.title][0] == "SAFE"]
    angles = score_angles(llm, safe) if safe else {}
    _, _, decisions = pick(pool, safety, angles, History(ROOT / "data/history.jsonl"), cfg, now)
    for d in decisions:
        print(f"{'KEEP' if d.kept else 'DROP'}  {d.title}  — {d.reason}")
    return 0


def cmd_sample_render(args, cfg):
    """Layout samples with obvious placeholder text (never real facts) for reviewing the design."""
    from .images import find_photo
    from .render import Slide, headline_for, render_slides

    out = ROOT / "samples"
    photo = find_photo(args.photo_query, cfg, out / "photos")
    print("photo:", f"{photo.credit} ({photo.licence}) {photo.source_url}" if photo else "none found → plain background")
    topic, handle = "Sample Topic", cfg["handle"] or "@yourhandle"
    fact = "Placeholder text showing where one verified fact goes, up to twenty-five words, with its year."
    slides = [Slide("hook", topic, headline_for(topic, cfg), "", None, [], handle, photo, "1/3"),
              Slide("fact", topic, "", fact, "₹1,234 crore", ["Source A", "Source B"], handle, photo, "2/3"),
              Slide("fact", topic, "", fact, "48%", ["Source A", "Source B"], handle, None, "3/3"),
              Slide("single", topic, headline_for(topic, cfg), fact, "US$2.9 billion", ["Source A", "Source B"], handle, photo)]
    for p in render_slides(slides, out, cfg):
        print(p.relative_to(ROOT))
    return 0


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles crash on non-English trend titles otherwise
        stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    p = argparse.ArgumentParser(prog="factpage")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("candidates", help="print today's trending candidates and why each was kept or dropped")
    c.add_argument("--no-llm", action="store_true", help="blocklist only, no AI calls")
    s = sub.add_parser("sample-render", help="render layout samples (placeholder text) into samples/")
    s.add_argument("--photo-query", default="cinema hall")
    args = p.parse_args(argv)
    cfg = load_config()
    return {"candidates": cmd_candidates, "sample-render": cmd_sample_render}[args.cmd](args, cfg)


if __name__ == "__main__":
    sys.exit(main())
