/**
 * Telegram webhook → GitHub Actions dispatch.
 *
 * Telegram POSTs every update here. For commands that need state
 * (status, approvals, edits, "run") we dispatch a GitHub Actions
 * workflow. For pure text responses (help, about) we reply inline —
 * zero perceived latency.
 *
 * Required secrets (set in Worker dashboard → Settings → Variables):
 *   TELEGRAM_BOT_TOKEN       — from @BotFather
 *   TELEGRAM_CHAT_ID         — the owner's numeric chat id
 *   TELEGRAM_WEBHOOK_SECRET  — random string used to verify requests
 *   GH_TOKEN                 — PAT with Actions: read/write on the repo
 *   GH_REPO                  — e.g. "jeffrizkallah/Xbot"
 */

const ABOUT_TEXT = [
  "🤖 *My job*",
  "",
  "I'm an autonomous Twitter agent running on GitHub Actions — no server, no manual intervention. I post to *@jeffrizkala*.",
  "",
  "*Every morning (09:00 ET):*",
  "• Scrape ~200+ articles from Reuters, AP, Politico, The Hill, WaPo, Bloomberg, CNBC, MarketWatch, SeekingAlpha, and Google News",
  "• Rank by recency × source authority × headline specificity",
  "• Dedupe near-duplicate stories across sources",
  "• Draft tweets with *Claude Opus 4.7* in my operator's voice (US politics + stocks/trading niches)",
  "• Send the top 10 drafts here for approval",
  "",
  "*When you tap ✅ Approve:*",
  "• The tweet is queued and auto-posted to X via the API",
  "• Daily cap: 10 tweets, 30-min minimum spacing between posts",
  "• Unapproved drafts expire after 12 hours",
  "",
  "*Also:*",
  "• Tap ✏️ to edit a draft in place before approving",
  "• Tap ❌ to reject",
  "• Type `run` to trigger me on-demand",
  "",
  "*Stack:* Claude Opus 4.7 + Twitter API v2 + Telegram Bot API + GitHub Actions cron + Cloudflare Workers webhook.",
].join("\n");

const HELP_TEXT = [
  "🤖 *Commands*",
  "`run` — scrape news and generate new drafts now",
  "`status` — show pending / approved / posted counts",
  "`job` — describe what I do (or ask: \"what's your job?\")",
  "`help` — show this message",
].join("\n");

const ABOUT_TRIGGERS = [
  "what's your job",
  "whats your job",
  "what is your job",
  "your job",
  "what do you do",
  "who are you",
  "what are you",
  "about you",
  "about yourself",
  "tell me about yourself",
  "what can you do",
];

async function tg(env, method, body) {
  const url = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`;
  const resp = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    console.log(`Telegram ${method} failed:`, resp.status, await resp.text());
  }
  return resp;
}

async function sendMessage(env, chatId, text, replyTo) {
  const body = {
    chat_id: chatId,
    text,
    parse_mode: "Markdown",
    disable_web_page_preview: true,
  };
  if (replyTo) body.reply_to_message_id = replyTo;
  return tg(env, "sendMessage", body);
}

async function dispatchWorkflow(env, file, inputs = {}) {
  const url = `https://api.github.com/repos/${env.GH_REPO}/actions/workflows/${file}/dispatches`;
  const resp = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GH_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "xbot-webhook",
    },
    body: JSON.stringify({ ref: "main", inputs }),
  });
  if (resp.status !== 204) {
    console.log(`workflow dispatch ${file} failed:`, resp.status, await resp.text());
    return false;
  }
  return true;
}

function detectCommand(text) {
  const stripped = text.replace(/^\/+/, "").split("@")[0].trim().replace(/[?.!]+$/, "");
  if (["run", "status", "help", "start"].includes(stripped)) return stripped;
  if (["job", "about"].includes(stripped)) return "about";
  const normalized = text.replace(/[?.!]+$/, "").trim();
  for (const trigger of ABOUT_TRIGGERS) {
    if (normalized.includes(trigger)) return "about";
  }
  return null;
}

async function handleUpdate(update, env) {
  // Button taps
  if (update.callback_query) {
    const cb = update.callback_query;
    // Ack instantly to remove spinner
    await tg(env, "answerCallbackQuery", {
      callback_query_id: cb.id,
      text: "Processing…",
    });
    await dispatchWorkflow(env, "process_update.yml", {
      update_json: JSON.stringify(update),
    });
    return;
  }

  if (!update.message) return;

  const msg = update.message;
  const chatId = msg.chat && msg.chat.id;
  if (String(chatId) !== String(env.TELEGRAM_CHAT_ID)) {
    // Ignore strangers
    return;
  }

  // Reply to a draft = edit
  if (msg.reply_to_message) {
    await dispatchWorkflow(env, "process_update.yml", {
      update_json: JSON.stringify(update),
    });
    return;
  }

  const text = (msg.text || "").toLowerCase().trim();
  const cmd = detectCommand(text);

  if (cmd === "help" || cmd === "start") {
    await sendMessage(env, chatId, HELP_TEXT, msg.message_id);
    return;
  }
  if (cmd === "about") {
    await sendMessage(env, chatId, ABOUT_TEXT, msg.message_id);
    return;
  }
  if (cmd === "status") {
    // Status needs live state — dispatch workflow
    await dispatchWorkflow(env, "process_update.yml", {
      update_json: JSON.stringify(update),
    });
    return;
  }
  if (cmd === "run") {
    await sendMessage(
      env,
      chatId,
      "🚀 Morning workflow dispatched. New drafts in ~60s.",
      msg.message_id
    );
    await dispatchWorkflow(env, "morning.yml", {});
    return;
  }
  // Unknown message — silent
}

export default {
  async fetch(req, env) {
    if (req.method !== "POST") return new Response("ok");

    // Verify the secret header Telegram sends with every update
    const secret = req.headers.get("X-Telegram-Bot-Api-Secret-Token");
    if (!env.TELEGRAM_WEBHOOK_SECRET || secret !== env.TELEGRAM_WEBHOOK_SECRET) {
      return new Response("forbidden", { status: 403 });
    }

    let update;
    try {
      update = await req.json();
    } catch (e) {
      return new Response("bad json", { status: 400 });
    }

    // Respond 200 fast; let work continue in background.
    // @ts-ignore — waitUntil is available on the execution context
    try {
      await handleUpdate(update, env);
    } catch (e) {
      console.log("handler error:", e && e.stack ? e.stack : String(e));
    }
    return new Response("ok");
  },
};
