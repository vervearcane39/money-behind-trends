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


def cmd_run(args, cfg):
    from .history import History
    from .pipeline import run_slot, silent_too_long

    rec = run_slot(cfg, dry_run=args.dry_run, root=ROOT, now=datetime.now(timezone.utc))
    print(f"status: {rec['status']}" + (f" — {rec['reason']}" if rec["reason"] else ""))
    print(f"topic: {rec['topic']}\nreport: {rec.get('report')}")
    for f in rec["facts"]:
        print(f"fact: {f['claim']}")
    n = cfg["alert_after_skipped_runs"]
    if silent_too_long(History(ROOT / "data/history.jsonl"), n):
        print(f"ALERT: the last {n} slots were all skipped. Open reports/ to see why.", file=sys.stderr)
        return 1  # fails the workflow → GitHub emails you
    return 0  # an occasional skipped slot is normal, not a failure


def _token_file():
    import os
    from pathlib import Path
    return Path(os.environ["RUNNER_TEMP"]) / "ig_token" if os.environ.get("RUNNER_TEMP") else None


def _login(cfg) -> str:
    return cfg["instagram"].get("login", "instagram")


def _host(cfg) -> str:
    return "graph.facebook.com" if _login(cfg) == "facebook" else "graph.instagram.com"


def cmd_publish(args, cfg):
    import os
    from .pipeline import publish_pending
    from .publish import InstagramPublisher, check_urls

    tf = _token_file()
    token = tf.read_text().strip() if tf and tf.exists() else os.environ.get("IG_ACCESS_TOKEN", "")
    if not token or not os.environ.get("IG_USER_ID"):
        raise SystemExit("IG_ACCESS_TOKEN and IG_USER_ID must be set to publish")
    pub = InstagramPublisher(token, os.environ["IG_USER_ID"], cfg["instagram"]["api_version"], host=_host(cfg))
    media_id = publish_pending(cfg, ROOT, args.pending, args.base_url, pub, check_urls, datetime.now(timezone.utc))
    print(f"published: media id {media_id}")
    return 0


def cmd_check_instagram(args, cfg):
    import os
    from .publish import PublishError, check_instagram

    token = os.environ.get("IG_ACCESS_TOKEN", "")
    if not token:
        print("IG_ACCESS_TOKEN is not set")
        return 1
    try:
        for line in check_instagram(token, os.environ.get("IG_USER_ID", ""), cfg["instagram"]["api_version"],
                                    login=_login(cfg), handle=cfg["handle"]):
            print(line)
    except PublishError as e:
        print(f"PROBLEM: {e}")
        return 1
    return 0


def cmd_facebook_setup(args, cfg):
    """One-time: turn the Facebook user token in IG_ACCESS_TOKEN into the Page token + IG_USER_ID secrets."""
    import os
    from .publish import PublishError, check_instagram, facebook_setup
    from .token import mask, store_secret

    need = ["IG_ACCESS_TOKEN", "FB_APP_ID", "FB_APP_SECRET", "GH_SECRETS_PAT", "GITHUB_REPOSITORY"]
    missing = [n for n in need if not os.environ.get(n)]
    if missing:
        print(f"PROBLEM: these secrets are not set: {', '.join(missing)}")
        return 1
    saved = {}

    def store(name, value):
        mask(value)
        store_secret(os.environ["GITHUB_REPOSITORY"], name, value, os.environ["GH_SECRETS_PAT"])
        saved[name] = value

    v = cfg["instagram"]["api_version"]
    try:
        for line in facebook_setup(os.environ["IG_ACCESS_TOKEN"], os.environ["FB_APP_ID"], os.environ["FB_APP_SECRET"],
                                   cfg["handle"], v, store):
            print(line)
        for line in check_instagram(saved["IG_ACCESS_TOKEN"], saved["IG_USER_ID"], v, login="facebook",
                                    handle=cfg["handle"]):
            print(line)
    except PublishError as e:
        print(f"PROBLEM: {e}")
        return 1
    return 0


def cmd_refresh_token(args, cfg):
    import os
    from .token import refresh, refresh_if_due, store_secret

    if _login(cfg) == "facebook":
        print("facebook mode: the Page token does not expire, nothing to refresh")
        return 0
    token = os.environ.get("IG_ACCESS_TOKEN")
    if not token:
        print("no IG_ACCESS_TOKEN configured — skipping token refresh (fine during dry-run setup)")
        return 0

    def store(new):
        store_secret(os.environ["GITHUB_REPOSITORY"], "IG_ACCESS_TOKEN", new, os.environ["GH_SECRETS_PAT"])
        tf = _token_file()
        if tf:
            tf.write_text(new)  # later steps in this run use the fresh token

    print(refresh_if_due(ROOT / "data/state.json", token, datetime.now(timezone.utc), refresh, store))
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
    r = sub.add_parser("run", help="run one posting slot (writes out/, reports/, data/history.jsonl)")
    r.add_argument("--dry-run", action="store_true", help="never prepare anything for publishing")
    pb = sub.add_parser("publish", help="publish the images prepared by `run` (needs IG secrets)")
    pb.add_argument("pending", help="path to out/pending.json")
    pb.add_argument("--base-url", required=True, help="public URL where out/site is served (GitHub Pages)")
    sub.add_parser("refresh-token", help="refresh the Instagram token if 7+ days old and save it to GitHub secrets")
    sub.add_parser("check-instagram", help="read-only check of the Instagram token, account and publishing permission")
    sub.add_parser("facebook-setup", help="one-time: save the Facebook Page token and IG_USER_ID to GitHub secrets")
    args = p.parse_args(argv)
    cfg = load_config()
    return {"candidates": cmd_candidates, "sample-render": cmd_sample_render, "run": cmd_run,
            "publish": cmd_publish, "refresh-token": cmd_refresh_token,
            "check-instagram": cmd_check_instagram, "facebook-setup": cmd_facebook_setup}[args.cmd](args, cfg)


if __name__ == "__main__":
    sys.exit(main())
