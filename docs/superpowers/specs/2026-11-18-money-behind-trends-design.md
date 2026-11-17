# Design: "The money behind what's trending" — automated Instagram fact page

Date: 2026-11-18 · Status: draft, awaiting owner approval

## 1. Intent

Publish 3–4 Instagram posts a day, with no human in the loop. Each post takes a topic
trending right now and shows 1–3 short, surprising, **verified** facts about the money
or numbers behind it. The page is only worth anything if its facts are true, so
**posting nothing always beats posting something unverified**. Success means accurate,
sourced posts that look designed by a person. Volume is not the goal.

The owner is not a strong programmer. Every manual step (Meta app, tokens, GitHub
secrets) must be explained click by click in the README.

## 2. Goals / non-goals / anti-goals

Goals
- Fully automatic after a manual launch gate (≥20 dry-run posts reviewed by the owner).
- Every published claim traceable to verbatim quotes on two independent domains.
- $0/month, with the paid-able parts (LLM, image host, scheduler) swappable via config.
- An audit trail per post (markdown verification report + history log in the repo).

Non-goals (v1)
- Reels or animation. The renderer is structured so v2 can add them with ffmpeg.
- Engagement automation of any kind: no likes, follows, comments or DMs.
- Analytics or growth tooling.

Anti-goals (failure even if it "works")
- Any number on a post that the sources don't contain verbatim.
- Investment advice, predictions, price targets.
- Images that look AI-made, or images without a reuse licence.
- Sensitive topics slipping through (deaths, politics, crime, minors, and so on).
- The page silently dying (expired token, disabled workflow) without the owner being told.

## 3. Verified facts this design rests on (checked 2026-11-18)

| Item | Finding | Consequence |
|---|---|---|
| Google Trends RSS | `https://trends.google.com/trending/rss?geo=XX` works; old `/trends/trendingsearches/daily/rss` returns 404. robots.txt only disallows `/explore?`. Each item has `ht:news_item_url` links (real article URLs). | Primary trend source + first research URLs. |
| Wikipedia top pageviews | `wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia/all-access/YYYY/MM/DD` works; about 1-day lag; includes Main_Page, Special:*, Wikipedia:* and sensitive lists. | Second trend source; strict filters. |
| Google News RSS | `news.google.com/robots.txt`: `Disallow: /` for `*`, no `/rss` allow. | **Not used.** Replaced by publisher RSS feeds (§5.1). |
| Instagram App Review | Meta App Review table: "only for a business I own or manage" + Instagram Login + Standard Access → App Review **not required**. | App stays in Development mode; owner's account added as an Instagram tester. |
| Instagram limits | 100 API-published posts per 24h moving window (carousel = 1); JPEG only; carousel ≤20 items; container `status_code` polled at most once/min for ≤5 min; media is cURLed from a public URL. | Check `content_publishing_limit` before every publish. |
| IG tokens | Long-lived tokens last 60 days; refreshable when ≥24h old and not expired; expired = unrecoverable. | Automatic refresh, persisted to GitHub secrets (§5.8). |
| **Unverified** | Whether posts from a Development-mode app are publicly visible (Meta's generic App Modes page says dev-mode data is visible to role users only). Whether Meta can fetch from GitHub Pages. | One real test post in build step 4, decided by the owner before launch. |
| Groq free plan | `openai/gpt-oss-120b` and `qwen/qwen3.8-27b`: 30 RPM, 1,000 RPD, 8K TPM, 200K TPD each. No retention of inference data by default. | Extractor = gpt-oss-120b, verifier = qwen3.8-27b. Prompts must stay < ~6K tokens. |
| Gemini free tier | Per-model free limits no longer published (visible only in AI Studio); free-tier content is used to improve Google products and may be human-reviewed. | Not default. Reachable later through the same OpenAI-compatible client. |
| Unsplash API | Must hotlink Unsplash URLs for all uses; API is "for non-automated" experiences. | **Not used.** |
| Pixabay API | "made for real human requests; do not send lots of automated queries". | **Not used** (gray area). |
| Pexels API | 200 req/h, 20,000/month; show a link to Pexels + credit photographer. | Primary photo source. |
| Wikimedia | User-Agent must contain contact info (email, website or wiki user). | UA = `MoneyBehindTrends/<ver> (<repo URL>)`; repo URL is the contact, no email. |
| GitHub Actions | Free on standard runners for public repos; cron supports an IANA timezone; runs at :00 get delayed; scheduled workflows auto-disable after 60 days without repo activity. | Cron in `Asia/Kolkata` at :07 past; every run commits its log (counts as activity). |
| GitHub Actions terms | Hosted runners shouldn't be used for activity "unrelated to the production, testing, deployment, or publication of the software project". | **Gray area, accepted by owner.** Code stays portable (plain CLI). |
| GitHub Pages | Site ≤1 GB; 100 GB/month soft bandwidth; custom-Actions deploys are exempt from the 10 builds/hour limit. | Images deployed as a Pages artifact, never committed (no repo bloat). |
| Fine-grained PAT | Can be set with no expiration; "Secrets: write" lets the API update a repo secret (libsodium sealed box). | Used only to store the refreshed IG token. |

Items still to VERIFY at build time: the current Graph API version string for
`graph.instagram.com`, and robots.txt and paywall status of each candidate publisher feed.

## 4. Approaches considered

1. **Python CLI + GitHub Actions + Pages-artifact image hosting + Groq** *(chosen)*.
   Free, matches the spec, and every part is a plain HTTP call that can be swapped.
2. Commit the JPEGs to the repo and serve them from Pages/raw. Rejected: around 1 GB of
   images a year breaks the 1 GB Pages/repo guidance, and raw.githubusercontent
   behaviour for Meta's fetcher is unverified.
3. Free object storage (Cloudflare R2, Backblaze). Rejected for v1: signup needs a
   payment card or extra accounts. Kept possible behind the `ImageHost` interface.
4. Run on the owner's PC (Task Scheduler). Rejected: posts stop when the PC is off. It
   still works as a fallback because the CLI is host-agnostic.

## 5. Design

### 5.1 Trend collection (`factpage/trends.py`)
- **Google Trends RSS** for each geo in config (default `IN`, `US`). Keeps title, approx
  traffic and the `news_item_url`s.
- **Wikipedia top pageviews** for yesterday (UTC). Drops `Main_Page`, any title with
  a namespace prefix (`Special:`, `Wikipedia:`, `File:`, `Portal:`, `Talk:`…), `List_of_*`
  unless the business angle is explicit, and bot spikes: a page is treated as a bot
  spike when its views-to-rank ratio is extreme versus its 7-day history, **or** when
  mobile views are under 10% of desktop views (my call; a naive heuristic, marked
  `ponytail:` in code).
- **Publisher RSS feeds** (business sections) from an allowlist in config. At build time,
  each candidate feed is checked against robots.txt and paywall status; only passing
  feeds go in.
- Output: `Trend(title, source, geo, urls[], signal)`, merged by normalised title.
- CLI: `python -m factpage candidates` prints every candidate with KEPT/DROPPED and why.

### 5.2 Safety filter (`factpage/safety.py`)
Hard skip if **either** check flags the topic, or the classifier is unsure:
1. Keyword blocklist (config, case-insensitive, word-boundary). Covers deaths,
   accidents, disasters, violence, crime, terrorism, war, elections,
   politicians/parties, religion, communal/caste, health/medical, adult content, minors,
   court cases.
2. LLM classifier: one batched call per run returning `SAFE | UNSAFE | UNSURE` + reason
   per topic. Anything other than `SAFE` is dropped. A malformed response drops everything.

Private individuals: only topics that resolve to a Wikipedia article or an established
organisation are eligible. A person-topic is kept only if the LLM labels it a public
company, product, film, sports team or event. A person on their own is dropped.

### 5.3 Angle filter (`factpage/angle.py`)
- One LLM call scores each safe topic 0–10 for "clear business/money/numbers angle" and
  names the angle (budget vs box office, market share, media-rights value…).
- Choose the highest-scoring topic not used in the last 7 days (history). Ties go to the
  stronger trend signal.
- Fallback: when no topic scores ≥6, and only if no fallback post has been made today
  (history check), pick a general surprising-fact topic from a config list of evergreen
  safe topics.

### 5.4 Research (`factpage/research.py`)
- **Fetching rules:** every request sends the project User-Agent. robots.txt is checked
  with `urllib.robotparser` (cached per domain per run). Paywalled pages are skipped,
  detected by a config list of paywall domains + JSON-LD `isAccessibleForFree: false` +
  extracted text < 150 words.
- **Domain policy: allowlist-only** (my call; stricter than an allow+deny list). The
  allowlist holds wire services, official company/government/regulator domains and
  established outlets, grouped by type. The denylist is kept too, as a safety net. An
  unknown domain is rejected.
- **Sources gathered:** the Trends news URLs for the topic; the Wikipedia article (Action
  API plaintext extract + revision ID recorded); the Wikipedia article's external
  reference links filtered by the allowlist (good corroboration candidates); and
  matching items from the publisher RSS feeds.
- Main-text extraction: `trafilatura`. Each page is stored as
  `SourceDoc(url, domain, fetched_at, text, wiki_revid?)`.
- Prompt budget: pages are trimmed to the paragraphs around topic terms and numbers,
  to fit Groq's 8K TPM.

### 5.5 Extraction (`factpage/extract.py`)
The extractor LLM (gpt-oss-120b) receives one source's trimmed text and must return JSON
candidates `{claim, source_url, quote}`. The prompt forbids outside knowledge,
predictions and advice, and asks for a year in any time-sensitive claim
("as of 2025"). Claims are capped at 25 words.

### 5.6 Verification gate (`factpage/verify.py`): code first, LLM last
A claim becomes a `VerifiedFact` only if **all** checks pass:

| Check | How (code unless stated) |
|---|---|
| a. Quote is verbatim | Normalise (Unicode NFKC, lowercase, collapse whitespace, unify quotes/dashes, strip punctuation except digits' `.,`) then check substring in the source text. |
| b. Claim tokens ⊆ quote | Every **number** (parsed with units: %, $, ₹, €, £, crore, lakh, million, billion, bn, mn, k), every **date/year/month**, and every **proper noun** (capitalised tokens not at sentence start, plus known entity names) in the claim appears in the quote. Numbers compare by canonical value: "₹1,200 crore" == "1200 crore"; "1.2 billion" ≠ "1.3 billion". |
| c. Corroboration | **Every** claim (my call: stricter and simpler than "surprising ones only") needs a second `SourceDoc` on a different registrable domain (`tldextract` with a bundled suffix list) whose text contains all the claim's numbers (canonical) and proper nouns. Wikipedia can never be the corroborating source, and a Wikipedia-only claim never passes. |
| d. Independent LLM verifier | qwen3.8-27b, fresh context, sees only the claim + the two quoted excerpts (±300 chars). Must answer exactly `SUPPORTED`; `NOT_SUPPORTED`, `UNCLEAR` or malformed output → drop. |
| e. Dated, never "currently" | Reject claims containing banned time words (`currently, now, today, this year, latest, recently, so far`). Any claim containing a number must contain a 4-digit year or "as of <year>", and that year must pass (b). |
| f. Final text = verified text | Renderer and caption accept only `VerifiedFact` objects. Shortening creates a new claim string that re-runs a–d. Headline rule: the headline may contain only the topic name + fixed wording, with no numbers (checked in code), so it never needs fact-checking. |

On LLM rate limits: back off using `retry-after`, up to 3 tries, then **skip the slot**.
Checks are never loosened. If no fact passes, the slot is skipped and the reasons are logged.

Required unit tests (must pass before anything else ships):
- a claim whose number differs from the source by one digit → rejected;
- a quote not present in the page → rejected;
- a number supported only by Wikipedia → rejected.
Plus tests for number canonicalisation, proper-noun check, banned time words, and
domain dedupe.

### 5.7 Images and rendering (`factpage/images.py`, `factpage/render.py`)
- **Photo search:** Pexels first, then Wikimedia Commons (licence from `extmetadata`:
  only Public domain, CC0, CC BY x.x; never BY-SA/NC/ND). Search terms are the
  angle's object/place ("cinema hall", "stadium", "smartphone"), not the person.
- **No faces by default:** OpenCV Haar face detector rejects photos with a detected
  face (config flag `avoid_faces`). Logos can't be detected reliably for free;
  mitigation is object/place search terms + rejecting photos whose tags mention brand
  names (my call; known gap).
- Credit + licence + source URL recorded per image; CC BY images credited with
  "changes made: cropped, text overlaid".
- **No photo found** → plain brand-colour background (no credit needed) (my call;
  better than skipping a verified post or using an unlicensed photo).
- **Template:** one HTML/CSS template, 1080×1350, rendered by Playwright (Chromium) to
  PNG, then Pillow → baseline JPEG (quality 90, sRGB, no MPO).
  - Dark gradient overlay for legibility.
  - "TRENDING · <topic>" label bar in the accent colour.
  - Headline ≤8 words.
  - Fact ≤25 words; the key number drawn large as the visual anchor.
  - Footer: source names + @handle.
- Carousel: slide 1 = hook headline over the photo; slides 2–3 = one fact each.
  1 fact = single image.
- **Brand config:** headline font Archivo (OFL), body font Inter (OFL), both bundled in
  the repo; accent `#FFB020`; 72 px safe margins. All are my calls, changeable in config.
- **v2 hook:** `render_slide(data) -> png` is a pure function. A Reel later = render
  frames + ffmpeg, with no template changes.
- **Writing rules (code-checked):** banned phrases ("did you know", "fun fact",
  "mind-blowing", "you won't believe"…), 🤯, more than 1 emoji, `!!`.
- **Caption:**
  - context line from a fixed template ("<Topic> is trending in <country>.") so it carries no unverified facts;
  - the verified facts, each with its source names;
  - image credit;
  - 3–5 hashtags derived from the topic/angle words (sanitised: no numbers, no claims).

### 5.8 Publishing (`factpage/publish.py`)
- **Interfaces (the only abstractions):** `ImageHost.put(files) -> urls`
  (GitHubPagesHost), `Publisher.publish(urls, caption) -> media_id` (InstagramPublisher),
  `LLM.complete(role, prompt, schema)` (one OpenAI-compatible client: base_url + model
  + key from config/secrets. It covers Groq, Gemini's OpenAI-compatible endpoint and
  OpenRouter, with no SDKs).
- **Image hosting flow** (within one workflow run):
  1. build job renders the JPEGs;
  2. `actions/upload-pages-artifact` + `actions/deploy-pages`;
  3. publish job HEAD-checks each URL (200 + `image/jpeg`);
  4. publish.
  Images stay live until the next run's deploy. Instagram has its own copy by then.
- **Instagram flow:**
  1. `GET content_publishing_limit`, and abort if near the limit;
  2. create an item container per image (`is_carousel_item` when 2–3);
  3. poll `status_code` once/min for ≤5 min;
  4. carousel container;
  5. `media_publish`;
  6. record the media ID.
  Any error fails the run, so GitHub emails the owner.
- **Token refresh:** each run reads `data/state.json` → `token_refreshed_at`. If older than
  7 days, it calls `GET graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token`,
  writes the new token to the `IG_ACCESS_TOKEN` repo secret via the GitHub REST API
  (PyNaCl sealed box, fine-grained PAT `GH_SECRETS_PAT` with "Secrets: write" on this
  repo only, no expiry), and commits the new timestamp (not the token). A failed
  refresh fails the run, which sends an email, 53 days before the token would die.
- **Kill switch:** `publishing_enabled: false` in config by default. `--dry-run` forces it
  off. Publishing code refuses unless the flag is true **and** the run isn't a dry-run.

### 5.9 Logging and audit
- `data/history.jsonl` (committed every run, including skips): run ID, slot, timestamps,
  trend source, topic, candidates kept/dropped + reasons, facts, all source URLs + quotes +
  wiki revision IDs, verification results per check, image credit/licence, IG media ID.
- `reports/YYYY/MM/DD-<slot>-<slug>.md`: human-readable verification report per post or skip.
- Dry-run outputs (`out/<run>/` JPEGs + report) uploaded as an Actions artifact and the
  report committed, so the owner can review 20+ posts from the GitHub website.
- History dedupe:
  - topic: normalised title + Wikipedia page ID, within 7 days;
  - fact: normalised claim + its canonical number set, forever.

### 5.10 Infrastructure
- Python 3.11 (matches the owner's machine), public GitHub repo.
- Dependencies (each earns its place):
  - `requests`, `feedparser`, `trafilatura`, `tldextract`, `PyYAML`;
  - `playwright`, `Pillow`, `opencv-python-headless`;
  - `PyNaCl`;
  - `pytest` (dev).
- Workflow `post.yml`: `schedule` with `timezone: Asia/Kolkata`, cron at 09:07, 13:07,
  18:07, 21:07 (configurable), plus `workflow_dispatch` (manual run button).
  `concurrency: post` so runs never overlap.
- Workflow `test.yml`: runs pytest on every push.
- Secrets (GitHub Actions secrets only): `GROQ_API_KEY`, `PEXELS_API_KEY`,
  `IG_ACCESS_TOKEN`, `IG_USER_ID`, `GH_SECRETS_PAT`.
- `config.yaml` holds the slots, geos, feeds, allow/deny lists, paywall domains,
  blocklists, banned phrases, evergreen fallback topics, brand, LLM roles/models, and
  flags (`publishing_enabled`, `avoid_faces`).

## 6. Build order and launch gate (owner's, unchanged)
1. Trends + safety/angle filters + `candidates` CLI.
2. Research + extraction + verification gate + required tests.
3. Renderer + sample outputs.
4. Publishing + token refresh + logging. This step includes **one owner-approved real test
   post** to settle the two unverified items (dev-mode visibility, Pages fetch).
5. `--dry-run` end-to-end. Live publishing stays off until the owner has reviewed ≥20
   dry-run posts and flips `publishing_enabled`.

## 7. Deliverables
Repo, README (click-by-click setup for a non-programmer: Instagram professional account,
Meta developer app + Instagram tester + token, Groq key, Pexels key, fine-grained PAT,
GitHub secrets, Pages source = GitHub Actions, reviewing dry-runs, flipping the switch),
`config.yaml`, tests, and `LIMITS.md`: every free-tier limit relied on and what breaks
first if it changes.

## 8. Known ceilings / honest expectations
- The strict gate (verbatim quotes + a second non-Wikipedia domain with every number) will
  skip **many** slots. Some days may get 0–1 posts. That is by design.
- Bot-spike and face/logo detection are heuristics.
- The GitHub Actions terms gray area was accepted by the owner. The fallback is running
  the same CLI elsewhere.
- Groq's 8K TPM limits how much source text one call can see, which also limits how many
  facts are found.

## 9. Calls made by the designer (owner to check)
- Allowlist-only source domains.
- Corroboration required for every claim, not just surprising ones.
- Headline never contains numbers.
- Caption context line comes from a template.
- Brand-colour background when no licensed photo is found.
- Fonts Archivo + Inter; accent `#FFB020`; slots at :07 past.
- Token refreshed weekly.
- Images hosted via Pages artifact, not commits.
- One OpenAI-compatible LLM client.
- Bot-spike heuristic.

## 10. Needed from the owner before build step 4
Instagram handle (footer), GitHub username + repo name (User-Agent contact URL, Pages URL).
