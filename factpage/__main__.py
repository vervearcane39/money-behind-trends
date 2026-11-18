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


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles crash on non-English trend titles otherwise
        stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    p = argparse.ArgumentParser(prog="factpage")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("candidates", help="print today's trending candidates and why each was kept or dropped")
    c.add_argument("--no-llm", action="store_true", help="blocklist only, no AI calls")
    args = p.parse_args(argv)
    cfg = load_config()
    return {"candidates": cmd_candidates}[args.cmd](args, cfg)


if __name__ == "__main__":
    sys.exit(main())
