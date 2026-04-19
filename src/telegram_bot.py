"""Telegram integration for draft approval.

Flow:
1. `send_draft(draft)` posts the draft text to the user's chat with three
   inline buttons: Approve / Edit / Reject. The callback_data encodes the
   draft id so we can look it up when the user taps.
2. `process_updates()` polls getUpdates, handles button taps, and detects
   plain text replies to a draft message as edits.

We use long polling getUpdates — no webhook, no always-on server. Runs
inside the GitHub Actions hourly job.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import requests

from . import db
from .config import env, load_config
from .github_dispatch import trigger_workflow

log = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"

CB_APPROVE = "a"
CB_REJECT = "r"
CB_EDIT = "e"


def _token() -> str:
    return env("TELEGRAM_BOT_TOKEN", required=True)


def _chat_id() -> str:
    return env("TELEGRAM_CHAT_ID", required=True)


def _api(method: str, payload: dict | None = None, timeout: int = 30) -> dict:
    url = f"{API_BASE}/bot{_token()}/{method}"
    resp = requests.post(url, json=payload or {}, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error in {method}: {data}")
    return data


def _keyboard(draft_id: str) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Approve", "callback_data": f"{CB_APPROVE}:{draft_id}"},
                {"text": "✏️ Edit", "callback_data": f"{CB_EDIT}:{draft_id}"},
                {"text": "❌ Reject", "callback_data": f"{CB_REJECT}:{draft_id}"},
            ]
        ]
    }


def _format_draft(draft: db.Draft) -> str:
    niche_emoji = {"politics": "🏛", "trading": "📈"}.get(draft.niche, "📰")
    return (
        f"{niche_emoji} *{draft.niche.upper()}* draft\n"
        f"_Source:_ {draft.article_title}\n"
        f"_Link:_ {draft.article_url}\n\n"
        f"```\n{draft.text}\n```\n"
        f"`{len(draft.text)}/280 chars`"
    )


def send_draft(draft: db.Draft) -> None:
    data = _api(
        "sendMessage",
        {
            "chat_id": _chat_id(),
            "text": _format_draft(draft),
            "parse_mode": "Markdown",
            "reply_markup": _keyboard(draft.id),
            "disable_web_page_preview": True,
        },
    )
    draft.telegram_message_id = data["result"]["message_id"]
    db.upsert_draft(draft)
    log.info("Sent draft %s to Telegram (msg_id=%s)", draft.id, draft.telegram_message_id)


def _answer_callback(callback_query_id: str, text: str) -> None:
    try:
        _api("answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text})
    except Exception as e:
        log.warning("answerCallbackQuery failed: %s", e)


def _edit_message(chat_id: Any, message_id: int, text: str, keep_keyboard: bool = False) -> None:
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    if not keep_keyboard:
        payload["reply_markup"] = {"inline_keyboard": []}
    try:
        _api("editMessageText", payload)
    except Exception as e:
        log.warning("editMessageText failed (msg %s): %s", message_id, e)


def _reply(chat_id: Any, message_id: int, text: str) -> None:
    _api(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text,
            "reply_to_message_id": message_id,
            "parse_mode": "Markdown",
        },
    )


def _find_draft_by_message(message_id: int) -> db.Draft | None:
    for d in db.load_drafts():
        if d.telegram_message_id == message_id:
            return d
    return None


def _handle_callback(cb: dict) -> None:
    data = cb.get("data") or ""
    cb_id = cb["id"]
    msg = cb.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    message_id = msg.get("message_id")

    if ":" not in data:
        _answer_callback(cb_id, "Unknown action")
        return
    action, draft_id = data.split(":", 1)
    draft = db.get_draft(draft_id)
    if not draft:
        _answer_callback(cb_id, "Draft not found")
        return

    if action == CB_APPROVE:
        if draft.status != db.STATUS_PENDING:
            _answer_callback(cb_id, f"Already {draft.status}")
            return
        draft.status = db.STATUS_APPROVED
        draft.approved_at = time.time()
        db.upsert_draft(draft)
        _answer_callback(cb_id, "Approved — queued for posting")
        _edit_message(chat_id, message_id, _format_draft(draft) + "\n\n✅ *APPROVED — queued*")
    elif action == CB_REJECT:
        draft.status = db.STATUS_REJECTED
        db.upsert_draft(draft)
        _answer_callback(cb_id, "Rejected")
        _edit_message(chat_id, message_id, _format_draft(draft) + "\n\n❌ *REJECTED*")
    elif action == CB_EDIT:
        _answer_callback(cb_id, "Reply to this message with your edit")
        _reply(
            chat_id,
            message_id,
            "✏️ Reply to the draft message above with your new tweet text. "
            "I'll update it and keep it pending approval.",
        )
    else:
        _answer_callback(cb_id, "Unknown action")


COMMANDS_HELP = (
    "🤖 *Commands*\n"
    "`run` — scrape news and generate new drafts now\n"
    "`status` — show pending / approved / posted counts\n"
    "`job` — describe what I do (or ask: \"what's your job?\")\n"
    "`help` — show this message"
)

ABOUT_TEXT = (
    "🤖 *My job*\n\n"
    "I'm an autonomous Twitter agent running on GitHub Actions — no server, "
    "no manual intervention. I post to *@jeffrizkala*.\n\n"
    "*Every morning (09:00 ET):*\n"
    "• Scrape ~200+ articles from Reuters, AP, Politico, The Hill, WaPo, "
    "Bloomberg, CNBC, MarketWatch, SeekingAlpha, and Google News\n"
    "• Rank by recency × source authority × headline specificity\n"
    "• Dedupe near-duplicate stories across sources\n"
    "• Draft tweets with *Claude Opus 4.7* in my operator's voice "
    "(US politics + stocks/trading niches)\n"
    "• Send the top 10 drafts here for approval\n\n"
    "*When you tap ✅ Approve:*\n"
    "• The tweet is queued and auto-posted to X via the API\n"
    "• Daily cap: 10 tweets, 30-min minimum spacing between posts\n"
    "• Unapproved drafts expire after 12 hours\n\n"
    "*Also:*\n"
    "• Tap ✏️ to edit a draft in place before approving\n"
    "• Tap ❌ to reject\n"
    "• Type `run` to trigger me on-demand\n\n"
    "*Stack:* Claude Opus 4.7 + Twitter API v2 + Telegram Bot API + "
    "GitHub Actions cron. Prompt caching keeps LLM cost under $1/day."
)

ABOUT_TRIGGERS = (
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
)


def _command_text(msg: dict) -> str | None:
    """Return a lowercased command keyword if the message is a top-level command."""
    if msg.get("reply_to_message"):
        return None
    text = (msg.get("text") or "").strip().lower()
    if not text:
        return None

    # Accept both "/run" and "run"; strip bot suffix like /run@MyBot; trim punctuation.
    stripped = text.lstrip("/").split("@", 1)[0].strip().rstrip("?.!")

    # Strict single-word commands
    if stripped in {"run", "status", "help", "start"}:
        return stripped
    if stripped in {"job", "about"}:
        return "about"

    # Natural-language triggers ("what's your job?", "what do you do", ...)
    normalized = text.rstrip("?.!").strip()
    for trigger in ABOUT_TRIGGERS:
        if trigger in normalized:
            return "about"
    return None


def _is_authorized(msg: dict) -> bool:
    """Only the owner (TELEGRAM_CHAT_ID) can issue commands."""
    chat = msg.get("chat") or {}
    return str(chat.get("id")) == str(_chat_id())


def _handle_command(msg: dict, cmd: str) -> None:
    chat_id = msg["chat"]["id"]
    message_id = msg["message_id"]

    if not _is_authorized(msg):
        _reply(chat_id, message_id, "⛔ Unauthorized.")
        return

    if cmd in ("help", "start"):
        _reply(chat_id, message_id, COMMANDS_HELP)
        return

    if cmd == "about":
        _reply(chat_id, message_id, ABOUT_TEXT)
        return

    if cmd == "status":
        pending = len(db.drafts_by_status(db.STATUS_PENDING))
        approved = len(db.drafts_by_status(db.STATUS_APPROVED))
        posted_today = db.posts_today_count()
        text = (
            "📊 *Status*\n"
            f"Pending approval: *{pending}*\n"
            f"Approved (queued): *{approved}*\n"
            f"Posted today: *{posted_today}*"
        )
        _reply(chat_id, message_id, text)
        return

    if cmd == "run":
        ok = trigger_workflow("morning.yml")
        if ok:
            _reply(
                chat_id,
                message_id,
                "🚀 Morning workflow dispatched. New drafts should arrive in ~1–2 min.",
            )
        else:
            _reply(
                chat_id,
                message_id,
                "❌ Failed to dispatch workflow. Check GH_REPO / GH_WORKFLOW_TOKEN secrets.",
            )
        return


def _handle_reply(msg: dict) -> None:
    reply_to = msg.get("reply_to_message") or {}
    reply_to_id = reply_to.get("message_id")
    if not reply_to_id:
        return
    draft = _find_draft_by_message(reply_to_id)
    if not draft:
        # might be a reply to the bot's "reply to the draft above" prompt;
        # in that case the reply_to is the prompt, and the prompt replied to the draft
        prompt_reply_to_id = (reply_to.get("reply_to_message") or {}).get("message_id")
        if prompt_reply_to_id:
            draft = _find_draft_by_message(prompt_reply_to_id)
    if not draft:
        return

    new_text = (msg.get("text") or "").strip()
    if not new_text:
        return

    cfg = load_config()
    max_chars = cfg["generation"]["max_tweet_chars"]
    if len(new_text) > max_chars:
        _reply(
            msg["chat"]["id"],
            msg["message_id"],
            f"⚠️ Edit is {len(new_text)} chars — max is {max_chars}. Try again.",
        )
        return

    draft.edit_history.append(draft.text)
    draft.text = new_text
    draft.status = db.STATUS_PENDING
    db.upsert_draft(draft)

    # Update the original draft message to show the new text + keyboard.
    if draft.telegram_message_id:
        _api(
            "editMessageText",
            {
                "chat_id": msg["chat"]["id"],
                "message_id": draft.telegram_message_id,
                "text": _format_draft(draft) + "\n\n_(edited — pending approval)_",
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
                "reply_markup": _keyboard(draft.id),
            },
        )


def dispatch_update(upd: dict) -> bool:
    """Route a single Telegram update through the right handler.

    Used by both the webhook (via process_update.py) and the legacy
    getUpdates loop (process_updates, below). Returns True if handled.
    """
    try:
        if "callback_query" in upd:
            _handle_callback(upd["callback_query"])
            return True
        if "message" in upd:
            msg = upd["message"]
            cmd = _command_text(msg)
            if cmd:
                _handle_command(msg, cmd)
                return True
            if msg.get("reply_to_message"):
                _handle_reply(msg)
                return True
    except Exception as e:
        log.exception("Update handler failed: %s", e)
    return False


def process_updates() -> int:
    """Poll Telegram for any new events and handle them. Returns count processed.

    Used by the hourly cron as a safety net. If a webhook is configured,
    Telegram returns 409 — we log once and skip.
    """
    offset = db.get_telegram_offset()
    try:
        data = _api(
            "getUpdates",
            {"offset": offset + 1 if offset else 0, "timeout": 0, "allowed_updates": ["callback_query", "message"]},
            timeout=15,
        )
    except Exception as e:
        msg = str(e)
        if "409" in msg or "webhook is active" in msg.lower() or "Conflict" in msg:
            log.info("getUpdates skipped — webhook is active")
        else:
            log.exception("getUpdates failed: %s", e)
        return 0

    updates = data.get("result", [])
    count = 0
    max_id = offset
    for upd in updates:
        max_id = max(max_id, upd["update_id"])
        if dispatch_update(upd):
            count += 1

    if max_id != offset:
        db.set_telegram_offset(max_id)
    return count


def notify(text: str) -> None:
    """Plain status message to the user — for daily summaries, errors, etc."""
    try:
        _api(
            "sendMessage",
            {"chat_id": _chat_id(), "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True},
        )
    except Exception as e:
        log.warning("notify failed: %s", e)


def expire_old_drafts(ttl_minutes: int) -> int:
    cutoff = time.time() - ttl_minutes * 60
    n = 0
    for d in db.load_drafts():
        if d.status == db.STATUS_PENDING and d.created_at < cutoff:
            d.status = db.STATUS_EXPIRED
            db.upsert_draft(d)
            if d.telegram_message_id:
                _edit_message(
                    _chat_id(),
                    d.telegram_message_id,
                    _format_draft(d) + "\n\n⏱ *EXPIRED (unapproved)*",
                )
            n += 1
    return n
