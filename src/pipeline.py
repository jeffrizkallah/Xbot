"""High-level pipeline: scrape → rank → generate → send for approval."""
from __future__ import annotations

import logging
import time

from . import db, telegram_bot
from .config import load_config
from .generate import generate_drafts
from .rank import rank_by_niche
from .scrape.google_news import fetch_google_news
from .scrape.rss import Article, fetch_rss

log = logging.getLogger(__name__)


def _collect_articles(cfg: dict) -> list[Article]:
    max_age = cfg["ranking"]["max_age_hours"]
    articles: list[Article] = []
    for niche, nc in cfg["niches"].items():
        for url in nc.get("rss", []):
            articles.extend(fetch_rss(url, niche, max_age))
        for query in nc.get("google_news_queries", []):
            articles.extend(fetch_google_news(query, niche, max_age))
    return articles


def run_morning_pipeline() -> dict:
    """Scrape, rank, generate drafts, send to Telegram. Returns run stats."""
    cfg = load_config()
    t0 = time.time()

    articles = _collect_articles(cfg)
    log.info("Collected %d raw articles", len(articles))

    seen = db.seen_article_urls()
    ranked = rank_by_niche(
        articles,
        now_ts=time.time(),
        half_life_h=cfg["ranking"]["recency_half_life_hours"],
        exclude_urls=seen,
    )
    for niche, items in ranked.items():
        log.info("Niche %s: %d ranked candidates", niche, len(items))

    drafts = generate_drafts(ranked)

    sent: list[db.Draft] = []
    for article, gen in drafts:
        d = db.Draft(
            id=db.new_id(),
            niche=article.niche,
            text=gen["tweet"],
            article_url=article.url,
            article_title=article.title,
            created_at=time.time(),
        )
        try:
            telegram_bot.send_draft(d)
            sent.append(d)
        except Exception as e:
            log.exception("Failed to send draft to Telegram: %s", e)

    # Mark the articles we actually drafted on as seen, so we don't redraft them.
    db.mark_articles_seen([a.url for a, _ in drafts])

    elapsed = time.time() - t0
    stats = {
        "articles": len(articles),
        "drafts_sent": len(sent),
        "elapsed_s": round(elapsed, 1),
    }
    summary = (
        f"🗞 Morning run\n"
        f"Articles scraped: *{stats['articles']}*\n"
        f"Drafts sent: *{stats['drafts_sent']}*\n"
        f"Elapsed: {stats['elapsed_s']}s"
    )
    try:
        telegram_bot.notify(summary)
    except Exception:
        pass
    return stats
