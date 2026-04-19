"""Optional X/Twitter recent-search to spot trending conversation.

Twitter API Basic tier includes limited recent-search reads. This is used to
surface trending tickers/phrases, not to draft tweets directly.
"""
from __future__ import annotations

import logging
import os

import tweepy

from ..config import env

log = logging.getLogger(__name__)


def _client() -> tweepy.Client | None:
    token = env("TWITTER_BEARER_TOKEN")
    if not token:
        return None
    return tweepy.Client(bearer_token=token, wait_on_rate_limit=False)


def fetch_x_mentions(query: str, max_results: int = 20) -> list[dict]:
    if os.environ.get("ENABLE_X_SEARCH", "false").lower() != "true":
        return []
    client = _client()
    if client is None:
        return []
    try:
        resp = client.search_recent_tweets(
            query=query,
            max_results=max(10, min(max_results, 100)),
            tweet_fields=["public_metrics", "created_at", "lang"],
        )
    except Exception as e:
        log.warning("X search failed for %r: %s", query, e)
        return []

    data = resp.data or []
    out = []
    for t in data:
        m = t.public_metrics or {}
        out.append(
            {
                "id": t.id,
                "text": t.text,
                "likes": m.get("like_count", 0),
                "retweets": m.get("retweet_count", 0),
                "replies": m.get("reply_count", 0),
                "created_at": t.created_at.timestamp() if t.created_at else None,
            }
        )
    log.info("X search %r: %d tweets", query, len(out))
    return out
