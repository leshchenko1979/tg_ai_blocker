#!/usr/bin/env python3
"""Broadcast a custom update message to all known admins."""

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

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from dotenv import load_dotenv

from src.app.common.utils import retry_on_network_error
from src.app.database.admin_operations import deactivate_admin, get_all_admins
from src.app.database.postgres_connection import close_pool, get_pool

logger = logging.getLogger(__name__)


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

    if not args.message and not args.message_file:
        parser.error("You must provide --message or --message-file.")

    return args


def load_message(args: argparse.Namespace) -> str:
    if args.message_file:
        return args.message_file.read_text(encoding="utf-8")
    return args.message


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
    bot: Bot, message: str, parse_mode: str
) -> tuple[dict[str, list[int]], int]:
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
            await _deactivate_admin_after_failure(admin_id)

    return summary, len(admins)


def print_summary(summary: dict[str, list[int]], total: int, message: str) -> None:
    print("\nBroadcast summary")
    print("-----------------")
    print(f"Total admins in DB: {total}")
    print(f"Successfully notified: {len(summary['sent'])}")
    print(f"Unable to reach: {len(summary['unreachable'])}")
    print(f"Skipped (non-user accounts): {len(summary['bots_skipped'])}")
    if summary["unreachable"]:
        print("Problematic IDs: " + ", ".join(map(str, summary["unreachable"])))
    if summary["sent"]:
        snippet = message if len(message) <= 200 else message[:200] + "..."
        print(f"\nMessage preview:\n{snippet}")


async def main() -> None:
    args = parse_args()
    configure_logging(args.log_level)
    load_dotenv()

    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN environment variable is not set.")

    message = load_message(args)
    if not message.strip():
        raise ValueError("Provided message is empty.")

    await get_pool()
    bot = Bot(token=token)

    try:
        summary, total_admins = await broadcast_updates(bot, message, args.parse_mode)
        print_summary(summary, total=total_admins, message=message)
    finally:
        await bot.session.close()
        await close_pool()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Broadcast interrupted by user.")
