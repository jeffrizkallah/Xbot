"""Trigger a GitHub Actions workflow via the REST API.

Used by the Telegram command handler when the user types "run" — the hourly
job sees the message and dispatches the morning workflow.
"""
from __future__ import annotations

import logging

import requests

from .config import env

log = logging.getLogger(__name__)


def trigger_workflow(workflow_file: str, ref: str = "main") -> bool:
    """Fire workflow_dispatch on the given workflow file (e.g. 'morning.yml').

    Requires env vars:
      - GH_REPO: e.g. "jeffrizkallah/Xbot"
      - GH_WORKFLOW_TOKEN: PAT with `actions:write` (fine-grained) or classic `workflow` scope.
    """
    repo = env("GH_REPO", required=True)
    token = env("GH_WORKFLOW_TOKEN", required=True)

    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_file}/dispatches"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        resp = requests.post(url, json={"ref": ref}, headers=headers, timeout=15)
    except Exception as e:
        log.exception("workflow dispatch request failed: %s", e)
        return False

    if resp.status_code == 204:
        log.info("Dispatched workflow %s on %s@%s", workflow_file, repo, ref)
        return True

    log.warning("workflow dispatch failed (%d): %s", resp.status_code, resp.text[:300])
    return False
