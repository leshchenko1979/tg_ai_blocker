"""Spam message handling: notifications, deletion, banning."""

import html
import logging
from typing import Optional

from aiogram import types
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..common.bot import bot
from ..common.mcp_client import McpHttpError, get_mcp_client
from ..common.notifications import notify_admins_with_fallback_and_cleanup

from ..common.utils import (
    determine_effective_user_id,
    format_chat_or_channel_display,
    get_project_channel_url,
    get_setup_guide_url,
    get_spam_guide_url,
    retry_on_network_error,
)
from ..database import get_admin, get_admins_map
from ..i18n import t
from ..database.group_operations import (
    remove_member_from_group,
    set_no_rights_detected_at,
)
from ..database.spam_examples import insert_pending_spam_example
from ..types import MessageContextResult, MessageNotificationContext

logger = logging.getLogger(__name__)


async def handle_spam(
    message: types.Message,
    admin_ids: list[int],
    reason: str | None = None,
    message_context_result: Optional["MessageContextResult"] = None,
    skip_auto_delete: bool = False,
) -> str:
    """Handle detected spam: notify admins, optionally delete and ban."""
    try:
        if not message.from_user:
            logger.warning("Message without user info, skipping spam handling")
            return "spam_no_user_info"

        all_admins_delete = await check_admin_delete_preferences(admin_ids)
        effective_all_admins_delete = all_admins_delete and not skip_auto_delete

        notification_sent = await notify_admins(
            message,
            effective_all_admins_delete,
            admin_ids,
            reason,
            message_context_result,
        )

        if message_context_result and message_context_result.linked_channel_found:
            await notify_spam_contacts_via_mcp(message, reason, message_context_result)

        if effective_all_admins_delete:
            effective_user_id = determine_effective_user_id(message)
            if effective_user_id is None:
                logger.warning("Message without effective user info, skipping ban")
                return "spam_no_user_info"
            await handle_spam_message_deletion(message, admin_ids)
            await ban_user_for_spam(
                message.chat.id, effective_user_id, admin_ids, message.chat.title
            )
            return "spam_auto_deleted"

        return (
            "spam_admins_notified" if notification_sent else "spam_notification_failed"
        )

    except Exception as e:
        logger.error(f"Error handling spam: {e}", exc_info=True)
        raise


async def check_admin_delete_preferences(admin_ids: list[int]) -> bool:
    """Return True if all admins have delete_spam enabled."""
    if not admin_ids:
        return False

    admins_map = await get_admins_map(admin_ids)
    for admin_id in admin_ids:
        admin_user = admins_map.get(admin_id)
        if not admin_user or not admin_user.delete_spam:
            return False
    return True


def create_admin_notification_keyboard(
    message: types.Message,
    all_admins_delete: bool,
    pending_id: Optional[int] = None,
    *,
    lang: str = "en",
) -> InlineKeyboardMarkup:
    """Build keyboard with Delete/Not spam buttons for admin notification."""
    effective_user_id = determine_effective_user_id(message)
    if effective_user_id is None or pending_id is None:
        return InlineKeyboardMarkup(inline_keyboard=[[]])

    if not all_admins_delete:
        row = [
            InlineKeyboardButton(
                text=t(lang, "spam.delete_button"),
                callback_data=f"delete_spam_message:{effective_user_id}:{message.chat.id}:{message.message_id}",
                style="danger",
            ),
            InlineKeyboardButton(
                text=t(lang, "spam.not_spam_button"),
                callback_data=f"mark_as_not_spam:{pending_id}",
                style="success",
            ),
        ]
    else:
        row = [
            InlineKeyboardButton(
                text=t(lang, "spam.not_spam_confirm"),
                callback_data=f"mark_as_not_spam:{pending_id}",
                style="success",
            ),
        ]
    return InlineKeyboardMarkup(inline_keyboard=[row])


def format_missing_permission_message(
    chat_title: str,
    permission_name: str,
    chat_username: Optional[str] = None,
    *,
    lang: str = "en",
) -> str:
    """Format message about missing bot permissions for admins."""
    perm_key = (
        "spam.permission_delete_action"
        if ("delete" in permission_name.lower() or "удал" in permission_name.lower())
        else "spam.permission_ban_action"
    )
    action_description = t(lang, perm_key)

    group_display = format_chat_or_channel_display(
        chat_title, chat_username, t(lang, "common.group")
    )
    return t(
        lang,
        "spam.no_permission",
        action=action_description,
        permission=permission_name,
        group=group_display,
    ) + t(lang, "spam.setup_guide_link", url=get_setup_guide_url())


async def handle_permission_error(
    error: Exception,
    chat_id: int,
    admin_ids: list[int] | None,
    group_title: str | None,
    permission_name: str,
    action_description: str,
    group_username: Optional[str] = None,
    *,
    lang: str = "en",
) -> bool:
    """Detect permission error, notify admins, return True if it was a permission error."""
    if not isinstance(error, TelegramBadRequest):
        return False

    error_message = str(error).lower()
    is_permission_error = (
        "not enough rights" in error_message
        or "need administrator rights" in error_message
        or "chat admin required" in error_message
        or "can_delete_messages" in error_message
        or "can_restrict_members" in error_message
        or "message can't be deleted" in error_message
    )

    if is_permission_error:
        logger.warning(
            f"Cannot {action_description} in chat {chat_id}: {error}",
            exc_info=True,
        )
        await set_no_rights_detected_at(chat_id)
        if admin_ids:
            try:
                display_title = group_title or str(chat_id)
                group_msg_tpl = t(
                    lang,
                    "spam.group_no_permission",
                    mention="{mention}",
                    permission=permission_name,
                )
                await notify_admins_with_fallback_and_cleanup(
                    bot,
                    admin_ids,
                    chat_id,
                    private_message=format_missing_permission_message(
                        display_title, permission_name, group_username, lang=lang
                    ),
                    group_message_template=group_msg_tpl
                    + t(lang, "spam.setup_guide_link", url=get_setup_guide_url()),
                    cleanup_if_group_fails=True,
                    parse_mode="HTML",
                )
            except Exception as notify_exc:
                logger.warning(
                    f"Failed to notify admins about missing rights for {action_description}: {notify_exc}"
                )
        return True

    return False


def format_admin_notification_message(
    context: MessageNotificationContext,
    all_admins_delete: bool,
    reason: str | None = None,
    *,
    lang: str = "en",
) -> str:
    """Format spam notification text for admins."""
    if context.effective_user_id is None:
        return t(lang, "spam.error_no_user")

    group_display = format_chat_or_channel_display(
        context.chat_title, context.chat_username, t(lang, "common.group")
    )
    violator_display = format_chat_or_channel_display(
        context.violator_name, context.violator_username, t(lang, "common.user")
    )

    reason_text = (
        t(lang, "spam.reason_label", reason=html.escape(reason or "", quote=True))
        if reason
        else ""
    )

    admin_msg = (
        t(lang, "spam.notify_title")
        + t(lang, "spam.group_label", display=group_display)
        + t(lang, "spam.violator_label", display=violator_display)
        + t(lang, "spam.content_label", content=context.content_text)
        + f"{reason_text}{context.forward_source}\n"
    )

    if all_admins_delete:
        key = (
            "spam.destroyed_channel"
            if context.is_channel_sender
            else "spam.destroyed_user"
        )
        admin_msg += t(lang, key)
    else:
        link = context.message_link or get_project_channel_url()
        admin_msg += t(lang, "spam.message_link", link=link)
        admin_msg += t(lang, "spam.mode_tip")

    admin_msg += (
        "\n\n" + f'<a href="{get_spam_guide_url()}">' + t(lang, "spam.spam_guide_link")
    )

    return admin_msg


async def notify_admins(
    message: types.Message,
    all_admins_delete: bool,
    admin_ids: list[int],
    reason: str | None = None,
    message_context_result: Optional["MessageContextResult"] = None,
) -> bool:
    """Notify admins about spam. Returns True if at least one notification succeeded."""
    if not message.from_user:
        return False

    lang = "en"
    if admin_ids:
        first_admin = await get_admin(admin_ids[0])
        if first_admin and first_admin.language_code:
            from ..i18n import normalize_lang

            lang = normalize_lang(first_admin.language_code)
        else:
            from ..i18n import resolve_lang

            lang = resolve_lang(message.from_user, None)

    context = MessageNotificationContext.from_message(message)
    private_message = format_admin_notification_message(
        context, all_admins_delete, reason, lang=lang
    )

    pending_id = None
    if context.effective_user_id is not None:
        text = "[MEDIA_MESSAGE]"
        name = None
        bio = None
        linked_channel_fragment = None
        stories_context = None
        reply_context = None
        account_age_context = None
        if message_context_result:
            ctx = message_context_result.context
            text = message_context_result.message_text or "[MEDIA_MESSAGE]"
            name = ctx.name if ctx else None
            bio = ctx.bio if ctx else None
            if ctx:
                if ctx.linked_channel:
                    frag = ctx.linked_channel.get_fragment()
                    if frag:
                        linked_channel_fragment = frag
                if ctx.stories:
                    stories_context = ctx.stories.get_fragment("[EMPTY]")
                reply_context = ctx.reply
                if ctx.account_age:
                    account_age_context = ctx.account_age.get_fragment("[EMPTY]")
        pending_id = await insert_pending_spam_example(
            message.chat.id,
            message.message_id,
            context.effective_user_id,
            text=text,
            name=name,
            bio=bio,
            linked_channel_fragment=linked_channel_fragment,
            stories_context=stories_context,
            reply_context=reply_context,
            account_age_context=account_age_context,
        )

    keyboard = create_admin_notification_keyboard(
        message, all_admins_delete, pending_id, lang=lang
    )
    result = await notify_admins_with_fallback_and_cleanup(
        bot,
        admin_ids,
        message.chat.id,
        private_message,
        group_message_template=t(lang, "spam.group_message_template"),
        cleanup_if_group_fails=True,
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    return bool(result["notified_private"]) or bool(result["group_notified"])


async def handle_spam_message_deletion(
    message: types.Message, admin_ids: list[int]
) -> None:
    """Delete the spam message; notify admins on permission failure."""
    if not message.from_user:
        return

    try:

        @retry_on_network_error
        async def delete_spam_message():
            return await bot.delete_message(message.chat.id, message.message_id)

        await delete_spam_message()
        logger.info(
            f"Deleted spam message {message.message_id} in chat {message.chat.id}"
        )
    except TelegramBadRequest as e:
        lang = "en"
        if admin_ids:
            first_admin = await get_admin(admin_ids[0])
            from ..i18n import normalize_lang

            lang = (
                normalize_lang(first_admin.language_code)
                if first_admin and first_admin.language_code
                else "en"
            )
        perm_name = t(lang, "spam.permission_delete")
        if not await handle_permission_error(
            e,
            message.chat.id,
            admin_ids,
            message.chat.title,
            perm_name,
            "delete spam message",
            getattr(message.chat, "username", None),
            lang=lang,
        ):
            # Not a permission error, log as general error
            logger.warning(
                f"Could not delete spam message {message.message_id} in chat {message.chat.id}: {e}",
                exc_info=True,
            )


async def ban_user_for_spam(
    chat_id: int,
    user_id: int,
    admin_ids: list[int] | None = None,
    group_title: str | None = None,
) -> None:
    """Ban user/channel in chat and remove from approved_members."""
    try:

        @retry_on_network_error
        async def ban_spam_user():
            if user_id < 0:
                # It's a channel, use ban_chat_sender_chat
                return await bot.ban_chat_sender_chat(chat_id, sender_chat_id=user_id)
            return await bot.ban_chat_member(chat_id, user_id)

        await ban_spam_user()
        logger.info(f"Banned user {user_id} in chat {chat_id} for spam")
    except TelegramBadRequest as e:
        lang = "en"
        if admin_ids:
            first_admin = await get_admin(admin_ids[0])
            from ..i18n import normalize_lang

            lang = (
                normalize_lang(first_admin.language_code)
                if first_admin and first_admin.language_code
                else "en"
            )
        perm_name = t(lang, "spam.permission_ban")
        if not await handle_permission_error(
            e,
            chat_id,
            admin_ids,
            group_title,
            perm_name,
            "ban user",
            lang=lang,
        ):
            # Not a permission error, log as general error
            logger.warning(
                f"Failed to ban user {user_id} in chat {chat_id}: {e}", exc_info=True
            )
    except Exception as e:
        logger.warning(
            f"Failed to ban user {user_id} in chat {chat_id}: {e}", exc_info=True
        )
    try:
        await remove_member_from_group(user_id, chat_id)
    except Exception as e:
        logger.warning(
            f"Failed to remove user {user_id} from approved_members: {e}", exc_info=True
        )


def build_spam_block_notification_message(
    context: MessageNotificationContext,
    reason: str | None = None,
    *,
    lang: str = "en",
) -> str:
    """Build notification message for MCP spam notifications to spammers/channel admins."""
    from ..common.utils import load_config

    config = load_config()
    project_website = config["system"]["project_website"]
    project_channel = get_project_channel_url()

    entity_display = format_chat_or_channel_display(
        context.entity_name, context.entity_username, t(lang, "common.channel")
    )
    entity_type_key = (
        "spam.entity_channel"
        if context.entity_type == "канале"
        else "spam.entity_group"
    )
    entity_type = t(lang, entity_type_key)
    notification_msg = t(
        lang,
        "spam.blocked_comment",
        entity_type=entity_type,
        entity_display=entity_display,
        content=context.content_text,
    )

    if reason:
        notification_msg += t(
            lang,
            "spam.block_reason",
            reason=html.escape(reason, quote=True),
        )

    notification_msg += t(
        lang,
        "spam.site_channel",
        website=project_website,
        channel=project_channel,
    )

    return notification_msg


async def send_mcp_message_to_user(
    *,
    user_id: int,
    username: Optional[str],
    message: str,
    message_type: str,
) -> bool:
    client = get_mcp_client()
    chat_identifier = f"@{username}" if username else str(user_id)
    log_extra = {
        "user_id": user_id,
        "username": username,
        "chat_identifier": chat_identifier,
        "message_type": message_type,
    }
    try:
        await client.call_tool(
            "send_message",
            arguments={
                "chat_id": chat_identifier,
                "message": message,
                "parse_mode": "html",
            },
        )
        logger.info("Sent MCP spam notification", extra=log_extra)
        return True
    except McpHttpError as e:
        logger.warning(
            "Failed to send MCP message",
            extra={**log_extra, "error": str(e)},
            exc_info=True,
        )
        return False
    except Exception as e:
        logger.error(
            "Unexpected error sending MCP message",
            extra={**log_extra, "error": str(e)},
            exc_info=True,
        )
        return False


async def notify_spam_contacts_via_mcp(
    message: types.Message,
    reason: str | None = None,
    message_context_result: Optional["MessageContextResult"] = None,
) -> None:
    """Send MCP promotional notifications to spammers and spamming channel admins."""
    channel_users = (
        message_context_result.channel_users if message_context_result else None
    )
    context = MessageNotificationContext.from_message(message)
    notification_msg = build_spam_block_notification_message(context, reason)

    # Check if this is a channel sender
    is_channel_sender = (
        message.sender_chat is not None and message.sender_chat.id != message.chat.id
    )

    if is_channel_sender and channel_users:
        # For channel senders, send to channel admins (filter out bots)
        admin_count = 0
        for user in channel_users:
            if user.get("bot", True):
                continue  # Skip bots

            user_id = user.get("id")
            username = user.get("username")

            if user_id:
                success = await send_mcp_message_to_user(
                    user_id=user_id,
                    username=username,
                    message=notification_msg,
                    message_type="spammer_channel_admin_notification",
                )
                if success:
                    admin_count += 1

        logger.info(
            f"Sent spam notifications to {admin_count} channel admins",
            extra={
                "channel_id": message.sender_chat.id if message.sender_chat else None,
                "total_admins": len(
                    [u for u in channel_users if not u.get("bot", True)]
                ),
                "successful_notifications": admin_count,
            },
        )

    elif not is_channel_sender and message.from_user:
        # For human senders only - never use message.from_user for channel posts
        # (Telegram uses Channel Bot 136817688 as from_user for channel messages)
        user_id = message.from_user.id
        username = getattr(message.from_user, "username", None)
        success = await send_mcp_message_to_user(
            user_id=user_id,
            username=username,
            message=notification_msg,
            message_type="spammer_user_notification",
        )

        if not success:
            return
