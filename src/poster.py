"""Post approved drafts to X (Twitter) via API v2."""
from __future__ import annotations

import logging
import time

import tweepy

from . import db
from .config import env, load_config

log = logging.getLogger(__name__)


def _client() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=env("TWITTER_API_KEY", required=True),
        consumer_secret=env("TWITTER_API_SECRET", required=True),
        access_token=env("TWITTER_ACCESS_TOKEN", required=True),
        access_token_secret=env("TWITTER_ACCESS_TOKEN_SECRET", required=True),
    )


def post_draft(client: tweepy.Client, draft: db.Draft) -> bool:
    try:
        resp = client.create_tweet(text=draft.text)
    except Exception as e:
        draft.status = db.STATUS_FAILED
        draft.error = str(e)[:500]
        db.upsert_draft(draft)
        log.exception("create_tweet failed for draft %s: %s", draft.id, e)
        return False

    tweet_id = str(resp.data["id"]) if resp.data else None
    if not tweet_id:
        draft.status = db.STATUS_FAILED
        draft.error = "No tweet id in response"
        db.upsert_draft(draft)
        return False

    draft.status = db.STATUS_POSTED
    draft.posted_at = time.time()
    draft.tweet_id = tweet_id
    db.upsert_draft(draft)
    log.info("Posted draft %s as tweet %s", draft.id, tweet_id)
    return True


def post_approved() -> list[db.Draft]:
    """Post as many approved drafts as allowed by daily cap + spacing."""
    cfg = load_config()
    cap = cfg["posting"]["daily_cap"]
    spacing_min = cfg["posting"]["min_spacing_minutes"]

    approved = sorted(db.drafts_by_status(db.STATUS_APPROVED), key=lambda d: d.approved_at or 0)
    if not approved:
        return []

    posted_today = db.posts_today_count()
    remaining = cap - posted_today
    if remaining <= 0:
        log.info("Daily cap reached (%d posted today)", posted_today)
        return []

    last_ts = db.last_posted_at()
    if last_ts and (time.time() - last_ts) < spacing_min * 60:
        wait_s = int(spacing_min * 60 - (time.time() - last_ts))
        log.info("Spacing: %ds until next allowed post", wait_s)
        return []

    client = _client()
    # Post at most one per run to honor spacing naturally across hourly runs.
    draft = approved[0]
    if post_draft(client, draft):
        return [draft]
    return []
