import asyncio
import logging
from typing import cast

from aiogram import types

from ..common.bot import bot
from ..common.linked_channel import (
    LinkedChannelSummary,
    UserContext,
    collect_channel_summary_by_id,
    collect_linked_channel_summary,
)
from ..common.spam_classifier import is_spam
from ..common.stories import collect_user_stories
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


@dp.message(filter_handle_message)
async def handle_moderated_message(message: types.Message) -> str:
    """
    Handles all messages in moderated groups.
    Forwards, especially stories, are treated as spam.
    """
    try:
        # Determine effective user ID for moderation early
        # If message is from a channel (sender_chat is set), use channel ID
        # unless it's the group itself (anonymous admin)
        if message.sender_chat and message.sender_chat.id != message.chat.id:
            user_id = message.sender_chat.id
        elif message.from_user:
            user_id = message.from_user.id
        else:
            return "message_no_user_info"

        chat_id = message.chat.id

        # Get group early to check admin/approved status before expensive operations
        group, group_error = await get_and_check_group(chat_id)
        if group_error:
            return group_error

        assert group is not None

        # Check if sender is an admin - skip immediately without expensive operations
        if user_id in group.admin_ids:
            await track_group_event(
                chat_id, "message_from_admin_skipped", {"user_id": user_id}
            )
            return "message_from_admin_skipped"

        # Check if sender is approved - skip before expensive operations
        if await check_known_member(chat_id, user_id):
            return "message_known_member_skipped"

        logger.debug(
            f"sender_chat={getattr(message, 'sender_chat', None)}, "
            f"chat.linked_chat_id={getattr(message.chat, 'linked_chat_id', None)}"
        )
        skip, reason = await check_skip_channel_bot_message(message)
        if skip:
            return reason

        message_text, forward_info, is_story = build_forward_info(message)

        spam_score, bio, reason = await get_spam_score_and_bio(
            message, message_text, group, is_story
        )

        if spam_score is None:
            logger.warning("Failed to get spam score")
            return "message_spam_check_failed"

        await track_spam_check_result(chat_id, user_id, spam_score, message_text, bio)

        return await process_spam_or_approve(
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
    channel_fragment = None
    account_info_fragment = None
    stories_context = None
    reply_context = None
    admin_ids = group.admin_ids

    # Extract reply context if this is a reply
    if message.reply_to_message:
        reply_context = (
            message.reply_to_message.text
            or message.reply_to_message.caption
            or "[MEDIA_MESSAGE]"
        )

    # Check if message is from a sender_chat (channel) that is NOT the group itself
    if message.sender_chat and message.sender_chat.id != message.chat.id:
        # Channel sender
        subject_id = message.sender_chat.id
        name = message.sender_chat.title or "Channel"

        try:
            # Try to get channel description
            chat_info = await bot.get_chat(subject_id)
            bio = chat_info.description
        except Exception:
            pass

        try:
            summary = await collect_channel_summary_by_id(
                subject_id,
                user_reference=f"sender_chat_{subject_id}",
                username=message.sender_chat.username,
            )
            if summary:
                channel_fragment = summary.to_prompt_fragment()
        except Exception as exc:
            logger.info(
                "Failed to collect channel summary for sender_chat",
                extra={
                    "sender_chat_id": subject_id,
                    "error": str(exc),
                },
            )

    elif message.from_user:
        # User sender
        user = message.from_user
        name = user.full_name

        try:
            user_with_bio = await bot.get_chat(user.id)
            bio = user_with_bio.bio if user_with_bio else None
        except Exception:
            pass

        if getattr(message, "message_thread_id", None):
            # Only collect stories when user replies to a channel post (in discussion threads)
            # Run stories and linked channel collection in parallel for better performance
            stories_task = collect_user_stories(user.id, username=user.username)
            linked_channel_task = collect_linked_channel_summary(
                user.id, username=user.username
            )

            try:
                results = await asyncio.gather(
                    stories_task, linked_channel_task, return_exceptions=True
                )
                stories_result = results[0]
                user_context_result = results[1]

                # Handle stories result
                if isinstance(stories_result, Exception):
                    logger.info(
                        "Failed to collect user stories",
                        extra={
                            "user_id": user.id,
                            "username": user.username,
                            "error": str(stories_result),
                        },
                    )
                elif stories_result is not None:
                    stories_context = cast(str, stories_result)

                # Handle linked channel/user context result
                if isinstance(user_context_result, Exception):
                    logger.info(
                        "Failed to collect linked channel summary",
                        extra={
                            "user_id": user.id,
                            "username": user.username,
                            "error": str(user_context_result),
                        },
                    )
                else:
                    # user_context_result is not an Exception here
                    if user_context_result is not None:
                        user_context = cast(UserContext, user_context_result)
                        if user_context.linked_channel:
                            channel_fragment = (
                                user_context.linked_channel.to_prompt_fragment()
                            )
                        if user_context.account_info:
                            account_info_fragment = (
                                user_context.account_info.to_prompt_fragment()
                            )

            except Exception as exc:
                # Fallback in case gather itself fails
                logger.info(
                    "Failed to collect stories and linked channel data in parallel",
                    extra={
                        "user_id": user.id,
                        "username": user.username,
                        "error": str(exc),
                    },
                )

    spam_score, reason = await is_spam(
        comment=message_text,
        name=name,
        bio=bio,
        admin_ids=admin_ids,
        linked_channel_fragment=channel_fragment,
        stories_context=stories_context,
        reply_context=reply_context,
        account_age_context=account_info_fragment,
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
