"""
Clean up spam examples for a specific admin.

Addresses contradicting examples (not-spam with strong spam indicators like bot in bio,
new account) that can confuse the LLM, and reduces prompt bloat.

Usage:
  python scripts/cleanup_admin_spam_examples.py --admin-id 286024235 --list
  python scripts/cleanup_admin_spam_examples.py --chat-id -1001660382870 --list
  python scripts/cleanup_admin_spam_examples.py --admin-id 286024235 --remove-contradicting --dry-run
  python scripts/cleanup_admin_spam_examples.py --admin-id 286024235 --remove-duplicates --limit 30 --dry-run
"""

import argparse
import asyncio
import logging
import os
import re
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

load_dotenv()

from src.app.database.postgres_connection import get_pool

logger = logging.getLogger(__name__)

# Not-spam with these profile indicators may contradict Trojan Horse guidance
BIO_BOT_PATTERN = re.compile(r"t\.me/|bot|robot|лиды|привод", re.I)
NAME_PROMO_PATTERN = re.compile(r"\d+к(?:\s|/)|комменты|лиды|экспертиза", re.I)
RISKY_ACCOUNT_AGE = ("photo_age=0mo", "photo_age=unknown")


async def get_admin_ids_from_chat(chat_id: int) -> list[int]:
    """Resolve admin_ids for a group from chat_id."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT admin_id FROM group_administrators WHERE group_id = $1",
            chat_id,
        )
        return [r["admin_id"] for r in rows] if rows else []


async def list_examples(admin_ids: list[int]) -> None:
    """List spam examples used for the admin(s)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, admin_id, score, LEFT(text, 70) as text_preview, name, LEFT(bio, 50) as bio_preview,
                   account_signals_context, created_at
            FROM spam_examples
            WHERE (admin_id IS NULL OR admin_id = ANY($1)) AND (confirmed IS NOT DISTINCT FROM true)
            ORDER BY admin_id NULLS FIRST, created_at DESC
            LIMIT 200
            """,
            admin_ids,
        )
        # Summary
        counts = await conn.fetch(
            """
            SELECT admin_id, score, COUNT(*) as cnt
            FROM spam_examples
            WHERE (admin_id IS NULL OR admin_id = ANY($1)) AND (confirmed IS NOT DISTINCT FROM true)
            GROUP BY admin_id, score
            ORDER BY admin_id NULLS FIRST, score
            """,
            admin_ids,
        )
    total = sum(r["cnt"] for r in counts)
    logger.info("Summary for admin_ids %s: %s examples total", admin_ids, total)
    for r in counts:
        admin_label = "global" if r["admin_id"] is None else r["admin_id"]
        logger.info(
            "  admin_id=%s score=%s count=%s", admin_label, r["score"], r["cnt"]
        )
    logger.info("---")
    for row in rows[:50]:
        logger.info(
            "id=%s admin=%s score=%s | %s | name=%s bio=%s age=%s",
            row["id"],
            row["admin_id"] or "GLOBAL",
            row["score"],
            (row["text_preview"] or "")[:50],
            row["name"],
            row["bio_preview"],
            row["account_signals_context"],
        )
    if len(rows) > 50:
        logger.info("... and %s more", len(rows) - 50)


def _is_contradicting(row: dict) -> bool:
    """True if not-spam example has strong spam indicators (Trojan Horse contradiction)."""
    if row["score"] >= 0:
        return False
    bio = (row.get("bio") or "") or ""
    name = (row.get("name") or "") or ""
    age = row.get("account_signals_context") or ""
    if BIO_BOT_PATTERN.search(bio) and (age in RISKY_ACCOUNT_AGE or not age):
        return True
    if NAME_PROMO_PATTERN.search(name) and (age in RISKY_ACCOUNT_AGE or not age):
        return True
    return False


async def remove_contradicting(admin_ids: list[int], dry_run: bool) -> int:
    """Remove admin-specific not-spam examples with conflicting profile indicators."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, admin_id, text, name, bio, score, account_signals_context
            FROM spam_examples
            WHERE admin_id = ANY($1) AND score < 0 AND (confirmed IS NOT DISTINCT FROM true)
            """,
            admin_ids,
        )
    contradicting = [r for r in rows if _is_contradicting(dict(r))]
    if not contradicting:
        logger.info("No contradicting examples found")
        return 0
    ids_to_delete = [r["id"] for r in contradicting]
    logger.info(
        "%s contradicting examples (admin-specific): %s",
        len(ids_to_delete),
        ids_to_delete,
    )
    for r in contradicting:
        logger.info(
            "  id=%s name=%s bio=%s age=%s",
            r["id"],
            r["name"],
            (r["bio"] or "")[:40],
            r["account_signals_context"],
        )
    if dry_run:
        logger.info("Dry run: would delete %s rows", len(ids_to_delete))
        return len(ids_to_delete)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM spam_examples WHERE id = ANY($1)",
            ids_to_delete,
        )
    logger.info("Deleted %s contradicting examples", len(ids_to_delete))
    return len(ids_to_delete)


async def remove_duplicates(admin_ids: list[int], dry_run: bool) -> int:
    """Among admin-specific examples, keep one per (text, name), delete older duplicates."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, text, name, created_at
            FROM spam_examples
            WHERE admin_id = ANY($1) AND (confirmed IS NOT DISTINCT FROM true)
            ORDER BY created_at ASC
            """,
            admin_ids,
        )
    seen: dict[tuple[str, str | None], int] = {}
    to_delete: list[int] = []
    for r in rows:
        key = (r["text"] or "", r["name"])
        if key in seen:
            to_delete.append(r["id"])
        else:
            seen[key] = r["id"]
    if not to_delete:
        logger.info("No duplicate (text, name) pairs found")
        return 0
    logger.info("Found %s duplicate rows to remove: %s", len(to_delete), to_delete[:20])
    if dry_run:
        logger.info("Dry run: would delete %s rows", len(to_delete))
        return len(to_delete)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM spam_examples WHERE id = ANY($1)", to_delete)
    logger.info("Deleted %s duplicate examples", len(to_delete))
    return len(to_delete)


async def limit_admin_examples(admin_ids: list[int], keep: int, dry_run: bool) -> int:
    """Keep only N most recent admin-specific examples per admin, delete the rest."""
    pool = await get_pool()
    deleted = 0
    for aid in admin_ids:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id FROM spam_examples
                WHERE admin_id = $1 AND (confirmed IS NOT DISTINCT FROM true)
                ORDER BY created_at DESC
                """,
                aid,
            )
        if len(rows) <= keep:
            continue
        to_delete = [r["id"] for r in rows[keep:]]
        logger.info(
            "Admin %s: keeping %s, deleting %s oldest", aid, keep, len(to_delete)
        )
        if dry_run:
            deleted += len(to_delete)
            continue
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM spam_examples WHERE id = ANY($1)", to_delete
            )
        deleted += len(to_delete)
    if dry_run and deleted:
        logger.info("Dry run: would delete %s rows total", deleted)
    elif deleted:
        logger.info("Deleted %s rows total", deleted)
    return deleted


async def main() -> None:
    parser = argparse.ArgumentParser(description="Clean up spam examples for an admin")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--admin-id", type=int, help="Admin Telegram user ID")
    g.add_argument("--chat-id", type=int, help="Group chat ID (resolves to admin_ids)")
    parser.add_argument("--list", action="store_true", help="List examples and exit")
    parser.add_argument(
        "--remove-contradicting",
        action="store_true",
        help="Remove admin-specific not-spam examples with bot/promo in bio+new account",
    )
    parser.add_argument(
        "--remove-duplicates",
        action="store_true",
        help="Remove admin-specific duplicates by (text, name)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="Keep only N most recent admin-specific examples per admin",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without modifying the database",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if args.admin_id:
        admin_ids = [args.admin_id]
    else:
        admin_ids = await get_admin_ids_from_chat(args.chat_id)
        if not admin_ids:
            logger.error("No admins found for chat_id %s", args.chat_id)
            sys.exit(1)
        logger.info("Resolved chat_id %s -> admin_ids %s", args.chat_id, admin_ids)

    if args.list:
        await list_examples(admin_ids)
        return

    if args.remove_contradicting:
        await remove_contradicting(admin_ids, args.dry_run)
    if args.remove_duplicates:
        await remove_duplicates(admin_ids, args.dry_run)
    if args.limit is not None:
        await limit_admin_examples(admin_ids, args.limit, args.dry_run)

    if not any(
        [args.remove_contradicting, args.remove_duplicates, args.limit is not None]
    ):
        parser.error(
            "Specify --list or at least one of --remove-contradicting, --remove-duplicates, --limit"
        )


if __name__ == "__main__":
    asyncio.run(main())
