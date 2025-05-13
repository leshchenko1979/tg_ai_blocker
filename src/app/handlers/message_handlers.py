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
async def handle_moderated_message(message: types.Message):
    """Обработчик всех сообщений в модерируемых группах"""
    try:
        if not message.from_user:
            return "message_no_user_info"

        chat_id = message.chat.id
        user_id = message.from_user.id

        # Получаем текст сообщения или описание медиа
        message_text = message.text or message.caption or "[MEDIA_MESSAGE]"

        # Add forwarded message info to the text for better spam detection
        if message.forward_from or message.forward_from_chat or message.story:
            forward_info = []
            if message.forward_from:
                forward_info.append(
                    f"Forwarded from user: {message.forward_from.full_name}"
                )
            if message.forward_from_chat:
                forward_info.append(
                    f"Forwarded from chat: {message.forward_from_chat.title}"
                )
            if message.story:
                forward_info.append(
                    f"Forwarded story from: {message.story.chat.title} (@{message.story.chat.username})"
                )
                # Automatically treat forwarded stories as spam
                spam_score = 100

            message_text = f"{message_text}\n[FORWARD_INFO]: {' | '.join(forward_info)}"

        # Track message processing start
        await track_group_event(
            chat_id,
            "message_processing_started",
            {
                "user_id": user_id,
                "message_text": message_text,
                "is_forwarded": bool(
                    message.forward_from or message.forward_from_chat or message.story
                ),
            },
        )

        # Получаем информацию о группе из базы данных
        group = await get_group(chat_id)
        if not group:
            logger.error(f"Group not found for chat {chat_id}")
            return "error_message_group_not_found"

        if not group.moderation_enabled:
            # Трекинг пропуска из-за отключенной модерации
            await track_group_event(
                chat_id,
                "message_skipped_moderation_disabled",
                {},
            )
            return "message_moderation_disabled"

        is_known_member = await is_member_in_group(chat_id, user_id)

        if is_known_member:
            # Трекинг пропуска известного пользователя
            await track_group_event(
                chat_id,
                "message_skipped_known_member",
                {"user_id": user_id},
            )
            return "message_known_member_skipped"

        user = message.from_user
        user_with_bio = await bot.get_chat(user.id)
        bio = user_with_bio.bio if user_with_bio else None

        # Используем список администраторов из базы данных
        admin_ids = group.admin_ids

        spam_score = await is_spam(
            comment=message_text, name=user.full_name, bio=bio, admin_ids=admin_ids
        )

        if spam_score is None:
            logger.warning("Failed to get spam score")
            return "message_spam_check_failed"

        # Трекинг результата проверки на спам
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

            # Трекинг одобрения пользователя
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
        # Трекинг необработанной ошибки
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
        channel_title = message.chat.title or "(без названия)"
        instruction = (
            f"❗️ Бот был добавлен в канал <b>{channel_title}</b>, а не в группу с комментариями к нему.\n\n"
            "Чтобы бот работал корректно, добавьте его в группу, "
            "которая привязана к вашему каналу как группа для комментариев.\n\n"
            "После этого бот сможет модерировать комментарии к вашим постам.\n\n"
            "Подробнее: https://t.me/ai_antispam/14"
        )
        notified_admins = []
        try:
            admins = await bot.get_chat_administrators(message.chat.id)
        except Exception as e:
            logger.warning(
                f"Не удалось получить админов канала {message.chat.id}: {e}",
                exc_info=True,
            )
            admins = []
        for admin in admins:
            if admin.user.is_bot:
                continue
            admin_info = await get_admin(admin.user.id)
            if admin_info:
                try:
                    await bot.send_message(
                        admin.user.id, instruction, parse_mode="HTML"
                    )
                    notified_admins.append(admin.user.id)
                except Exception as e:
                    logger.warning(
                        f"Не удалось отправить инструкцию админу {admin.user.id}: {e}",
                        exc_info=True,
                    )
        await bot.leave_chat(message.chat.id)
        logger.info(f"Bot left channel {message.chat.id} after channel_post event.")
        mp.track(
            message.chat.id,
            "channel_post_received_and_left",
            {
                "chat_title": message.chat.title,
                "chat_id": message.chat.id,
                "notified_admins": notified_admins,
            },
        )
        return "channel_post_left_channel"
    except Exception as e:
        logger.error(f"Error handling channel_post: {e}", exc_info=True)
        return "channel_post_error"
