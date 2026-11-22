"""Human-readable verification report for one slot, so any post (or skip) can be audited later."""


def _line(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def render(rec: dict) -> str:
    out = [f"# {rec.get('topic') or 'Skipped slot'} — {rec['run_id']}", "",
           f"- **Status:** {rec['status']}" + (f" — {rec['reason']}" if rec.get("reason") else ""),
           f"- **Mode:** {rec['mode']}", f"- **Time (UTC):** {rec['at']}"]
    if rec.get("trend_title"):
        out += [f"- **Trend:** \"{rec['trend_title']}\" via {rec['trend_source']}"
                f"{' (' + rec['geo'] + ')' if rec.get('geo') else ''}",
                f"- **Angle:** {rec.get('angle', {}).get('angle', '')}"]
    if rec.get("media_id"):
        out.append(f"- **Instagram media ID:** {rec['media_id']}")

    if rec.get("facts"):
        out += ["", "## Published facts (verbatim)"]
        for i, f in enumerate(rec["facts"], 1):
            out += [f"### {i}. {f['claim']}", f"- Source: {f['primary_url']}", f"  > {f['primary_quote']}"]
            if f.get("corroborator_url"):
                pub = f" (published {f['corroborator_published']})" if f.get("corroborator_published") else ""
                out += [f"- Second source: {f['corroborator_url']}{pub}", f"  > {f['corroborator_excerpt']}"]
            else:
                out.append("- Second source: none required (one allowlisted news source is enough)")
            out.append(f"- Verifier model: {f['verifier']}")
    if rec.get("photo"):
        p = rec["photo"]
        out += ["", "## Image credit", f"{p['credit']} — {p['licence']} — {p['source_url']}"]
    elif rec.get("facts"):
        out += ["", "## Image credit", "No licensed photo found; plain brand background used."]
    if rec.get("caption"):
        out += ["", "## Caption", "```", rec["caption"], "```"]

    if rec.get("checks"):
        out += ["", "## Every candidate fact and its checks"]
        for c in rec["checks"]:
            out.append(f"- **{c['claim']}**")
            if c.get("skipped"):
                out.append(f"  - skipped: {c['skipped']}")
                continue
            out.append(f"  - source: {c['source_url']}")
            for name, (ok, why) in c["results"].items():
                out.append(f"  - {_line(ok)} `{name}` — {why}")
    if rec.get("sources"):
        out += ["", "## Sources fetched"]
        out += [f"- {s['name']} ({s['words']} words): {s['url']}" for s in rec["sources"]]
    if rec.get("decisions"):
        out += ["", "## Topic decisions"]
        out += [f"- {'KEEP' if d['kept'] else 'drop'} — {d['title']} — {d['reason']}" for d in rec["decisions"]]
    return "\n".join(out) + "\n"
