# Cloudflare Worker — instant Telegram responses

This Worker makes Telegram commands and approvals fire within ~1–2 seconds instead of waiting for the hourly GitHub Actions cron. It's free (Cloudflare Workers free tier = 100k requests/day — you'll use ~50).

## How it fits

```
Telegram ── webhook ──▶ Cloudflare Worker ──▶ GitHub Actions (process_update.yml) ──▶ X API
                          │
                          └── instant reply for help/about/run ack
```

The Worker handles instant replies itself and delegates anything that needs repo state (approvals, edits, status) to a GitHub Actions workflow that runs in ~30s.

## One-time setup (no CLI needed — all dashboard)

### 1. Create the Worker

1. Sign in at https://dash.cloudflare.com (free account is fine).
2. Left sidebar → **Workers & Pages** → **Create application** → **Create Worker**.
3. Name it something like `xbot-webhook` → **Deploy**.
4. After deploy, click **Edit code**. Delete the default code, paste the contents of [`worker.js`](worker.js), click **Deploy**.
5. Copy the Worker URL from the dashboard header — looks like `https://xbot-webhook.<your-subdomain>.workers.dev`. Save it.

### 2. Add Worker secrets

In the Worker's dashboard → **Settings** → **Variables and Secrets** → **Add**:

| Name | Type | Value |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Secret | Same value as your GitHub `TELEGRAM_BOT_TOKEN` secret |
| `TELEGRAM_CHAT_ID` | Secret | `1778316288` (or whatever your personal chat id is) |
| `TELEGRAM_WEBHOOK_SECRET` | Secret | A random long string you invent. e.g. run `openssl rand -hex 32` or just mash keys — 40+ chars |
| `GH_TOKEN` | Secret | Same fine-grained PAT you saved as `GH_WORKFLOW_TOKEN` in GitHub, with Actions read/write |
| `GH_REPO` | Plaintext | `jeffrizkallah/Xbot` |

Redeploy (the dashboard may ask you to).

### 3. Register the webhook with Telegram

Run this in your terminal — replace the two placeholders:

```bash
BOT_TOKEN="<your telegram bot token>"
WORKER_URL="https://xbot-webhook.<your-subdomain>.workers.dev"
WEBHOOK_SECRET="<the random string from step 2>"

curl -X POST "https://api.telegram.org/bot${BOT_TOKEN}/setWebhook" \
  -H "Content-Type: application/json" \
  -d "{
    \"url\": \"${WORKER_URL}\",
    \"secret_token\": \"${WEBHOOK_SECRET}\",
    \"allowed_updates\": [\"message\", \"callback_query\"],
    \"drop_pending_updates\": true
  }"
```

You should get `{"ok":true,"result":true,"description":"Webhook was set"}`.

Verify it:

```bash
curl "https://api.telegram.org/bot${BOT_TOKEN}/getWebhookInfo"
```

Should show `url` = your Worker URL, `has_custom_certificate: false`, pending updates = 0.

### 4. Test it

On your phone, message the bot:

- `help` → instant reply with command list
- `what's your job?` → instant showcase reply
- `run` → instant "🚀 dispatched" reply, then drafts arrive ~60s later
- `status` → takes ~30s (needs repo state), then shows counts

Tap ✅ on a draft → tweet goes live in ~30–60s. Confirmation message from the bot follows.

## Turning it off

Remove the webhook (reverts to hourly-cron polling):

```bash
curl "https://api.telegram.org/bot${BOT_TOKEN}/deleteWebhook"
```

## Troubleshooting

- **Worker logs**: Cloudflare dashboard → your Worker → **Logs** → **Begin log stream**. You'll see every Telegram update hit the Worker in real time.
- **GitHub Actions logs**: https://github.com/jeffrizkallah/Xbot/actions → each run shows what happened.
- **Webhook not firing**: `getWebhookInfo` shows `last_error_message` if Telegram can't reach the Worker. Usually wrong secret or wrong URL.
- **Commands ignored**: The Worker checks `TELEGRAM_CHAT_ID` — only you can trigger it. Messages from other chats are silently dropped. If you're testing from a group, set `TELEGRAM_CHAT_ID` to that chat's id instead.
