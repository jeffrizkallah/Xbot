"""Entry point for the daily morning pipeline run.

Invoked by .github/workflows/morning.yml. Scrapes news, generates drafts,
sends them to Telegram for approval.
"""
import logging
import sys

from src.pipeline import run_morning_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

if __name__ == "__main__":
    try:
        stats = run_morning_pipeline()
        print(f"Morning run OK: {stats}")
    except Exception as e:
        logging.exception("Morning run failed: %s", e)
        sys.exit(1)
