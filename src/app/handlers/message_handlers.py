import logging

from aiogram import types

from ..common.bot import bot
from ..common.mp import mp
from ..common.spam_classifier import is_spam
from ..common.tracking import track_group_event
from ..database import (
    APPROVE_PRICE,
    DELETE_PRICE,
    add_member,
    get_admin,
    get_group,
    is_member_in_group,
)
from .dp import dp
from .handle_spam import handle_spam
from .try_deduct_credits import try_deduct_credits
from .updates_filter import filter_handle_message

logger = logging.getLogger(__name__)


@dp.message(filter_handle_message)
async def handle_moderated_message(message: types.Message) -> str:
    """
    Handles all messages in moderated groups.
    Forwards, especially stories, are treated as spam.
    """
    try:
        if not message.from_user:
            return "message_no_user_info"

        chat_id = message.chat.id
        user_id = message.from_user.id

        # Get message text or media caption
        message_text = message.text or message.caption or "[MEDIA_MESSAGE]"

        # Build forward and channel info
        forward_info = []
        is_story = False
        if message.forward_from:
            forward_info.append(
                f"Forwarded from user: {message.forward_from.full_name}"
            )
        if message.forward_from_chat:
            forward_info.append(
                f"Forwarded from chat: {message.forward_from_chat.title}"
            )
        story_obj = getattr(message, "story", None)
        if story_obj:
            story_chat = getattr(getattr(story_obj, "chat", None), "title", "Unknown")
            story_username = getattr(getattr(story_obj, "chat", None), "username", "")
            forward_info.append(
                f"Forwarded story from: {story_chat} (@{story_username})"
            )
            is_story = True

        # Add channel info if message is from a channel
        if message.sender_chat and message.sender_chat.type == "channel":
            channel_title = message.sender_chat.title
            channel_username = (
                f" (@{message.sender_chat.username})"
                if message.sender_chat.username
                else ""
            )
            forward_info.append(f"Posted by channel: {channel_title}{channel_username}")

        if forward_info:
            message_text = f"{message_text}\n[FORWARD_INFO]: {' | '.join(forward_info)}"

        # Track message processing start
        await track_group_event(
            chat_id,
            "message_processing_started",
            {
                "user_id": user_id,
                "message_text": message_text,
                "is_forwarded": bool(forward_info),
            },
        )

        # Get group info
        group = await get_group(chat_id)
        if not group:
            logger.error(f"Group not found for chat {chat_id}")
            return "error_message_group_not_found"
        if not group.moderation_enabled:
            await track_group_event(chat_id, "message_skipped_moderation_disabled", {})
            return "message_moderation_disabled"

        if await is_member_in_group(chat_id, user_id):
            await track_group_event(
                chat_id, "message_skipped_known_member", {"user_id": user_id}
            )
            return "message_known_member_skipped"

        # --- Early return for stories ---
        if is_story:
            spam_score = 100
            bio = None
        else:
            user = message.from_user
            user_with_bio = await bot.get_chat(user.id)
            bio = user_with_bio.bio if user_with_bio else None
            admin_ids = group.admin_ids
            spam_score = await is_spam(
                comment=message_text, name=user.full_name, bio=bio, admin_ids=admin_ids
            )
            if spam_score is None:
                logger.warning("Failed to get spam score")
                return "message_spam_check_failed"

        # Track spam check result
        await track_group_event(
            chat_id,
            "spam_check_result",
            {
                "chat_id": chat_id,
                "user_id": user_id,
                "spam_score": spam_score,
                "is_spam": spam_score > 50,
                "message_text": message_text,
                "user_bio": bio,
            },
        )

        if spam_score > 50:
            if await try_deduct_credits(chat_id, DELETE_PRICE, "delete spam"):
                await handle_spam(message)
                return "message_spam_deleted"
        elif await try_deduct_credits(chat_id, APPROVE_PRICE, "approve user"):
            await add_member(chat_id, user_id)
            await track_group_event(
                chat_id,
                "user_approved",
                {
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "spam_score": spam_score,
                },
            )
            return "message_user_approved"

        return "message_insufficient_credits"

    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
        await track_group_event(
            chat_id,
            "error_message_processing",
            {
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        raise


@dp.channel_post()
async def handle_channel_post(message: types.Message):
    """
    Обрабатывает сообщения типа channel_post (бот добавлен в канал, а не в группу с комментариями).
    Уведомляет администратора канала (если найден в базе) и отписывает бота от канала.
    """
    try:
        await send_wrong_channel_addition_instruction(message.chat, bot)
        return "channel_post_left_channel"
    except Exception as e:
        logger.error(f"Error handling channel_post: {e}", exc_info=True)
        return "channel_post_error"


async def send_wrong_channel_addition_instruction(chat, bot):
    """
    Отправляет инструкцию администраторам канала, если бот был добавлен в канал, а не в группу обсуждений.
    Вставляет ссылку на обсуждение, если оно есть.
    """
    channel_title = chat.title or "(без названия)"
    discussion_link = None
    linked_chat_id = getattr(chat, "linked_chat_id", None)
    if linked_chat_id is not None:
        try:
            discussion_chat = await bot.get_chat(int(linked_chat_id))
            if username := getattr(discussion_chat, "username", None):
                discussion_link = f"https://t.me/{username}"
        except Exception as e:
            logger.warning(
                f"Не удалось получить связанную группу обсуждения: {e}", exc_info=True
            )
    instruction = (
        f"❗️ Бот был добавлен в канал <b>{channel_title}</b>, а не в группу обсуждений.\n\n"
        "Для корректной работы бота, добавьте его в группу обсуждений, "
        "привязанную к вашему каналу.\n\n"
        "После этого бот сможет защищать ваши посты от спама в комментариях.\n\n"
        + (
            f'<b>Группа обсуждений:</b> <a href="{discussion_link}">перейти в группу</a>\n\n'
            if discussion_link
            else ""
        )
        + "Подробнее: https://t.me/ai_antispam/14"
    )
    notified_admins = []
    try:
        admins = await bot.get_chat_administrators(chat.id)
    except Exception as e:
        logger.warning(
            f"Не удалось получить админов канала {chat.id}: {e}",
            exc_info=True,
        )
        admins = []
    for admin in admins:
        if admin.user.is_bot:
            continue
        try:
            await bot.send_message(admin.user.id, instruction, parse_mode="HTML")
            notified_admins.append(admin.user.id)
        except Exception as e:
            logger.warning(
                f"Не удалось отправить инструкцию админу {admin.user.id}: {e}",
                exc_info=True,
            )
    await bot.leave_chat(chat.id)
    logger.info(f"Bot left channel {chat.id} after notification.")
    await track_group_event(
        chat.id,
        "channel_admins_notified_wrong_addition",
        {
            "chat_title": chat.title,
            "chat_id": chat.id,
            "notified_admins": notified_admins,
        },
    )
