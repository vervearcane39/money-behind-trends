# Money Behind Trends Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A scheduled Python pipeline that turns a trending topic into 1–3 verified money facts, renders 1080×1350 JPEGs, and publishes them to Instagram via the official API. It is safe by default: dry-run until the owner flips the switch.

**Architecture:** One CLI (`python -m factpage`) runs one slot end to end: trends → filters → research → extract → code-first verification gate → photo → render → (host + publish) → log. LLM, image host and publisher are the only swappable interfaces. GitHub Actions is the scheduler and Pages is the image host.

**Tech Stack:** Python 3.11; requests, feedparser, trafilatura, tldextract, PyYAML, playwright, Pillow, opencv-python-headless, PyNaCl; pytest.

**Spec:** `docs/superpowers/specs/2026-11-18-money-behind-trends-design.md`

## Global Constraints

- Python 3.11 (local machine is 3.11.9; Actions pinned to 3.11 for parity).
- $0/month. No paid services. No unofficial Instagram libraries. No likes/follows/comments/DMs.
- No investment advice, predictions or price targets. Facts only.
- User-Agent on every request: `MoneyBehindTrends/0.1 (https://github.com/vervearcane39)`.
- robots.txt respected for every fetched URL; paywalled pages skipped; allowlist-only domains.
- Photo sources: Pexels and Wikimedia Commons only (Commons licences: Public domain, CC0, CC BY x.x). No Unsplash, no Pixabay, no AI images.
- LLM roles: `classifier` + `verifier` = `qwen/qwen3.8-27b`; `angle` + `extractor` = `openai/gpt-oss-120b`; base URL `https://api.groq.com/openai/v1`; key env `GROQ_API_KEY`.
- Image: 1080×1350 baseline JPEG, quality 90, sRGB.
- Copy: headline ≤ 8 words with no digits; fact ≤ 25 words. Banned: "did you know", "fun fact", "mind-blowing", "you won't believe", 🤯, more than 1 emoji, "!!".
- `publishing_enabled: false` by default; `--dry-run` always wins.
- Slots: 09:07, 13:07, 18:07, 21:07, timezone `Asia/Kolkata`.
- Topic not repeated within 7 days; fact never repeated; at most 1 fallback (evergreen) post per day.
- Secrets only in GitHub Actions secrets: `GROQ_API_KEY`, `PEXELS_API_KEY`, `IG_ACCESS_TOKEN`, `IG_USER_ID`, `GH_SECRETS_PAT`.

## Review Focus

1. **Non-Latin or odd trend titles** (Hindi queries in geo=IN, emoji, "x vs y"). Expected: no crash. The topic is dropped if no allowlisted English source matches. Test in Task 2.
2. **LLM returns prose, truncated or malformed JSON.** Expected: that step treats it as "drop/unsure", never as a pass. Tests in Tasks 2, 4.
3. **A source URL times out, 403s, redirects off-allowlist or is disallowed by robots.txt.** Expected: that source is skipped and the run continues. Test in Task 3.
4. **Every trend source is down or empty.** Expected: the slot is skipped with a logged reason and exit code 0 (a skip is not a failure). Test in Task 7.
5. **The same fact resurfacing days later in different words** (same number, same subject). Expected: dropped by the forever-dedupe on the canonical number set + key nouns. Test in Task 1.

---

### Task 1: Scaffold, config, history, numbers

**Files:**
- Create: `requirements.txt`, `config.yaml`, `factpage/__init__.py`, `factpage/config.py`, `factpage/history.py`, `factpage/textnorm.py`, `data/history.jsonl` (empty), `data/state.json` (`{}`), `.gitignore`
- Test: `tests/test_textnorm.py`, `tests/test_history.py`

**Interfaces:**
- Produces:
  - `load_config(path="config.yaml") -> dict`
  - `textnorm.norm(text) -> str` (for verbatim matching)
  - `textnorm.numbers(text) -> set[tuple[Decimal, str]]` (canonical value, kind in `{"", "%", "$", "₹", "€", "£"}`)
  - `textnorm.number_spans(text) -> list[str]` (as written)
  - `textnorm.proper_nouns(text) -> set[str]`
  - `textnorm.years(text) -> set[int]`
  - `textnorm.registrable_domain(url) -> str`
  - `History(path)` with methods `topic_used_within(key, days, now) -> bool`, `fact_seen(fact_key) -> bool`, `fallback_used_on(date) -> bool`, `append(record: dict)`
  - `topic_key(title) -> str`; `fact_key(claim) -> str`

- [ ] Step 1: Write the failing tests.
  - `numbers("₹1,200 crore") == {(Decimal("12000000000"), "₹")}`
  - `numbers("Rs 1,200 crore") == numbers("INR 1200 crore")`
  - `numbers("$1.2 billion") == numbers("US$1,200 million")`
  - `numbers("$1.2 billion") != numbers("$1.3 billion")`
  - `numbers("12.5%") == {(Decimal("12.5"), "%")}`
  - `years("as of 2025, revenue") == {2025}`
  - `proper_nouns("Netflix paid Sony") ⊇ {"netflix", "sony"}`; stopwords such as "The" are excluded
  - `norm("“Hello”—world") == norm('"hello" - world')`
  - `registrable_domain("https://en.m.wikipedia.org/x") == "wikipedia.org"`
  - History tests: topic used 6 days ago → True for 7 days; 8 days ago → False; `fact_key("Avatar earned $2.9 billion as of 2023") == fact_key("As of 2023, Avatar earned US$2,900 million")`
- [ ] Step 2: `pytest tests/test_textnorm.py tests/test_history.py -v` → FAIL (module not found).
- [ ] Step 3: Implement.
  - Number regex: optional currency (`₹|Rs\.?|INR|\$|US\$|USD|€|EUR|£|GBP`), digits with `,` groups and optional decimal, optional unit (`%|percent|crore|cr|lakh|thousand|k|million|mn|m|billion|bn|b|trillion|tn`). Multipliers: crore 1e7, lakh 1e5, k/thousand 1e3, million/mn/m 1e6, billion/bn/b 1e9, trillion/tn 1e12.
  - `fact_key` = sorted canonical numbers + sorted proper nouns, sha1.
  - `tldextract.TLDExtract(suffix_list_urls=())` so it uses the bundled list, offline.
  - `config.yaml` contains every key listed in spec §5.10 with the defaults from the spec.
- [ ] Step 4: Run the same tests → PASS.
- [ ] Step 5: `git commit -m "feat: scaffold, config, text normalisation, history"`

### Task 2: Trends, safety and angle filters, `candidates` CLI

**Files:**
- Create: `factpage/http.py`, `factpage/llm.py`, `factpage/trends.py`, `factpage/filters.py`, `factpage/__main__.py`
- Test: `tests/test_trends.py` (fixtures `tests/fixtures/trends_in.xml`, `wiki_top.json`), `tests/test_filters.py`

**Interfaces:**
- Produces:
  - `http.get(url, *, timeout=20, allow_robots_skip=False) -> requests.Response | None` (None on robots-disallow, network error or non-2xx; reason logged)
  - `http.robots_allowed(url) -> bool`
  - `llm.LLM(cfg).json(role, system, user) -> dict | None` (None on malformed JSON; raises `llm.RateLimited` after 3 backoffs)
  - `Trend(title, source, geo, urls: list[str], signal: int)` dataclass
  - `trends.parse_google_trends(xml, geo) -> list[Trend]`; `trends.parse_wiki_top(json) -> list[Trend]`; `trends.parse_feed(xml, feed_name) -> list[Trend]`; `trends.collect(cfg) -> list[Trend]`
  - `filters.blocklist_hit(title, words) -> str | None`
  - `filters.classify_safety(llm, trends) -> dict[str, tuple[str, str]]` (title → (SAFE|UNSAFE|UNSURE, reason))
  - `filters.score_angles(llm, trends) -> dict[str, Angle]`, where `Angle(score:int, angle:str, photo_query:str, tags:list[str])`
  - `filters.pick(trends, safety, angles, history, cfg, now) -> tuple[Trend | None, Angle | None, list[Decision]]`, where `Decision(title, kept: bool, reason: str)`
  - CLI `python -m factpage candidates` prints one line per Decision.

- [ ] Step 1: Write the failing tests.
  - The Google Trends fixture parses to 10 Trends, the first with ≥1 `urls`.
  - The wiki fixture drops `Main_Page`, `Special:Search`, `Wikipedia:Featured_pictures`.
  - `blocklist_hit("Actor dies in crash", words)` returns "dies".
  - The safety classifier with a fake LLM returning `UNSURE` → dropped; with a fake returning `None` (malformed) → **all** dropped.
  - `pick` skips a topic used 3 days ago; the fallback is not chosen when `history.fallback_used_on(today)`.
  - Review Focus 1: a title "भारत बनाम" with no angle → dropped, no exception.
- [ ] Step 2: `pytest tests/test_trends.py tests/test_filters.py -v` → FAIL.
- [ ] Step 3: Implement.
  - feedparser for RSS; the `ht:` namespace keys come through feedparser as `ht_news_item_url`. **VERIFY by running against the fixture.**
  - Wiki bot-spike heuristic per spec §5.1, marked `# ponytail:`.
  - The safety prompt lists the spec §5.2 categories verbatim and returns `{"results":[{"title","label","reason"}]}`.
  - The angle prompt returns `score, angle, photo_query (object/place, no people), tags (≤2 single words)`.
- [ ] Step 4: Tests → PASS. Run `python -m factpage candidates --no-llm` live (blocklist only) → prints today's real candidates.
- [ ] Step 5: Commit `feat: trend collection and filters`.

### Task 3: Research (fetch rules, domains, paywalls, Wikipedia)

**Files:**
- Create: `factpage/research.py`
- Test: `tests/test_research.py`

**Interfaces:**
- Consumes: `http.get`, `textnorm.registrable_domain`, config `sources.allow` (domain → display name), `sources.deny`, `sources.paywall`.
- Produces:
  - `SourceDoc(url, domain, name, text, fetched_at, wiki_revid: int | None)`
  - `research.allowed(url, cfg) -> bool`
  - `research.is_paywalled(html, text, domain, cfg) -> bool`
  - `research.fetch_doc(url, cfg) -> SourceDoc | None`
  - `research.wikipedia_doc(title) -> tuple[SourceDoc | None, list[str]]` (doc + its external reference URLs)
  - `research.gather(trend, cfg) -> list[SourceDoc]` (deduped by URL, ≤ 8 docs)
  - `research.trim(text, terms, max_chars=12000) -> str`

- [ ] Step 1: Write the failing tests.
  - `allowed("https://www.reuters.com/x")` True (subdomain of an allowlisted domain); `allowed("https://randomfacts.net/x")` False; a denylisted domain is False even if it looks like news.
  - `is_paywalled` True for JSON-LD `"isAccessibleForFree": false` and for text under 150 words.
  - Review Focus 3: `fetch_doc` returns None (no raise) when `http.get` returns None or the final redirect URL is off-allowlist.
- [ ] Step 2: `pytest tests/test_research.py -v` → FAIL.
- [ ] Step 3: Implement.
  - trafilatura `extract(html, include_comments=False)`.
  - Wikipedia via the Action API: `action=query&prop=extracts|revisions|extlinks&explaintext=1&rvprop=ids&ellimit=max&redirects=1&format=json`.
- [ ] Step 4: Tests → PASS. Live smoke: `wikipedia_doc("Jensen Huang")` returns text + revid.
- [ ] Step 5: Commit `feat: research with robots, allowlist and paywall rules`.

### Task 4: Extraction and the verification gate

**Files:**
- Create: `factpage/extract.py`, `factpage/verify.py`
- Test: `tests/test_verify.py`, `tests/test_extract.py`

**Interfaces:**
- Consumes: `SourceDoc`, `LLM`, `textnorm.*`.
- Produces:
  - `Candidate(claim, source_url, quote)`
  - `VerifiedFact(claim, key_number: str | None, primary: SourceDoc, primary_quote, corroborator: SourceDoc, corroborator_excerpt, verifier_reason)`
  - `CheckLog(claim, results: dict[str, tuple[bool, str]])`
  - `extract.extract_candidates(llm, doc, topic, angle) -> list[Candidate]`
  - `verify.verify(candidate, docs, llm, cfg) -> tuple[VerifiedFact | None, CheckLog]` (runs a → b → e → style → c → d in that order, stopping at the first failure)

- [ ] Step 1: Write the failing tests (fake LLM with a configurable verdict).
  - **Required:** `test_rejects_number_off_by_one_digit`: the page says "budget of ₹550 crore"; the claim says "₹560 crore" with the true quote → fails `b`. The same claim with an altered quote → fails `a`.
  - **Required:** `test_rejects_quote_not_in_page`.
  - **Required:** `test_rejects_number_only_on_wikipedia`: the number is only on `en.wikipedia.org` and the second doc is `en.m.wikipedia.org` → fails `c`. The second doc is an allowlisted news page without the number → fails `c`.
  - `test_accepts_supported_claim`: two domains + verdict SUPPORTED → VerifiedFact with `key_number == "₹550 crore"`.
  - Verdict `UNCLEAR` → rejected at `d`. Malformed verdict → rejected at `d`.
  - "currently" in the claim → fails `e`. A number with no year → fails `e`.
  - A superlative ("largest") not in the quote → fails `b`. A proper noun not in the quote → fails `b`.
  - Claim > 25 words or containing "fun fact" → fails `style`.
  - Quote under 8 words → fails `a`.
  - Review Focus 2: `extract_candidates` with a fake LLM returning None → `[]`.
- [ ] Step 2: `pytest tests/test_verify.py tests/test_extract.py -v` → FAIL.
- [ ] Step 3: Implement.
  - The quote must be found in the doc whose URL is `candidate.source_url`.
  - Corroborator: the first other doc with a different registrable domain, not `wikipedia.org`, containing all claim numbers and proper nouns. If the primary is Wikipedia, the corroborator becomes the citation shown.
  - Verifier excerpt: ±300 chars around the first claim number (or proper noun) in each doc.
  - The verifier prompt returns `{"verdict","reason"}`, and only the exact `"SUPPORTED"` passes.
- [ ] Step 4: Tests → PASS.
- [ ] Step 5: Commit `feat: extraction and code-first verification gate`.

### Task 5: Photos and renderer

**Files:**
- Create: `factpage/images.py`, `factpage/render.py`, `factpage/templates/slide.html`, `factpage/fonts/` (Inter + Archivo variable TTFs + `OFL.txt` each, from github.com/google/fonts)
- Test: `tests/test_images.py`, `tests/test_render.py`

**Interfaces:**
- Produces:
  - `Photo(path: Path, credit: str, licence: str, source_url: str, provider: str)`
  - `images.commons_licence_ok(short_name) -> bool`
  - `images.has_face(path) -> bool`
  - `images.find_photo(query, cfg, out_dir) -> Photo | None`
  - `Slide(kind: "hook"|"fact", topic, headline, fact, key_number, sources: list[str], handle, photo: Photo | None)`
  - `render.render_slides(slides, out_dir, cfg) -> list[Path]` (JPEG paths)
  - `render.headline_for(topic, cfg) -> str` (≤ 8 words, no digits)

- [ ] Step 1: Write the failing tests.
  - `commons_licence_ok`: "CC0" ✓, "Public domain" ✓, "CC BY 4.0" ✓, "CC BY-SA 4.0" ✗, "CC BY-NC 2.0" ✗.
  - `headline_for("Ramayana: Part 1", cfg)` has ≤ 8 words and no digits.
  - The render smoke test makes 2 slides with `photo=None` → 2 files that Pillow opens as JPEG, size (1080, 1350), mode RGB.
- [ ] Step 2: `pytest tests/test_images.py tests/test_render.py -v` → FAIL.
- [ ] Step 3: Implement.
  - Pexels `GET https://api.pexels.com/v1/search?query=…&orientation=portrait&per_page=15`, header `Authorization: <key>`. **VERIFY response fields** (`photos[].src.large2x`, `photographer`, `url`) on first live call.
  - Commons Action API `generator=search&gsrnamespace=6&prop=imageinfo&iiprop=url|extmetadata&iiurlwidth=1600`.
  - Face check: `cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")`.
  - Render: Playwright Chromium, viewport 1080×1350, `page.goto(file://…html)`, PNG → Pillow → JPEG q90.
  - Brand values come from config.
- [ ] Step 4: Tests → PASS. `python -m factpage sample-render` writes `samples/*.jpg` (with and without a photo) for owner review.
- [ ] Step 5: Commit `feat: licensed photos and HTML renderer`.

### Task 6: Caption, publishing, token refresh

**Files:**
- Create: `factpage/caption.py`, `factpage/publish.py`, `factpage/token.py`
- Test: `tests/test_caption.py`, `tests/test_publish.py`, `tests/test_token.py`

**Interfaces:**
- Produces:
  - `caption.build(trend, facts: list[VerifiedFact], photo, angle, cfg) -> str`
  - `caption.copy_ok(text, cfg) -> tuple[bool, str]`
  - `publish.InstagramPublisher(token, ig_user_id, api_version)` with `.quota_left() -> int` and `.publish(image_urls: list[str], caption: str) -> str` (media ID)
  - `publish.check_urls(urls) -> None` (raises unless 200 + `image/jpeg`)
  - `token.refresh_due(state, now, days=7) -> bool`
  - `token.refresh(token) -> str`
  - `token.store_secret(repo, name, value, pat) -> None`

- [ ] Step 1: Write the failing tests (requests mocked via `unittest.mock`).
  - The caption contains every fact claim verbatim, "Photo:" credit, 3–5 hashtags, no banned phrase.
  - `publish` with 1 URL → calls `/media` once (no `is_carousel_item`), then `/media_publish`.
  - 3 URLs → 3 item containers with `is_carousel_item=true`, then a `media_type=CAROUSEL` container, then publish.
  - Container `status_code=ERROR` → raises.
  - `quota_left()==0` → `publish` raises before creating containers.
  - `refresh_due` is True at 8 days and False at 6 days.
  - `store_secret` encrypts with a sealed box that decrypts back to the value with the test private key.
- [ ] Step 2: `pytest tests/test_caption.py tests/test_publish.py tests/test_token.py -v` → FAIL.
- [ ] Step 3: Implement against `https://graph.instagram.com/<version>`. **VERIFY the current version string** in Meta's changelog. Poll once per 60s, max 5 times.
- [ ] Step 4: Tests → PASS.
- [ ] Step 5: Commit `feat: caption, Instagram publisher, token refresh`.

### Task 7: Pipeline, reports, dry-run

**Files:**
- Create: `factpage/pipeline.py`, `factpage/report.py`
- Modify: `factpage/__main__.py` (add `run [--dry-run]`, `publish <pending.json> --base-url URL`, `refresh-token`, `sample-render`)
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `pipeline.run_slot(cfg, *, dry_run: bool, out_dir: Path, now) -> dict` (the run record). It writes `out/<run_id>/*.jpg`, `reports/YYYY/MM/DD-HHMM-<slug>.md`, appends `data/history.jsonl`, and (live only) writes `out/pending.json` = `{run_id, images: [names], caption}`.
  - `report.render(record) -> str`

- [ ] Step 1: Write the failing tests (all network/LLM faked).
  - Review Focus 4: `collect` returns [] → the record status is `skipped`, the reason is "no trends", no exception, the history line is appended.
  - All candidates fail verification → status `skipped`, the reason lists the per-check failures.
  - The happy path in dry-run → JPEGs + report exist, no `pending.json`.
  - With `publishing_enabled: true` and `dry_run=False` → `pending.json` exists. With `dry_run=True` → it doesn't, even when the flag is true.
- [ ] Step 2: `pytest tests/test_pipeline.py -v` → FAIL.
- [ ] Step 3: Implement. Max 3 facts; 1 fact → a single combined slide (headline + fact), 2–3 → hook + fact slides. `RateLimited` anywhere → status `skipped`, reason `rate limited`.
- [ ] Step 4: Full suite `pytest -q` → all PASS.
- [ ] Step 5: Commit `feat: end-to-end slot pipeline with dry-run and audit reports`.

### Task 8: Workflows, README, LIMITS

**Files:**
- Create: `.github/workflows/post.yml`, `.github/workflows/test.yml`, `README.md`, `LIMITS.md`

- [ ] Step 1: `test.yml`: on push/PR, Python 3.11, `pip install -r requirements.txt`, `pytest -q`.
- [ ] Step 2: `post.yml`.
  - Trigger: four `schedule` entries `cron: '7 9 * * *'` … with `timezone: "Asia/Kolkata"`, plus `workflow_dispatch` with an input `dry_run` (default true).
  - `concurrency: {group: post, cancel-in-progress: false}`; `permissions: contents: write, pages: write, id-token: write`; `environment: github-pages`.
  - Steps: checkout → Python → pip + `playwright install --with-deps chromium` → `refresh-token` (no-op if IG secrets absent) → `run` → upload `out/` as an artifact → if `out/pending.json` exists: `upload-pages-artifact` (path `out/site`) → `deploy-pages` → `publish` with `--base-url ${{ steps.deploy.outputs.page_url }}` → commit `data/ reports/` as github-actions[bot] with `git pull --rebase` and then push.
- [ ] Step 3: README with click-by-click steps.
  - Create the GitHub repo + push; Pages source = GitHub Actions.
  - Groq key; Pexels key.
  - Instagram professional account; Meta developer app → Instagram API setup with Instagram login → add the account as a tester → generate a token → IG user ID.
  - Fine-grained PAT (only this repo, Secrets: read & write, no expiry).
  - Add 5 secrets.
  - Run a dry-run manually; review reports; flip `publishing_enabled`.
  - The kill switch; reading failure emails.
- [ ] Step 4: `LIMITS.md`: every limit from spec §3 with "what breaks first".
- [ ] Step 5: Validate the YAML parses (`python -c "import yaml;yaml.safe_load(open(...))"`), then commit `docs: workflows, README, limits`.

### Task 9: Live verification (local)

- [ ] `pytest -q` → all pass.
- [ ] `python -m factpage candidates --no-llm` → real trends with kept/dropped reasons.
- [ ] `python -m factpage sample-render` → inspect JPEGs visually.
- [ ] Without `GROQ_API_KEY`/`PEXELS_API_KEY`, `python -m factpage run --dry-run` exits 0 with status `skipped` and reason "missing GROQ_API_KEY". The full LLM dry-run happens once the owner adds keys.
