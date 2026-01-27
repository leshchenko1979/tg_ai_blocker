import logging

from aiogram import types

from ..common.bot import bot
from ..spam.context_collector import collect_sender_context
from ..spam.spam_classifier import is_spam
from ..spam.context_types import SpamClassificationContext, UserContext
from ..common.tracking import track_group_event
from ..common.utils import retry_on_network_error
from ..database import (
    APPROVE_PRICE,
    DELETE_PRICE,
    add_member,
    get_group,
    is_member_in_group,
)
from .dp import dp
from .handle_spam import handle_spam
from .try_deduct_credits import try_deduct_credits
from .updates_filter import filter_handle_message

logger = logging.getLogger(__name__)


def determine_effective_user_id(message: types.Message) -> int | None:
    """
    Determine the effective user ID for moderation.
    For channel messages (sender_chat), use channel ID unless it's the group itself (anonymous admin).
    For regular users, use their user ID.
    """
    if message.sender_chat and message.sender_chat.id != message.chat.id:
        return message.sender_chat.id
    elif message.from_user:
        return message.from_user.id
    return None


async def validate_group_and_permissions(chat_id: int, user_id: int):
    """
    Get group and perform early permission checks.

    Returns:
        tuple: (group, error_reason) where error_reason is None if valid
    """
    group, group_error = await get_and_check_group(chat_id)
    if group_error:
        return None, group_error

    assert group is not None

    # Check if sender is an admin - skip immediately
    if user_id in group.admin_ids:
        await track_group_event(
            chat_id, "message_from_admin_skipped", {"user_id": user_id}
        )
        return group, "message_from_admin_skipped"

    # Check if sender is approved
    if await check_known_member(chat_id, user_id):
        return group, "message_known_member_skipped"

    return group, None


async def check_message_eligibility(message: types.Message) -> tuple[bool, str]:
    """
    Check if message should be skipped based on various criteria.

    Returns:
        tuple: (should_skip, reason)
    """
    logger.debug(
        f"sender_chat={getattr(message, 'sender_chat', None)}, "
        f"chat.linked_chat_id={getattr(message.chat, 'linked_chat_id', None)}"
    )
    return await check_skip_channel_bot_message(message)


async def analyze_message_content(
    message: types.Message, group
) -> tuple[float | None, str | None, str, bool]:
    """
    Analyze message content for spam.

    Returns:
        tuple: (spam_score, bio, reason, is_story)
    """
    message_text, forward_info, is_story = build_forward_info(message)
    spam_score, bio, reason = await get_spam_score_and_bio(
        message, message_text, group, is_story
    )
    return spam_score, bio, reason, is_story


async def process_moderation_result(
    chat_id: int,
    user_id: int,
    spam_score: float,
    message: types.Message,
    admin_ids: list[int],
    reason: str,
) -> str:
    """
    Process the spam analysis result and track it.

    Returns:
        str: Processing result identifier
    """
    await track_spam_check_result(chat_id, user_id, spam_score, message_text="", bio="")
    return await process_spam_or_approve(
        chat_id, user_id, spam_score, message, admin_ids, reason
    )


@dp.message(filter_handle_message)
async def handle_moderated_message(message: types.Message) -> str:
    """
    Handles all messages in moderated groups.
    Forwards, especially stories, are treated as spam.
    """
    try:
        # Determine effective user ID for moderation
        user_id = determine_effective_user_id(message)
        if user_id is None:
            return "message_no_user_info"

        chat_id = message.chat.id

        # Validate group and check permissions (early exits)
        group, permission_error = await validate_group_and_permissions(chat_id, user_id)
        if permission_error:
            return permission_error

        assert group is not None  # At this point group should not be None

        # Check if message should be skipped
        skip, reason = await check_message_eligibility(message)
        if skip:
            return reason

        # Analyze message content for spam
        spam_score, bio, reason, is_story = await analyze_message_content(
            message, group
        )

        if spam_score is None:
            logger.warning("Failed to get spam score")
            return "message_spam_check_failed"

        # Process and track the moderation result
        return await process_moderation_result(
            chat_id, user_id, spam_score, message, group.admin_ids, reason
        )

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

        admin_id = admin.user.id
        try:

            @retry_on_network_error
            async def send_instruction():
                return await bot.send_message(admin_id, instruction, parse_mode="HTML")

            await send_instruction()
            notified_admins.append(admin_id)
        except Exception as e:
            logger.warning(
                f"Не удалось отправить инструкцию админу {admin_id}: {e}",
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


async def check_skip_channel_bot_message(message) -> tuple[bool, str]:
    """
    Проверяет, нужно ли пропустить сообщение от channel bot (sender_chat) в обсуждении канала.
    Возвращает (True, reason) если нужно пропустить, иначе (False, '').
    """
    linked_chat_id = getattr(message.chat, "linked_chat_id", None)
    if message.sender_chat:
        # Проверяем, если сообщение отправлено "от имени группы" (админ постит как группа)
        if message.sender_chat.id == message.chat.id:
            logger.debug(
                f"Skip moderation for message {message.message_id} "
                f"from admin posting as group {message.sender_chat.id} "
                f"in chat {message.chat.id}"
            )
            return True, "message_from_group_admin_skipped"

        # Если linked_chat_id уже есть и подходит — не делаем запрос к API
        if linked_chat_id and message.sender_chat.id == linked_chat_id:
            logger.debug(
                f"Skip moderation for message {message.message_id} "
                f"from channel bot {message.sender_chat.id} "
                f"in discussion group {message.chat.id}"
            )
            return True, "message_from_channel_bot_skipped"

        if (
            not linked_chat_id
            and getattr(message.chat, "type", None) == "supergroup"
            and getattr(message.sender_chat, "type", None) == "channel"
        ):
            try:
                chat_info = await bot.get_chat(message.chat.id)
                linked_chat_id = getattr(chat_info, "linked_chat_id", None)
                logger.debug(f"fetched linked_chat_id via API: {linked_chat_id}")

            except Exception as e:
                logger.warning(f"failed to fetch linked_chat_id via API: {e}")

            if linked_chat_id and message.sender_chat.id == linked_chat_id:
                logger.debug(
                    f"Skip moderation for message {message.message_id} "
                    f"from channel bot {message.sender_chat.id} "
                    f"in discussion group {message.chat.id} (with fallback)"
                )
                return True, "message_from_channel_bot_skipped"

    return False, ""


def build_forward_info(message) -> tuple[str, list[str], bool]:
    """
    Собирает информацию о пересылках, канале и сторис для сообщения.
    Возвращает (message_text, forward_info, is_story).
    """
    message_text = message.text or message.caption or "[MEDIA_MESSAGE]"
    forward_info = []
    is_story = False

    if message.forward_from:
        forward_info.append(f"Forwarded from user: {message.forward_from.full_name}")

    if message.forward_from_chat:
        forward_info.append(f"Forwarded from chat: {message.forward_from_chat.title}")

    story_obj = getattr(message, "story", None)

    if story_obj:
        story_chat = getattr(getattr(story_obj, "chat", None), "title", "Unknown")
        story_username = getattr(getattr(story_obj, "chat", None), "username", "")
        forward_info.append(f"Forwarded story from: {story_chat} (@{story_username})")
        is_story = True

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

    return message_text, forward_info, is_story


async def get_and_check_group(chat_id):
    group = await get_group(chat_id)

    if not group:
        logger.error(f"Group not found for chat {chat_id}")
        return None, "error_message_group_not_found"

    if not group.moderation_enabled:
        await track_group_event(chat_id, "message_skipped_moderation_disabled", {})
        return None, "message_moderation_disabled"

    return group, None


async def check_known_member(chat_id, user_id):
    if await is_member_in_group(chat_id, user_id):
        await track_group_event(
            chat_id, "message_skipped_known_member", {"user_id": user_id}
        )
        return True
    return False


async def get_spam_score_and_bio(message, message_text, group, is_story):
    if is_story:
        return 100, None, "Story forward"

    bio = None
    name = "Unknown"
    sender_context = None
    reply_context = None
    admin_ids = group.admin_ids

    # Extract reply context if this is a reply
    if message.reply_to_message:
        reply_context = (
            message.reply_to_message.text
            or message.reply_to_message.caption
            or "[MEDIA_MESSAGE]"
        )

    # Collect sender context using unified collector
    sender_context = await collect_sender_context(message, message.chat.id)

    # Handle context based on sender type
    if isinstance(sender_context, UserContext):
        # User sender - context is UserContext
        name = message.from_user.full_name if message.from_user else "Unknown"
        bio = None
        try:
            user_with_bio = await bot.get_chat(message.from_user.id)
            bio = user_with_bio.bio if user_with_bio else None
        except Exception:
            pass
    elif isinstance(sender_context, SpamClassificationContext):
        # Channel sender - context is already SpamClassificationContext
        name = sender_context.name or "Channel"
        bio = sender_context.bio

    # Create classification context
    if isinstance(sender_context, UserContext):
        # User sender - construct context from UserContext
        context = SpamClassificationContext(
            name=name,
            bio=bio,
            linked_channel=sender_context.linked_channel,
            stories=sender_context.stories,
            reply=reply_context,
            account_age=sender_context.account_info,
        )
    else:
        # Channel sender - context is already SpamClassificationContext, just add reply
        context = sender_context
        context.reply = reply_context

    spam_score, reason = await is_spam(
        comment=message_text,
        admin_ids=admin_ids,
        context=context,
    )
    return spam_score, bio, reason


async def track_spam_check_result(
    chat_id, user_id, spam_score, message_text, bio, reason=None
):
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
            "reason": reason,
        },
    )


async def process_spam_or_approve(
    chat_id, user_id, spam_score, message, admin_ids, reason
):
    if spam_score > 50:
        if await try_deduct_credits(chat_id, DELETE_PRICE, "delete spam"):
            await handle_spam(message, admin_ids, reason)
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
