"""Rank scraped articles by a simple weighted score.

Signals (all normalized 0-1 then weighted):
  - recency: exponential decay from publish time, half-life from config
  - source authority: hand-curated multiplier per domain
  - title richness: penalize clickbait/empty titles, reward specific numbers & tickers
  - deduplication: near-duplicate titles collapsed to the best one
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from urllib.parse import urlparse

from .scrape.rss import Article

# Authority weight per domain. Unknown domains default to 1.0.
SOURCE_WEIGHTS = {
    "reuters.com": 1.4,
    "apnews.com": 1.4,
    "bloomberg.com": 1.3,
    "wsj.com": 1.3,
    "ft.com": 1.3,
    "cnbc.com": 1.2,
    "marketwatch.com": 1.1,
    "politico.com": 1.2,
    "thehill.com": 1.0,
    "washingtonpost.com": 1.2,
    "nytimes.com": 1.2,
    "seekingalpha.com": 0.9,
}

TICKER_RE = re.compile(r"\$[A-Z]{1,5}\b")
NUMBER_RE = re.compile(r"\b\d[\d,\.]*%?\b")


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return ""


def _recency_score(published_ts: float, now_ts: float, half_life_h: float) -> float:
    age_h = max(0.0, (now_ts - published_ts) / 3600.0)
    return math.exp(-math.log(2) * age_h / half_life_h)


def _authority_score(url: str) -> float:
    d = _domain(url)
    for domain, weight in SOURCE_WEIGHTS.items():
        if d.endswith(domain):
            return weight
    return 1.0


def _richness_score(title: str) -> float:
    score = 0.5
    if TICKER_RE.search(title):
        score += 0.3
    if NUMBER_RE.search(title):
        score += 0.2
    # clickbait penalty
    lower = title.lower()
    if any(p in lower for p in ("you won't believe", "this one trick", "shocking")):
        score -= 0.3
    return max(0.0, min(1.5, score))


def _normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", title.lower()).strip()


def _titles_similar(a: str, b: str) -> bool:
    # cheap Jaccard on token sets
    ta, tb = set(_normalize_title(a).split()), set(_normalize_title(b).split())
    if not ta or not tb:
        return False
    inter = len(ta & tb)
    union = len(ta | tb)
    return (inter / union) >= 0.65


def score_article(a: Article, now_ts: float, half_life_h: float) -> float:
    recency = _recency_score(a.published_ts, now_ts, half_life_h)
    authority = _authority_score(a.url)
    richness = _richness_score(a.title)
    return recency * authority * richness


def dedupe(articles: list[Article]) -> list[Article]:
    """Keep highest-scored article among near-duplicate titles."""
    articles = sorted(articles, key=lambda a: getattr(a, "_score", 0), reverse=True)
    kept: list[Article] = []
    for a in articles:
        if any(_titles_similar(a.title, k.title) for k in kept):
            continue
        kept.append(a)
    return kept


def rank(
    articles: list[Article],
    now_ts: float,
    half_life_h: float,
    exclude_urls: set[str] | None = None,
) -> list[Article]:
    exclude_urls = exclude_urls or set()
    fresh = [a for a in articles if a.url not in exclude_urls]
    for a in fresh:
        a._score = score_article(a, now_ts, half_life_h)  # type: ignore[attr-defined]
    deduped = dedupe(fresh)
    return sorted(deduped, key=lambda a: a._score, reverse=True)  # type: ignore[attr-defined]


def rank_by_niche(
    articles: list[Article],
    now_ts: float,
    half_life_h: float,
    exclude_urls: set[str] | None = None,
) -> dict[str, list[Article]]:
    grouped: dict[str, list[Article]] = defaultdict(list)
    for a in articles:
        grouped[a.niche].append(a)
    return {
        niche: rank(group, now_ts, half_life_h, exclude_urls)
        for niche, group in grouped.items()
    }
