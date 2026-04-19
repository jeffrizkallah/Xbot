from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import feedparser

log = logging.getLogger(__name__)


@dataclass
class Article:
    url: str
    title: str
    summary: str
    source: str
    published_ts: float
    niche: str


def _parse_ts(entry) -> float:
    for key in ("published_parsed", "updated_parsed"):
        if getattr(entry, key, None):
            return time.mktime(getattr(entry, key))
    return time.time()


def fetch_rss(url: str, niche: str, max_age_hours: int) -> list[Article]:
    try:
        feed = feedparser.parse(url)
    except Exception as e:
        log.warning("RSS fetch failed for %s: %s", url, e)
        return []

    source = (feed.feed.get("title") if hasattr(feed, "feed") else None) or url
    cutoff = time.time() - max_age_hours * 3600
    out: list[Article] = []
    for entry in feed.entries:
        ts = _parse_ts(entry)
        if ts < cutoff:
            continue
        link = getattr(entry, "link", None)
        title = getattr(entry, "title", None)
        if not link or not title:
            continue
        summary = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
        out.append(
            Article(
                url=link,
                title=title.strip(),
                summary=summary.strip()[:800],
                source=source,
                published_ts=ts,
                niche=niche,
            )
        )
    log.info("RSS %s: %d fresh articles", source, len(out))
    return out
