# Free-tier limits this system depends on

Checked against official docs on 2026-11-18. Free tiers change, so re-check yearly.

| Service | Limit (free) | What we use | If it changes |
|---|---|---|---|
| **Groq** `openai/gpt-oss-120b` (angle + extraction) | 30 req/min, 1,000 req/day, **8,000 tokens/min**, **200,000 tokens/day** | ~1 angle call + ≤8 extraction calls per slot (each ≤~4.5K tokens) → ≤~150K tokens/day | **Most likely to bite first.** Token limits make runs slower (we wait and retry). If the daily cap is hit, slots are skipped, never loosened. Fix: lower `trim` size, fewer feeds, or swap provider in `config.yaml → llm`. |
| **Groq** `qwen/qwen3.8-27b` (safety + verifier) | same as above, **plus only 1,000 output tokens/minute** (found in a live test; not in the docs table) | ≤3 safety calls (reasoning off) + ≤~10 verifier calls per slot | Runs pause and retry when limited, so a slot can take 5–10 minutes. Hidden "reasoning" tokens count as output, so reasoning is set low or off in `config.yaml`. |
| **Google Trends "Trending Now" RSS** `trends.google.com/trending/rss?geo=XX` | No published limit or guarantee. It's a public feed, not an API. | 2 requests per slot | **Second most likely.** Google moved this feed once already (the old `/trends/trendingsearches/daily/rss` is 404). If it changes, trends come only from Wikipedia + news feeds. If everything fails for 3 days, the watchdog emails you. |
| **Wikimedia APIs** (pageviews, Wikipedia, Commons) | No fixed quota. Requires a User-Agent with contact info; we send `maxlag=5` | ~4–6 requests per slot | Requests without a proper User-Agent get blocked. Ours is set in `config.yaml → user_agent`. |
| **Publisher RSS feeds** (BBC, The Hindu, Mint, ET, CNBC, Guardian…) | None published | 12 requests per slot | A feed that moves or blocks bots just returns nothing. Re-check `robots.txt` before adding new feeds. |
| **Pexels API** | 200 req/hour, 20,000 req/month; must credit Pexels + photographer. **New keys paused as of Nov 2026** | Optional; not used without a key | Wikimedia Commons is used instead; if it has no suitable photo, a plain brand background. |
| **Instagram Content Publishing API** | 100 API posts per 24 h (one doc page says 50; we read the live number via `content_publishing_limit`) | ≤4/day | Way under. Checked before every publish. |
| **Instagram long-lived token** | Valid 60 days; refreshable once ≥24 h old; **dead if it expires** | Refreshed every 7 days | A failed refresh fails the run → email. You have ~8 weeks of warnings before it dies. |
| **Meta App Review** | Not required for an app used only on an account you own (Standard Access). Meta's create-app guide has a conflicting general line. | Development mode | Settled by the first live post (README step 11). If Meta tightens this, publishing fails with a permissions error → email. |
| **GitHub Actions** (public repo) | Standard runners free and unlimited; cron can run late, especially at :00; scheduled workflows **auto-disable after 60 days without repo activity** | 4 runs/day, ~5–10 min each | Every run commits its log, which counts as activity. Terms gray area: Actions shouldn't be used for activity "unrelated to the production, testing, deployment, or publication of the software project". If GitHub objects, the same `python -m factpage run` works on any computer or server. |
| **GitHub Pages** | Site ≤1 GB, 100 GB/month bandwidth (soft) | Only the latest post's 1–3 JPEGs (~1 MB) | Images are deployed, not committed, so the repo never bloats. |
| **GitHub fine-grained token** (`GH_SECRETS_PAT`) | Can be set to never expire; GitHub deletes tokens unused for a year | Used weekly | If you set an expiry, it stops saving refreshed Instagram tokens when it expires. |

## What breaks first, in order of likelihood

1. **Groq free-tier cuts.** Slots get skipped more often, and the 3-day watchdog emails you. Swap to
   another OpenAI-compatible provider in `config.yaml → llm`; no code change is needed.
2. **Google Trends RSS changes.** Fewer topics. Wikipedia and the news feeds keep it going.
3. **Meta token or App Review policy.** Publishing fails loudly by email, never silently.
4. **GitHub Actions terms enforcement.** Move the same command to another scheduler.
