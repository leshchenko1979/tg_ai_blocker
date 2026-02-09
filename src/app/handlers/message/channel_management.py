"""
Channel management and administration.

This module handles channel-related operations including notifications
to administrators when the bot is incorrectly added to channels.
"""

import logging

from aiogram import types
from aiogram.client.bot import Bot

from ...common.utils import format_chat_or_channel_display, retry_on_network_error

logger = logging.getLogger(__name__)


async def handle_channel_post(message: types.Message) -> str:
    """
    Handle channel posts when bot is incorrectly added to a channel.

    When the bot is added to a channel instead of a discussion group,
    it notifies channel administrators with instructions and leaves the channel.

    Args:
        message: The channel post message

    Returns:
        Result identifier string for logging
    """
    try:
        from ...common.bot import bot

        await notify_channel_admins_and_leave(message.chat, bot)
        return "channel_post_left_channel"
    except Exception as e:
        logger.error(f"Error handling channel_post: {e}", exc_info=True)
        return "channel_post_error"


async def get_discussion_username(chat: types.Chat, bot: Bot) -> str | None:
    """
    Get the username of the linked discussion group.

    Args:
        chat: The channel chat object
        bot: The bot instance for API calls

    Returns:
        Username of discussion group if available, None otherwise
    """
    linked_chat_id = getattr(chat, "linked_chat_id", None)
    if linked_chat_id is not None:
        try:
            discussion_chat = await bot.get_chat(int(linked_chat_id))
            return getattr(discussion_chat, "username", None)
        except Exception as e:
            logger.warning(
                f"Failed to get linked discussion group {linked_chat_id}: {e}"
            )
    return None


def build_channel_instruction_message(
    channel_title: str,
    discussion_link: str | None,
    channel_username: str | None = None,
) -> str:
    """
    Build the instructional message for channel administrators.

    Args:
        channel_title: Title of the channel
        discussion_link: URL to the discussion group if available
        channel_username: Optional channel username without @

    Returns:
        Formatted HTML message with instructions
    """
    channel_display = format_chat_or_channel_display(
        channel_title, channel_username, "Канал"
    )
    base_instruction = (
        f"❗️ Бот был добавлен в канал <b>{channel_display}</b> вместо группы обсуждения.\n\n"
        "Для правильной работы бота добавьте его в группу обсуждения, связанную с вашим каналом.\n\n"
        "После этого бот сможет защищать ваши посты от спама в комментариях.\n\n"
    )

    if discussion_link:
        base_instruction += (
            f'<b>Discussion Group:</b> <a href="{discussion_link}">go to group</a>\n\n'
        )

    base_instruction += "Подробнее: https://t.me/ai_antispam/14"

    return base_instruction


async def notify_channel_admins(
    chat: types.Chat, instruction: str, bot: Bot
) -> list[int]:
    """
    Notify all non-bot administrators of the channel.

    Args:
        chat: The channel chat object
        instruction: The message to send to administrators
        bot: The bot instance for sending messages

    Returns:
        List of admin IDs that were successfully notified
    """
    notified_admins = []

    try:
        admins = await bot.get_chat_administrators(chat.id)
    except Exception as e:
        logger.warning(
            f"Failed to get channel admins for {chat.id}: {e}", exc_info=True
        )
        return notified_admins

    for admin in admins:
        if admin.user.is_bot:
            continue

        admin_id = admin.user.id
        try:

            @retry_on_network_error
            async def send_instruction() -> None:
                await bot.send_message(admin_id, instruction, parse_mode="HTML")

            await send_instruction()
            notified_admins.append(admin_id)
        except Exception as e:
            logger.warning(
                f"Failed to send instruction to admin {admin_id}: {e}", exc_info=True
            )

    return notified_admins


async def notify_channel_admins_and_leave(chat: types.Chat, bot: Bot) -> None:
    """
    Notify channel administrators about incorrect bot placement and leave the channel.

    When the bot is added to a channel instead of a discussion group, this function:
    1. Creates an instructional message for administrators
    2. Attempts to find and notify all channel administrators
    3. Leaves the channel to prevent confusion

    Args:
        chat: The channel chat object
        bot: The bot instance for sending messages and leaving
    """
    channel_title = chat.title or "(untitled)"
    channel_username = getattr(chat, "username", None)
    discussion_username = await get_discussion_username(chat, bot)

    discussion_link = (
        f"https://t.me/{discussion_username}" if discussion_username else None
    )
    instruction = build_channel_instruction_message(
        channel_title, discussion_link, channel_username
    )

    notified_admins = await notify_channel_admins(chat, instruction, bot)

    await bot.leave_chat(chat.id)
    logger.info(
        f"Bot left channel {chat.id} after notifying {len(notified_admins)} admins."
    )
