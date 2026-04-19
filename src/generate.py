"""Generate draft tweets with Claude Opus 4.7.

Design:
- One article per API call so each tweet gets dedicated reasoning.
- System prompt + tone samples are sent with cache_control so the second
  call onward hits the prompt cache (cheaper, faster).
- Tone samples are .txt files under tone_samples/. If the folder is empty,
  we fall back to a generic "punchy, specific, no hashtags" style. Drop in
  50-200 of your own tweets (one per file or many per file, either works)
  and the generator will switch to style-mimicry mode automatically.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import anthropic

from .config import TONE_DIR, env, load_config
from .scrape.rss import Article

log = logging.getLogger(__name__)

SYSTEM_BASE = """You are a tweet-writing assistant for a single user whose
Twitter account covers US politics and stocks/trading. You write ONE
standalone tweet at a time based on a news article the user is reacting to.

Hard rules:
- Maximum {max_chars} characters. Count carefully.
- No hashtags. No emojis unless the user's tone samples use them.
- No "thread" markers, no "1/", no "🧵".
- No disclaimers like "this is not financial advice".
- Never fabricate numbers, quotes, or facts not in the source article.
- If the article lacks a specific hook, return an empty tweet rather than
  inventing one.
- Prefer concrete numbers, names, and tickers over vague commentary.
- For trading tweets, include the ticker in $SYMBOL form when relevant.
- For political tweets, stay sharp but not libellous. Opinions OK, slurs no.

Output format: strict JSON, no prose:
{{"tweet": "<the tweet text>", "rationale": "<one short sentence on the angle>"}}

If the article is not worth tweeting about, return:
{{"tweet": "", "rationale": "<why not>"}}
"""

TONE_DEFAULT = """No tone samples provided yet. Default style: punchy, specific,
skimmable. One idea per tweet. Lead with the news, then the take."""


def _load_tone_samples() -> str:
    if not TONE_DIR.exists():
        return TONE_DEFAULT
    files = sorted(TONE_DIR.glob("*.txt"))
    if not files:
        return TONE_DEFAULT
    chunks = []
    for f in files:
        content = f.read_text(encoding="utf-8").strip()
        if content:
            chunks.append(content)
    if not chunks:
        return TONE_DEFAULT
    joined = "\n\n---\n\n".join(chunks)
    return (
        "The following are real tweets written by the user. Mimic their "
        "voice, sentence length, punctuation, and cadence. Do NOT copy phrases "
        "verbatim.\n\n<user_tweets>\n" + joined + "\n</user_tweets>"
    )


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))


def _build_system_blocks(max_chars: int) -> list[dict]:
    tone = _load_tone_samples()
    # Two blocks, both cached: the static rules and the (relatively static) tone.
    return [
        {
            "type": "text",
            "text": SYSTEM_BASE.format(max_chars=max_chars),
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": tone,
            "cache_control": {"type": "ephemeral"},
        },
    ]


def _user_prompt(article: Article) -> str:
    return (
        f"Niche: {article.niche}\n"
        f"Source: {article.source}\n"
        f"Title: {article.title}\n"
        f"Summary: {article.summary}\n"
        f"URL: {article.url}\n\n"
        "Write one tweet reacting to this article."
    )


def draft_tweet(client: anthropic.Anthropic, article: Article, max_chars: int, model: str) -> dict | None:
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=400,
            system=_build_system_blocks(max_chars),
            messages=[{"role": "user", "content": _user_prompt(article)}],
        )
    except Exception as e:
        log.exception("Claude call failed for %s: %s", article.url, e)
        return None

    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
    # Strip common JSON fencing
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        log.warning("Non-JSON response for %s: %r", article.url, text[:200])
        return None

    tweet = (parsed.get("tweet") or "").strip()
    if not tweet:
        log.info("Skipped (no tweet) for %s — %s", article.url, parsed.get("rationale", ""))
        return None
    if len(tweet) > max_chars:
        log.info("Dropping over-length tweet (%d chars) for %s", len(tweet), article.url)
        return None

    return {
        "tweet": tweet,
        "rationale": parsed.get("rationale", ""),
    }


def generate_drafts(articles_by_niche: dict[str, list[Article]]) -> list[tuple[Article, dict]]:
    cfg = load_config()
    model = cfg["generation"]["model"]
    max_chars = cfg["generation"]["max_tweet_chars"]
    niche_cfg = cfg["niches"]

    client = _client()
    results: list[tuple[Article, dict]] = []
    for niche, articles in articles_by_niche.items():
        target = niche_cfg.get(niche, {}).get("drafts", 5)
        produced = 0
        for a in articles:
            if produced >= target:
                break
            draft = draft_tweet(client, a, max_chars, model)
            if draft:
                results.append((a, draft))
                produced += 1
        log.info("Generated %d/%d drafts for niche=%s", produced, target, niche)
    return results
