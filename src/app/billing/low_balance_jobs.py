"""
Low balance warning and group leave jobs.

Scheduled daily via asyncio background loop. Handles:
- Week-ahead warning when credits < min(threshold, last_week_spend)
- Day-1, day-6, day-7 depletion timeline warnings
- Leaving sole-payer groups on deadline (no account deletion)
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from ..common.bot import bot
from ..common.notifications import perform_complete_group_cleanup
from ..common.utils import (
    format_chat_or_channel_display,
    load_config,
    retry_on_network_error,
)
from ..i18n import normalize_lang, t
from ..database import (
    clear_depletion_flags,
    get_admin,
    get_admin_group_ids,
    get_admins_for_depletion_timeline,
    get_admins_for_low_balance_warnings,
    get_paying_admins,
    mark_low_balance_warned,
)

logger = logging.getLogger(__name__)

SECONDS_PER_DAY = 86400


def _get_billing_config():
    """Load billing config with defaults."""
    config = load_config()
    billing = config.get("billing", {})
    return {
        "low_balance_threshold": billing.get("low_balance_threshold", 50),
        "depletion_grace_days": billing.get("depletion_grace_days", 7),
        "warn_day_after": billing.get("warn_day_after", True),
        "warn_day_before": billing.get("warn_day_before", True),
    }


async def _send_admin_message(admin_id: int, text: str) -> bool:
    """Send a message to admin. Returns True if sent, False on failure (e.g. bot blocked)."""
    try:

        @retry_on_network_error
        async def _send():
            return await bot.send_message(
                admin_id,
                text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )

        await _send()
        return True
    except Exception as e:
        logger.warning(
            f"Failed to send low balance message to admin {admin_id}: {e}",
            exc_info=True,
        )
        return False


async def check_week_ahead_warnings() -> None:
    """Send week-ahead warning to admins with low balance who haven't been warned."""
    cfg = _get_billing_config()
    threshold = cfg["low_balance_threshold"]

    admins = await get_admins_for_low_balance_warnings(threshold)
    for row in admins:
        admin_id = row["admin_id"]
        credits = row["credits"]
        # Skip inactive (e.g. blocked bot)
        admin = await get_admin(admin_id)
        if admin and not admin.is_active:
            continue
        lang = (
            normalize_lang(admin.language_code)
            if admin and admin.language_code
            else "en"
        )

        text = t(lang, "low_balance.week_ahead", credits=credits)
        if await _send_admin_message(admin_id, text):
            await mark_low_balance_warned(admin_id)
            logger.info(f"Sent week-ahead warning to admin {admin_id}")


def _days_since(dt: datetime) -> float:
    """Days since the given datetime (UTC)."""
    if dt is None:
        return 0.0
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    return delta.total_seconds() / SECONDS_PER_DAY


async def check_depletion_timeline() -> None:
    """Handle day-1, day-6, day-7 depletion timeline actions."""
    cfg = _get_billing_config()
    grace_days = cfg["depletion_grace_days"]
    warn_day_after = cfg["warn_day_after"]
    warn_day_before = cfg["warn_day_before"]

    admins = await get_admins_for_depletion_timeline()
    for row in admins:
        admin_id = row["admin_id"]
        depleted_at = row["credits_depleted_at"]
        admin = await get_admin(admin_id)
        if admin and not admin.is_active:
            continue

        days = _days_since(depleted_at)

        # Day 7: leave sole-payer groups, then clear flag to avoid re-processing
        if days >= grace_days:
            await leave_sole_payer_groups(admin_id)
            await clear_depletion_flags(admin_id)
            continue

        # Day 1: warn about leaving in 7 days
        if warn_day_after and 1 <= days < 2:
            lang = (
                normalize_lang(admin.language_code)
                if admin and admin.language_code
                else "en"
            )
            deadline = depleted_at
            if deadline:
                deadline_dt = (
                    deadline.replace(tzinfo=timezone.utc)
                    if deadline.tzinfo is None
                    else deadline
                )
                deadline_dt += timedelta(days=grace_days)
                deadline_str = deadline_dt.strftime("%d.%m.%Y")
            else:
                deadline_str = t(lang, "low_balance.in_7_days")
            text = t(lang, "low_balance.depleted", deadline=deadline_str)
            await _send_admin_message(admin_id, text)
            logger.info(f"Sent day-1 depletion warning to admin {admin_id}")

        # Day 6: final warning
        elif warn_day_before and grace_days - 1 <= days < grace_days:
            lang = (
                normalize_lang(admin.language_code)
                if admin and admin.language_code
                else "en"
            )
            text = t(lang, "low_balance.tomorrow")
            await _send_admin_message(admin_id, text)
            logger.info(f"Sent day-6 depletion warning to admin {admin_id}")


async def leave_sole_payer_groups(admin_id: int) -> None:
    """
    Leave groups where admin is the sole payer (no other admins with credits > 0).
    Notify admin. No account deletion — admin record and training data preserved.
    """
    admin = await get_admin(admin_id)
    lang = (
        normalize_lang(admin.language_code) if admin and admin.language_code else "en"
    )

    group_ids = await get_admin_group_ids(admin_id)
    left_groups = []
    bot_info = await bot.me()
    ref_link = f"https://t.me/{bot_info.username}?start={admin_id}"

    for group_id in group_ids:
        paying = await get_paying_admins(group_id)
        if len(paying) == 0:
            try:
                chat = await bot.get_chat(group_id)
                title = getattr(chat, "title", None) or str(group_id)
                username = getattr(chat, "username", None)
                display = format_chat_or_channel_display(
                    title, username, t(lang, "common.group")
                )
                left_groups.append(display)
            except Exception:
                left_groups.append(str(group_id))

            success = await perform_complete_group_cleanup(group_id)
            if success:
                logger.info(
                    f"Left sole-payer group {group_id} for dry admin {admin_id}"
                )
            else:
                logger.warning(f"Failed to leave group {group_id} for admin {admin_id}")

    if left_groups:
        groups_list = "\n• ".join(left_groups)
        text = t(lang, "low_balance.left_groups", groups=groups_list, ref_link=ref_link)
        await _send_admin_message(admin_id, text)
        logger.info(
            f"Notified admin {admin_id} about leaving {len(left_groups)} groups"
        )


async def run_low_balance_checks() -> None:
    """Entry point for the daily asyncio loop."""
    try:
        await check_week_ahead_warnings()
        await check_depletion_timeline()
    except Exception as e:
        logger.error(f"Low balance checks failed: {e}", exc_info=True)


async def low_balance_loop() -> None:
    """Background loop: run checks every 24 hours. Cancel on shutdown."""
    while True:
        try:
            await run_low_balance_checks()
        except asyncio.CancelledError:
            logger.info("Low balance loop cancelled")
            raise
        except Exception as e:
            logger.error(f"Low balance loop error: {e}", exc_info=True)
        await asyncio.sleep(SECONDS_PER_DAY)
