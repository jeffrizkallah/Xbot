# Twitter Agent

Daily pipeline: scrapes political + stocks/trading news, drafts tweets in your tone with Claude Opus 4.7, sends drafts to Telegram for one-tap approval, posts approved tweets to X.

Runs free on GitHub Actions cron. No server required.

## How it works

```
┌──────────────────────┐   ┌──────────────┐   ┌──────────────┐   ┌─────────────┐
│  Morning workflow    │   │ You, on phone │   │   Hourly     │   │     X       │
│ (once/day, 13:00 UTC)│──▶│  Telegram     │──▶│  workflow    │──▶│  (tweets)   │
│  scrape→rank→draft   │   │ ✅/✏️/❌      │   │ posts approved│   │             │
└──────────────────────┘   └──────────────┘   └──────────────┘   └─────────────┘
```

1. **Morning job** (daily cron): scrape RSS + Google News for politics & trading, rank by recency/authority/specificity, dedupe, generate N tweet drafts with Claude Opus 4.7, push each to Telegram with Approve/Edit/Reject buttons.
2. **Hourly job**: poll Telegram for button taps, apply edits, post approved drafts to X (respecting daily cap + spacing), expire stale drafts.
3. **State** lives as JSONL files in `state/` committed back to the repo by the workflow — easy to audit.

## One-time setup

### 1. Create accounts / tokens

**Anthropic API key**
- https://console.anthropic.com → API keys → Create. Load at least a few dollars of credit.

**Telegram bot + chat id**
- Open Telegram, message `@BotFather`, run `/newbot`, pick a name. Save the token.
- Message `@userinfobot` — it replies with your numeric user id. That's your `TELEGRAM_CHAT_ID`.
- Send any message to your new bot first so it's allowed to DM you.

**X / Twitter developer app**
- https://developer.twitter.com (Basic tier — you said you have it).
- Create a Project + App. Under the app's User Authentication settings:
  - App permissions: **Read and write**
  - Type: **Web App, Automated App, or Bot**
  - Callback URL: `http://localhost` (unused but required)
- Generate: API Key, API Secret, Access Token, Access Token Secret, Bearer Token.
- ⚠️ Regenerate Access Token/Secret *after* changing permissions to read-write, otherwise posts will 403.

### 2. Push this folder to a private GitHub repo

```bash
cd "c:/Locally Stored Cursor Projects/Twiiter Agent"
git init
git add .
git commit -m "initial"
# Create a PRIVATE repo on github.com first, then:
git remote add origin git@github.com:YOUR_USERNAME/twitter-agent.git
git branch -M main
git push -u origin main
```

### 3. Add secrets in the repo

`Settings → Secrets and variables → Actions → New repository secret`. Add all of:

- `ANTHROPIC_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TWITTER_API_KEY`
- `TWITTER_API_SECRET`
- `TWITTER_ACCESS_TOKEN`
- `TWITTER_ACCESS_TOKEN_SECRET`
- `TWITTER_BEARER_TOKEN`

(Optional) Variable `ENABLE_X_SEARCH = true` to enable X recent-search signals for trading.

### 4. Test it

In the repo, `Actions → Morning drafts → Run workflow`. In a minute or two you should get Telegram messages. Tap ✅. Then `Actions → Hourly approval + post → Run workflow` — your tweet goes live.

If nothing arrives on Telegram, check the Actions run logs for errors.

## Daily use

- Morning: drafts arrive on Telegram.
- For each draft: **✅ Approve** / **✏️ Edit** (bot asks you to reply with new text) / **❌ Reject**.
- Approved tweets auto-post within the next hour (one per hourly run, spaced per config).
- Unapproved drafts expire after 12h (configurable in `config.yaml`).

## Adding your tone

See [tone_samples/README.md](tone_samples/README.md). Just drop `.txt` files in `tone_samples/`, commit, push. Next morning run will mimic your voice.

## Tuning

Edit `config.yaml`:
- `generation.drafts_per_run` — total drafts/day
- `niches.<name>.drafts` — per-niche draft count
- `niches.<name>.rss` / `google_news_queries` — sources
- `ranking.recency_half_life_hours` — how aggressively to decay old news
- `posting.daily_cap`, `min_spacing_minutes` — posting cadence
- `telegram.approval_ttl_minutes` — how long drafts live before expiring

## Local dev / testing

```bash
cp .env.example .env
# fill in the values
pip install -r requirements.txt
python morning_job.py   # scrape + draft + send to Telegram
python hourly_job.py    # process approvals + post
```

On Windows PowerShell, load `.env` with a helper or just `$env:ANTHROPIC_API_KEY = "..."` before running.

## Project layout

```
twitter_agent/
├── .github/workflows/     # morning.yml + hourly.yml cron jobs
├── src/
│   ├── scrape/            # RSS, Google News, X search
│   ├── config.py          # YAML + env loading
│   ├── db.py              # JSONL state store
│   ├── rank.py            # recency × authority × specificity
│   ├── generate.py        # Claude Opus 4.7 + tone samples
│   ├── telegram_bot.py    # send drafts, handle buttons + edits
│   ├── poster.py          # Twitter API v2 posting
│   └── pipeline.py        # orchestration
├── tone_samples/          # drop your tweets here
├── state/                 # committed state — drafts.jsonl, etc.
├── config.yaml            # niches, sources, limits
├── morning_job.py         # entry: scrape + draft
├── hourly_job.py          # entry: approve + post
└── requirements.txt
```

## Cost estimate

- Claude Opus 4.7: ~$0.50–1.50/day at 10 drafts (prompt caching keeps system+tone blocks cheap after the first draft).
- GitHub Actions: free (well under the 2000 min/mo private-repo quota).
- Twitter API Basic: $100/mo (your existing cost).

## Troubleshooting

- **Telegram buttons don't do anything**: the hourly workflow runs at :05 past each hour. Expect up to ~60min latency between tapping and posting. For instant: add a Cloudflare Workers webhook (not included — ping me if you want that upgrade).
- **State conflicts in git**: the `concurrency` group prevents simultaneous runs, but if you push manual edits while a workflow is running, rebase. State is just JSONL — safe to hand-edit.
- **Tweets look bland**: add more `tone_samples/*.txt`. 20 samples is the floor, 100+ is better.
