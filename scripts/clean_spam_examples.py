"""
Legacy cleanup: remove alert wrapper from spam_examples.text.

Contract (spam_examples.text): ONLY original message content — no alert wrapper
(⚠️ ВТОРЖЕНИЕ!, Группа:, Нарушитель:, Содержание угрозы:, Причина:, etc.).

With the pending flow, new examples are stored at notify time from the original
message, so this script is only needed for legacy rows inserted before that change.
"""

import argparse
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Загружаем переменные окружения до импортов
load_dotenv()

from src.app.database.postgres_connection import get_pool
from src.app.common.utils import clean_alert_text

logger = logging.getLogger(__name__)


async def clean_spam_examples(*, dry_run: bool = False) -> int:
    """
    Remove alert wrapper from spam_examples.text.

    Only processes confirmed rows (pending rows are excluded).
    Returns the number of rows cleaned.
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, text FROM spam_examples WHERE (confirmed IS NOT DISTINCT FROM true)"
        )

        cleaned = 0
        for row in rows:
            original_text = row["text"]
            cleaned_text = clean_alert_text(original_text)

            if cleaned_text != original_text:
                if dry_run:
                    logger.info(
                        "Would clean example %s: %s... -> %s...",
                        row["id"],
                        original_text[:80],
                        (cleaned_text or "")[:80],
                    )
                    cleaned += 1
                else:
                    await conn.execute(
                        "UPDATE spam_examples SET text = $1 WHERE id = $2",
                        cleaned_text,
                        row["id"],
                    )
                    cleaned += 1
                    logger.info("Cleaned example %s", row["id"])

        logger.info(
            "%s %s examples out of %s total",
            "Would clean" if dry_run else "Cleaned",
            cleaned,
            len(rows),
        )
        return cleaned


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Clean alert wrapper from spam_examples.text"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be cleaned without modifying the database",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    asyncio.run(clean_spam_examples(dry_run=args.dry_run))
