"""JSONL-backed state store.

We avoid SQLite so state files are human-readable in git diffs and easy to
inspect / hand-edit during development. Files live under state/ and are
committed back to the repo by the GitHub Actions workflow.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Iterable

from .config import STATE_DIR

DRAFTS_FILE = STATE_DIR / "drafts.jsonl"
SEEN_FILE = STATE_DIR / "seen_articles.jsonl"
TG_OFFSET_FILE = STATE_DIR / "telegram_offset.json"

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_POSTED = "posted"
STATUS_EXPIRED = "expired"
STATUS_FAILED = "failed"


@dataclass
class Draft:
    id: str
    niche: str
    text: str
    article_url: str
    article_title: str
    created_at: float
    status: str = STATUS_PENDING
    telegram_message_id: int | None = None
    approved_at: float | None = None
    posted_at: float | None = None
    tweet_id: str | None = None
    edit_history: list[str] = field(default_factory=list)
    error: str | None = None


def _ensure_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    _ensure_dir()
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def new_id() -> str:
    return uuid.uuid4().hex[:10]


def load_drafts() -> list[Draft]:
    return [Draft(**row) for row in _read_jsonl(DRAFTS_FILE)]


def save_drafts(drafts: list[Draft]) -> None:
    _write_jsonl(DRAFTS_FILE, [asdict(d) for d in drafts])


def upsert_draft(draft: Draft) -> None:
    drafts = load_drafts()
    for i, d in enumerate(drafts):
        if d.id == draft.id:
            drafts[i] = draft
            break
    else:
        drafts.append(draft)
    save_drafts(drafts)


def get_draft(draft_id: str) -> Draft | None:
    for d in load_drafts():
        if d.id == draft_id:
            return d
    return None


def drafts_by_status(status: str) -> list[Draft]:
    return [d for d in load_drafts() if d.status == status]


def seen_article_urls() -> set[str]:
    return {row["url"] for row in _read_jsonl(SEEN_FILE)}


def mark_articles_seen(urls: Iterable[str]) -> None:
    existing = _read_jsonl(SEEN_FILE)
    existing_set = {r["url"] for r in existing}
    now = time.time()
    for url in urls:
        if url not in existing_set:
            existing.append({"url": url, "seen_at": now})
            existing_set.add(url)
    # keep only last 2000 — enough to dedupe a few weeks of news
    existing = sorted(existing, key=lambda r: r["seen_at"])[-2000:]
    _write_jsonl(SEEN_FILE, existing)


def get_telegram_offset() -> int:
    if not TG_OFFSET_FILE.exists():
        return 0
    with open(TG_OFFSET_FILE, "r", encoding="utf-8") as f:
        return json.load(f).get("offset", 0)


def set_telegram_offset(offset: int) -> None:
    _ensure_dir()
    with open(TG_OFFSET_FILE, "w", encoding="utf-8") as f:
        json.dump({"offset": offset}, f)


def posts_today_count() -> int:
    cutoff = time.time() - 24 * 3600
    return sum(
        1
        for d in load_drafts()
        if d.status == STATUS_POSTED and (d.posted_at or 0) > cutoff
    )


def last_posted_at() -> float | None:
    posted = [d.posted_at for d in load_drafts() if d.status == STATUS_POSTED and d.posted_at]
    return max(posted) if posted else None
