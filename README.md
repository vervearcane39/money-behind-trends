# Money Behind Trends

An automatic Instagram page. Four times a day it picks a topic that is trending right now. It finds
1–3 facts about the money or numbers behind the topic and **checks every fact word-for-word against an
established news source** (never Wikipedia alone). Then it designs the post and publishes it through
Instagram's official API.

If no fact passes every check, it posts nothing and writes down why. That is on purpose: the page is
only worth anything if every fact is true.

```
Google Trends + Wikipedia + business news feeds
        │
        ▼
 safety filter (word blocklist AND an AI check) ─► skip anything sensitive
        │
        ▼
 pick the topic with the clearest money angle (never the same topic within 7 days)
        │
        ▼
 read allowlisted sources ─► AI copies out candidate facts with exact quotes
        │
        ▼
 VERIFICATION GATE (all must pass)
   a. quote appears word-for-word on the page          (code)
   b. every number, name, date in the fact is in quote  (code)
   e. dated ("in 2024"), never "currently"              (code)
      no predictions / advice, ≤25 words                (code)
   c. the source is an allowlisted news site; Wikipedia alone   (code)
      is never enough. A second site is optional:
      `require_second_source` in config.yaml
   d. a separate AI model says SUPPORTED                (AI)
        │
        ▼
 licensed photo (Pexels / Wikimedia Commons) ─► 1080×1350 image(s) ─► Instagram
        │
        ▼
 history log + a verification report for every post or skip (in this repo)
```

**Cost: $0/month.** Every service used is on a free tier. See [LIMITS.md](LIMITS.md) for each limit and
what breaks first if one changes.

---

## Setup (about 45 minutes, once)

You will collect four secret values (five if you have a Pexels key) and paste them into GitHub. Keep a text file open while you go,
and delete it at the end.

### 1. Put this code on GitHub

1. Go to <https://github.com/new>.
2. Repository name: `money-behind-trends`. Choose **Public** (GitHub Actions minutes are free and
   unlimited only for public repos). Don't tick any "Add a README" boxes.
3. Click **Create repository**.
4. Upload this folder's contents to it. If you're using Claude, ask it to "push this project to
   github.com/vervearcane39/money-behind-trends".

> Public means anyone can read the code, the logs and the verification reports. **No secret ever goes
> in the code.** Secrets live only in GitHub's encrypted "Actions secrets" (step 8).

### 2. Turn on GitHub Pages (this hosts the images Instagram downloads)

1. In your repo, click **Settings** (top bar).
2. Left menu: **Pages**.
3. Under **Build and deployment → Source**, choose **GitHub Actions**.

### 3. Get a free Groq AI key → secret `GROQ_API_KEY`

1. Go to <https://console.groq.com> and sign in (Google login is fine).
2. Left menu: **API Keys** → **Create API Key** → name it `money-behind-trends` → **Submit**.
3. Copy the key (it starts with `gsk_`). Groq shows it only once.

### 4. (Optional) Pexels photo key → secret `PEXELS_API_KEY`

**You can skip this step.** As of November 2026, Pexels has paused new API keys. Without a Pexels key the
system uses photos from Wikimedia Commons (public domain, CC0 or CC BY only). If no suitable photo is found,
it uses a plain background in the brand colour.

If Pexels starts issuing keys again:
1. Go to <https://www.pexels.com/api/> and click **Your API Key**.
2. Fill in the short form (description: "Automated Instagram page that credits Pexels photographers").
3. Copy the key and add it as a secret in step 8.

### 5. Make your Instagram account a professional account

1. In the Instagram app: **Profile → ☰ menu → Settings and activity → Account type and tools →
   Switch to professional account**.
2. Choose **Creator** or **Business** (either works).
3. Make sure the account is **public** (Meta requires it).

### 6. Create the Meta developer app and get your token → secrets `IG_ACCESS_TOKEN` and `IG_USER_ID`

1. Go to <https://developers.facebook.com/apps> and log in with Facebook. Register as a developer if
   asked (it's free).
2. Click **Create app**.
3. **Connect a business**: choose the option to skip / not connect one for now.
4. **Use case**: select **Other** → **Next**.
5. **App type**: select **Business** → **Next**.
6. **App name**: `Money Behind Trends`. **Contact email**: yours → **Create app**.
7. On the app dashboard, scroll to **Instagram** → **Set up**. "API setup with Instagram login" is
   added automatically.
8. Left menu: **Instagram → API setup with Instagram login**.
9. Under **Generate access tokens**, click **Add account** and log in with your Instagram account. If
   asked, accept the tester invite. In the Instagram app it's under
   **Settings → Apps and websites → Tester invites**.
10. Click **Generate token** next to your account, log in again if asked, and copy the token. This is
    `IG_ACCESS_TOKEN`. Tokens from the dashboard last 60 days, and the system refreshes them for you
    every week.
11. Get your Instagram user ID. Paste this into your browser, replacing `YOUR_TOKEN`:
    `https://graph.instagram.com/v27.0/me?fields=user_id,username&access_token=YOUR_TOKEN`
    Copy the number after `"user_id"`. That's `IG_USER_ID`. Close the tab afterwards, and never share
    that URL, because it contains your token.

**Leave the app in Development mode, and don't submit App Review.** Meta's App Review table says an app
used only for an Instagram account you own needs Standard Access and **no App Review**. Meta's
create-app guide has a general line saying App Review is needed for "live data". The first real post
(step 11 below) settles which applies to you, before anything runs on its own.

### 7. Create a GitHub token so the system can save refreshed Instagram tokens → secret `GH_SECRETS_PAT`

1. Go to <https://github.com/settings/personal-access-tokens/new>.
2. **Token name**: `money-behind-trends secrets`.
3. **Expiration**: **No expiration**. If it expires, the Instagram token can't be saved and will die
   within 60 days.
4. **Repository access**: **Only select repositories** → pick `money-behind-trends`.
5. **Permissions → Repository permissions → Secrets**: **Read and write**. Leave everything else as
   "No access".
6. Click **Generate token** and copy it.

### 8. Add the five secrets to GitHub

In your repo: **Settings → Secrets and variables → Actions → New repository secret**. Add each one
(the name must match exactly):

| Name | Value |
|---|---|
| `GROQ_API_KEY` | from step 3 |
| `PEXELS_API_KEY` | from step 4 (optional; leave it out if you have no key) |
| `IG_ACCESS_TOKEN` | from step 6.10 |
| `IG_USER_ID` | from step 6.11 |
| `GH_SECRETS_PAT` | from step 7 |

Now delete your temporary text file.

### 9. Set your handle

1. In your repo, open `config.yaml` → click the ✏️ pencil.
2. Set `handle: "@yourhandle"` (with your real handle).
3. Click **Commit changes**.

### 10. First dry run (nothing is posted)

1. Repo → **Actions** tab. If asked, click **I understand my workflows, go ahead and enable them**.
2. Left list: **post** → **Run workflow** → keep **Dry run** ticked → **Run workflow**.
3. Wait 3–10 minutes, then click the run:
   - Scroll to **Artifacts** → download `run-…` to see the images it made.
   - The `reports/` folder in your repo now has a report: the topic, every fact it tried, and exactly
     which check each one passed or failed.

From now on it also runs on its own four times a day (09:07, 13:07, 18:07, 21:07 India time), still
in dry-run mode.

### 11. Review at least 20 dry-run posts, then go live

1. Read at least 20 reports in `reports/` and look at their images (from each run's **Artifacts**).
   Check that every fact is true, sourced and well written. If anything is wrong, stop and fix it before
   going live.
2. When you're satisfied, open `config.yaml` and set `publishing_enabled: true`, then commit.
3. Do one manual live run: **Actions → post → Run workflow**, **untick Dry run** → **Run workflow**.
4. Open your Instagram profile **in a private/incognito browser window, not logged in**:
   - **You can see the post** → you're live. From now on it runs fully automatically.
   - **You can't see it, or the run failed with a permissions error** → Meta wants App Review for your
     app after all. Set `publishing_enabled: false` again and ask for help with the App Review
     submission.

---

## Day to day

- **Kill switch:** set `publishing_enabled: false` in `config.yaml`. To stop everything, go to
  **Actions → post → ••• → Disable workflow**.
- **You'll get an email** when a run fails. GitHub sends these by default to whoever last edited
  `.github/workflows/post.yml`; check **github.com/settings/notifications → Actions**. A run fails when:
  - a key is missing or rejected;
  - the token refresh fails;
  - publishing fails;
  - **12 slots in a row (3 days) were all skipped**.
- **A skipped slot is normal.** The checks are strict, so some days get 0–1 posts.
- **Audit any post:** each report in `reports/` lists the claim, both source URLs, the exact quotes,
  and every check's result. Wikipedia sources are pinned to the exact revision read.
- **Change posting times:** edit both `slots` in `config.yaml` and the four `cron:` lines in
  `.github/workflows/post.yml`.
- **Change design:** the `brand:` section of `config.yaml` (accent colour, fonts, headline templates).
- **Change sources:** `feeds:` and `sources:` in `config.yaml`. Only domains listed under
  `sources.allow` are ever read.

## Running it on your own computer (optional)

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m playwright install chromium
.venv\Scripts\python -m factpage candidates --no-llm
.venv\Scripts\python -m factpage sample-render
.venv\Scripts\python -m pytest -q
```

Commands:
- `candidates --no-llm` lists today's trends and which ones the blocklist drops.
- `sample-render` writes layout samples to `samples/`.
- `run --dry-run` runs a full slot. It needs `GROQ_API_KEY` and `PEXELS_API_KEY` set in your terminal.

## What it will never do

- Like, follow, comment, DM, or use unofficial Instagram tools.
- Give investment advice, predictions or price targets.
- Use AI-generated images, news photos, or images without a reuse licence.
- Read pages blocked by `robots.txt`, paywalled pages, or sites outside the allowlist.
- Publish a number that only Wikipedia supports.

## Licences

- Fonts: Inter and Archivo, SIL Open Font License (`factpage/fonts/*-OFL.txt`).
- Photos: credited in each caption under each provider's terms.
