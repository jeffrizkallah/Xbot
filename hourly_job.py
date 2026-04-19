"""Entry point for the hourly approval+post job.

1. Poll Telegram for button presses and reply-edits.
2. Post any approved drafts (respecting daily cap + spacing).
3. Expire pending drafts older than the configured TTL.
"""
import logging
import sys

from src import db, poster, telegram_bot
from src.config import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def main() -> None:
    cfg = load_config()

    processed = telegram_bot.process_updates()
    logging.info("Telegram updates processed: %d", processed)

    posted = poster.post_approved()
    for d in posted:
        try:
            telegram_bot.notify(
                f"✅ Posted tweet `{d.tweet_id}` ({d.niche})\nhttps://x.com/i/status/{d.tweet_id}"
            )
        except Exception:
            pass

    expired = telegram_bot.expire_old_drafts(cfg["telegram"]["approval_ttl_minutes"])
    if expired:
        logging.info("Expired %d stale drafts", expired)

    approved_count = len(db.drafts_by_status(db.STATUS_APPROVED))
    posted_today = db.posts_today_count()
    logging.info(
        "Hourly run OK: posted=%d, approved_queue=%d, posted_today=%d",
        len(posted),
        approved_count,
        posted_today,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.exception("Hourly run failed: %s", e)
        sys.exit(1)
