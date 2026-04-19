"""Entry point: process a single Telegram update passed as UPDATE_JSON env.

Invoked by .github/workflows/process_update.yml when the Cloudflare Worker
dispatches it. Runs the same handlers the hourly job uses, then also tries
to post any approved drafts immediately.
"""
import json
import logging
import os
import sys

from src import db, poster, telegram_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def main() -> None:
    raw = os.environ.get("UPDATE_JSON", "").strip()
    if not raw:
        logging.error("UPDATE_JSON env is empty")
        sys.exit(1)

    try:
        update = json.loads(raw)
    except json.JSONDecodeError as e:
        logging.error("Failed to parse UPDATE_JSON: %s", e)
        sys.exit(1)

    # Route the update through the normal handlers.
    telegram_bot.dispatch_update(update)

    # Approvals land here — try to post immediately, respecting cap/spacing.
    posted = poster.post_approved()
    for d in posted:
        try:
            telegram_bot.notify(
                f"✅ Posted tweet `{d.tweet_id}` ({d.niche})\n"
                f"https://x.com/i/status/{d.tweet_id}"
            )
        except Exception:
            pass

    logging.info("Update processed (posted=%d)", len(posted))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.exception("process_update failed: %s", e)
        sys.exit(1)
