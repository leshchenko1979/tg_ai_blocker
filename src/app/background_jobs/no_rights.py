"""
No-rights grace period jobs.

Scheduled daily. Leaves groups where bot has no required rights (delete_messages,
restrict_members) after grace period. Notifies admins before leaving.
"""

import logging

from aiogram.types import ChatMemberAdministrator

from ..common.bot import bot
from ..common.notifications import perform_complete_group_cleanup
from ..common.utils import (
    format_chat_or_channel_display,
    get_add_to_group_url,
    load_config,
    retry_on_network_error,
)
from ..database import get_admin, get_group
from ..database.group_operations import (
    clear_no_rights_detected_at,
    get_groups_with_no_rights_past_grace,
)
from ..i18n import normalize_lang, t

logger = logging.getLogger(__name__)


def _get_no_rights_grace_days() -> int:
    """Load no_rights_grace_days from config. Default 7."""
    config = load_config()
    billing = config.get("billing", {})
    return billing.get("no_rights_grace_days", 7)


async def _send_admin_message(admin_id: int, text: str) -> bool:
    """Send a message to admin. Returns True if sent, False on failure."""
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
            f"Failed to send no-rights message to admin {admin_id}: {e}",
            exc_info=True,
        )
        return False


async def leave_no_rights_groups() -> None:
    """
    Leave groups where bot has no required rights past grace period.
    Re-verify via get_chat_member before leaving. Notify admins.
    """
    grace_days = _get_no_rights_grace_days()
    group_ids = await get_groups_with_no_rights_past_grace(grace_days)

    if not group_ids:
        return

    bot_info = await bot.me()
    bot_user_id = bot_info.id

    # Collect admin_id -> list of (group_id, display) for groups we leave
    admin_to_left_groups: dict[int, list[tuple[int, str]]] = {}

    for group_id in group_ids:
        try:
            member = await bot.get_chat_member(group_id, bot_user_id)

            if isinstance(member, ChatMemberAdministrator) and (
                getattr(member, "can_delete_messages", False)
                and getattr(member, "can_restrict_members", False)
            ):
                await clear_no_rights_detected_at(group_id)
                logger.info(f"Rights restored in group {group_id}, cleared flag")
                continue

            # No rights or not admin: leave
            group = await get_group(group_id)
            try:
                chat = await bot.get_chat(group_id)
                title = getattr(chat, "title", None) or str(group_id)
                username = getattr(chat, "username", None)
                display = format_chat_or_channel_display(
                    title, username, t("en", "common.group")
                )
            except Exception:
                display = str(group_id)

            success = await perform_complete_group_cleanup(group_id)
            if success:
                logger.info(f"Left no-rights group {group_id}")
                if group and group.admin_ids:
                    for admin_id in group.admin_ids:
                        if admin_id not in admin_to_left_groups:
                            admin_to_left_groups[admin_id] = []
                        admin_to_left_groups[admin_id].append((group_id, display))
            else:
                logger.warning(f"Failed to leave group {group_id}")

        except Exception as e:
            logger.warning(
                f"Error checking/leaving group {group_id}: {e}",
                exc_info=True,
            )
            group = await get_group(group_id)
            display = str(group_id)
            if group and group.admin_ids:
                try:
                    chat = await bot.get_chat(group_id)
                    title = getattr(chat, "title", None) or str(group_id)
                    username = getattr(chat, "username", None)
                    display = format_chat_or_channel_display(
                        title, username, t("en", "common.group")
                    )
                except Exception:
                    pass
            try:
                success = await perform_complete_group_cleanup(group_id)
                if success and group and group.admin_ids:
                    for admin_id in group.admin_ids:
                        if admin_id not in admin_to_left_groups:
                            admin_to_left_groups[admin_id] = []
                        admin_to_left_groups[admin_id].append((group_id, display))
            except Exception as cleanup_e:
                logger.warning(f"Cleanup failed for {group_id}: {cleanup_e}")

    # Notify each admin about their left groups
    for admin_id, groups_list in admin_to_left_groups.items():
        admin = await get_admin(admin_id)
        if admin and not admin.is_active:
            continue

        lang = (
            normalize_lang(admin.language_code)
            if admin and admin.language_code
            else "en"
        )
        groups_display = "\n• ".join(display for _, display in groups_list)
        ref_link = f"https://t.me/{bot_info.username}?start={admin_id}"

        text = t(
            lang,
            "no_rights.left_groups",
            groups=groups_display,
            ref_link=ref_link,
            add_to_group_url=get_add_to_group_url(),
        )
        await _send_admin_message(admin_id, text)
        logger.info(
            f"Notified admin {admin_id} about {len(groups_list)} no-rights leaves"
        )
