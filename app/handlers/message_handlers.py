from aiogram import types

from common.bot import bot
from common.database import (
    APPROVE_PRICE,
    DELETE_PRICE,
    SKIP_PRICE,
    add_unique_user,
    deduct_credits_from_admins,
    ensure_group_exists,
    get_user,
    is_moderation_enabled,
    is_user_in_group,
    set_group_moderation,
)
from common.dp import dp
from common.mp import mp
from common.yandex_logging import get_yandex_logger, log_function_call
from handlers.updates_filter import filter_handle_message
from spam_classifier import is_spam
from stats import update_stats
from utils import config

logger = get_yandex_logger(__name__)


@log_function_call(logger)
async def try_deduct_credits(chat_id: int, amount: int, reason: str) -> bool:
    """
    Попытка списать звезды у админов. При неудаче отключает модерацию.

    Args:
        chat_id: ID чата
        amount: Количество звезд для списания
        reason: Причина списания для логов

    Returns:
        bool: True если списание успешно, False если нет
    """
    if amount == 0:  # Пропускаем бесплатные операции
        return True

    if not await deduct_credits_from_admins(chat_id, amount):
        logger.warning(f"No paying admins in chat {chat_id} for {reason}")
        await set_group_moderation(chat_id, False)
        # Уведомить админов об отключении модерации
        chat = await bot.get_chat(chat_id)
        admins = await bot.get_chat_administrators(chat_id)
        for admin in admins:
            if not admin.user.is_bot:
                await bot.send_message(
                    admin.user.id,
                    "Внимание, органическая форма жизни!\n\n"
                    f'Моя защита группы "{chat.title}" временно приостановлена '
                    "из-за истощения звездной энергии.\n\n"
                    "Пополни запас звезд командой /buy, чтобы я продолжил охранять "
                    "твоё киберпространство от цифровых паразитов!",
                )
        return False
    return True


@log_function_call(logger)
async def handle_spam(message_id: int, chat_id: int, user_id: int, text: str) -> None:
    """
    Обработка спам-сообщений в соответствии с настройками пользователя

    Args:
        message_id (int): ID сообщения
        chat_id (int): ID чата
        user_id (int): ID пользователя
        text (str): Текст сообщения
    """
    try:
        chat = await bot.get_chat(chat_id)
        group_name = chat.title

        # Регистрация события спама
        mp.track(
            chat_id,
            "spam_detected",
            {
                "message_id": message_id,
                "user_id": user_id,
                "text": text,
                "group_name": group_name,
            },
        )

        update_stats(chat_id, "processed")

        # Получаем админов и их настройки
        admins = await bot.get_chat_administrators(chat_id)
        all_admins_delete = True  # Флаг, что все админы в режиме удаления

        # Проверяем настройки каждого админа
        for admin in admins:
            if admin.user.is_bot:
                continue
            admin_user = await get_user(admin.user.id)
            if not admin_user or not admin_user.delete_spam:
                all_admins_delete = False
                break

        # Удаление сообщения только если все админы в режиме удаления
        if all_admins_delete:
            await bot.delete_message(chat_id, message_id)
            logger.info(f"Deleted spam message {message_id} in chat {chat_id}")
            update_stats(chat_id, "deleted")

        # Уведомление администраторов
        try:
            link = f"https://t.me/c/{chat_id}/{message_id}"

            for admin in admins:
                if admin.user.is_bot:
                    continue

                admin_user = await get_user(admin.user.id)
                admin_deletes = admin_user and admin_user.delete_spam

                admin_msg = (
                    f"⚠️ ТРЕВОГА! Обнаружено вторжение в {group_name} (@{chat.username})!\n"
                    f"Нарушитель: {user_id} (@{(await bot.get_chat_member(chat_id, user_id)).user.username})\n"
                    f"Содержание угрозы:\n\n{text}\n\n"
                    f"Принятые меры: "
                )

                if all_admins_delete:
                    admin_msg += "Вредоносное сообщение уничтожено"
                else:
                    admin_msg += f"Ссылка на сообщение: {link}\n\n"
                    if admin_deletes:
                        admin_msg += "(Сообщение не удалено, так как не все администраторы включили режим удаления)"

                try:
                    await bot.send_message(admin.user.id, admin_msg)
                except Exception as e:
                    logger.warning(f"Failed to notify admin {admin.user.id}: {e}")

        except Exception as e:
            logger.error(
                f"Failed to notify admins in chat {chat_id}: {e}", exc_info=True
            )
            raise

    except Exception as e:
        logger.error(f"Error handling spam: {e}", exc_info=True)
        raise


@dp.message(filter_handle_message)
async def handle_message(message: types.Message):
    """Обработчик всех текстовых сообщений"""
    logger.debug("handle_message called")
    try:
        if not message.text:
            logger.debug(f"Ignoring non-text message from {message.from_user.id}")
            return

        chat_id = message.chat.id
        user_id = message.from_user.id

        logger.info(
            f"Processing message {message.message_id} from {user_id} in {chat_id}"
        )

        # Получаем список админов и сохраняем группу если она новая
        admins = await bot.get_chat_administrators(chat_id)
        admin_ids = [admin.user.id for admin in admins if not admin.user.is_bot]
        await ensure_group_exists(chat_id, admin_ids)

        # Проверяем включена ли модерация
        if not await is_moderation_enabled(chat_id):
            logger.info(f"Moderation is disabled for chat {chat_id}, skipping")
            return

        # Проверяем, есть ли пользователь в списке известных
        is_known_user = await is_user_in_group(chat_id, user_id)

        if is_known_user:
            if await try_deduct_credits(chat_id, SKIP_PRICE, "skip check"):
                update_stats(chat_id, "processed")
            return

        # Для новых пользователей выполняем проверку
        user = message.from_user

        # Get user's bio through API call
        user_info = await bot.get_chat(user.id)
        bio = user_info.bio if user_info else None

        spam_score = await is_spam(
            comment=message.text, name=user.full_name, bio=bio, user_id=user.id
        )
        logger.info(
            f"Spam score: {spam_score}",
            extra={
                "chat_id": chat_id,
                "spam_score": spam_score,
                "user_name": user.full_name,
                "user_bio": bio,
            },
        )

        if spam_score > 50:
            if await try_deduct_credits(chat_id, DELETE_PRICE, "delete spam"):
                await handle_spam(message.message_id, chat_id, user_id, message.text)
            return

        # Если сообщение не спам
        if await try_deduct_credits(chat_id, APPROVE_PRICE, "approve user"):
            await add_unique_user(chat_id, user_id)
            update_stats(chat_id, "processed")

    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
        mp.track(chat_id, "unhandled_exception", {"exception": str(e)})
        raise
