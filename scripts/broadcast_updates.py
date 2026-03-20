#!/usr/bin/env python3
"""Broadcast an update to all DB admins or to `--admin-ids-file` (one Telegram user id per line).

DB pool is skipped for targeted sends until a TelegramBadRequest triggers deactivation.
Transient network errors are logged only (no deactivate). Optional `python-dotenv` for local runs.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = lambda *_a, **_k: None  # Docker Compose injects env; optional locally

load_dotenv(_PROJECT_ROOT / ".env")

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from src.app.common.utils import retry_on_network_error
from src.app.database.admin_operations import deactivate_admin, get_all_admins
from src.app.database.models import Administrator
from src.app.database.postgres_connection import close_pool, get_pool

logger = logging.getLogger(__name__)


def load_admin_ids_from_file(path: Path) -> list[int]:
    """Load admin Telegram user IDs: one integer per line; # starts a comment."""
    raw = path.read_text(encoding="utf-8")
    ids: list[int] = []
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        ids.append(int(s))
    return sorted(set(ids))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send an update message to every administrator in the database."
    )
    parser.add_argument(
        "-m",
        "--message",
        help="Update text to deliver. Preserve newlines by quoting them (e.g. $'line1\\nline2').",
    )
    parser.add_argument(
        "-f",
        "--message-file",
        type=Path,
        help="Path to a UTF-8 file whose entire contents will be broadcast.",
    )
    parser.add_argument(
        "--admin-ids-file",
        type=Path,
        help="Send only to these admin user IDs (one integer per line). Skips get_all_admins().",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print recipient count and ID sample; do not connect to Telegram.",
    )
    parser.add_argument(
        "--parse-mode",
        choices=["HTML", "Markdown"],
        default="HTML",
        help="Telegram parse mode to use when sending the message.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging verbosity (DEBUG, INFO, WARNING, ERROR, CRITICAL).",
    )
    args = parser.parse_args()

    if not args.dry_run and not args.message and not args.message_file:
        parser.error("You must provide --message or --message-file (unless --dry-run).")

    return args


def load_message(args: argparse.Namespace) -> str:
    if args.dry_run and not args.message and not args.message_file:
        return ""
    if args.message_file:
        return args.message_file.read_text(encoding="utf-8")
    return args.message or ""


def configure_logging(level: str) -> None:
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )


@retry_on_network_error
async def _send_update(bot: Bot, chat_id: int, message: str, parse_mode: str) -> None:
    await bot.send_message(
        chat_id,
        message,
        parse_mode=parse_mode,
        disable_web_page_preview=True,
    )


async def _deactivate_admin_after_failure(admin_id: int) -> None:
    try:
        await get_pool()
        if await deactivate_admin(admin_id):
            logger.info(
                "Admin %s deactivated after unsuccessful broadcast delivery", admin_id
            )
        else:
            logger.info(
                "Admin %s already inactive when trying to record broadcast failure",
                admin_id,
            )
    except Exception:
        logger.exception(
            "Unable to deactivate admin %s after broadcast failure", admin_id
        )


async def broadcast_updates(
    bot: Bot,
    message: str,
    parse_mode: str,
    admin_ids_filter: list[int] | None = None,
) -> tuple[dict[str, list[int]], int]:
    if admin_ids_filter is not None:
        admins = [Administrator(admin_id=i) for i in sorted(set(admin_ids_filter))]
    else:
        admins = await get_all_admins()
    summary: dict[str, list[int]] = {
        "sent": [],
        "unreachable": [],
        "bots_skipped": [],
    }

    for admin in admins:
        admin_id = admin.admin_id

        if admin_id < 0:
            summary["bots_skipped"].append(admin_id)
            logger.info("Skipping non-user admin %s", admin_id)
            continue

        try:
            await _send_update(bot, admin_id, message, parse_mode)
            summary["sent"].append(admin_id)
            logger.info("Message sent to admin %s", admin_id)
        except TelegramBadRequest as tb:
            summary["unreachable"].append(admin_id)
            logger.warning("Cannot send update to admin %s: %s", admin_id, tb)
            await _deactivate_admin_after_failure(admin_id)
        except Exception as exc:
            summary["unreachable"].append(admin_id)
            logger.error("Unexpected error while messaging admin %s: %s", admin_id, exc)

    return summary, len(admins)


def print_summary(
    summary: dict[str, list[int]], total: int, message: str, *, recipient_source: str
) -> None:
    print("\nBroadcast summary")
    print("-----------------")
    print(f"Recipients ({recipient_source}): {total}")
    print(f"Successfully notified: {len(summary['sent'])}")
    print(f"Unable to reach: {len(summary['unreachable'])}")
    print(f"Skipped (non-user accounts): {len(summary['bots_skipped'])}")
    if summary["unreachable"]:
        print("Problematic IDs: " + ", ".join(map(str, summary["unreachable"])))
    if summary["sent"]:
        snippet = message if len(message) <= 200 else message[:200] + "..."
        print(f"\nMessage preview:\n{snippet}")


def _print_dry_run_admin_ids(admin_ids: list[int]) -> None:
    print(f"Dry run: {len(admin_ids)} recipient(s)")
    if len(admin_ids) <= 10:
        print(f"  IDs: {admin_ids}")
    else:
        print(f"  First: {admin_ids[:5]}")
        print(f"  Last:  {admin_ids[-5:]}")


async def main() -> None:
    args = parse_args()
    configure_logging(args.log_level)
    load_dotenv(_PROJECT_ROOT / ".env")

    admin_ids_filter: list[int] | None = None
    if args.admin_ids_file:
        admin_ids_filter = load_admin_ids_from_file(args.admin_ids_file)

    if args.dry_run:
        if admin_ids_filter is not None:
            _print_dry_run_admin_ids(admin_ids_filter)
        else:
            await get_pool()
            try:
                admins = await get_all_admins()
                _print_dry_run_admin_ids([a.admin_id for a in admins])
            finally:
                await close_pool()
        return

    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN environment variable is not set.")

    message = load_message(args)
    if not message.strip():
        raise ValueError("Provided message is empty.")

    if admin_ids_filter is None:
        await get_pool()
    bot = Bot(token=token)
    recipient_source = (
        f"admin-ids-file {args.admin_ids_file}"
        if args.admin_ids_file
        else "all active in DB"
    )

    try:
        summary, total_admins = await broadcast_updates(
            bot, message, args.parse_mode, admin_ids_filter=admin_ids_filter
        )
        print_summary(
            summary,
            total=total_admins,
            message=message,
            recipient_source=recipient_source,
        )
    finally:
        await bot.session.close()
        await close_pool()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Broadcast interrupted by user.")
