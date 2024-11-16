from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

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
    """
    if amount == 0:
        return True

    success = await deduct_credits_from_admins(chat_id, amount)

    # Трекинг списания звезд
    mp.track(
        chat_id,
        "credits_deduction_attempt",
        {"chat_id": chat_id, "amount": amount, "reason": reason, "success": success},
    )

    if not success:
        logger.warning(f"No paying admins in chat {chat_id} for {reason}")
        await set_group_moderation(chat_id, False)

        # Трекинг отключения модерации
        mp.track(
            chat_id,
            "moderation_disabled_no_credits",
            {"chat_id": chat_id, "reason": reason, "required_amount": amount},
        )

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
    Обработка спам-сообщений
    """
    try:
        chat = await bot.get_chat(chat_id)
        group_name = chat.title
        link = f"https://t.me/{chat.username}/{message_id}"
        spammer_username = (await bot.get_chat_member(chat_id, user_id)).user.username

        # Трекинг обнаружения спама
        mp.track(
            chat_id,
            "spam_detected",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "user_id": user_id,
                "spammer_username": spammer_username,
                "message_length": len(text),
                "group_name": group_name,
            },
        )

        update_stats(chat_id, "processed")

        admins = await bot.get_chat_administrators(chat_id)
        all_admins_delete = True

        for admin in admins:
            if admin.user.is_bot:
                continue
            admin_user = await get_user(admin.user.id)
            if not admin_user or not admin_user.delete_spam:
                all_admins_delete = False
                break

        if all_admins_delete:
            await bot.delete_message(chat_id, message_id)
            logger.info(f"Deleted spam message {message_id} in chat {chat_id}")
            update_stats(chat_id, "deleted")

            # Трекинг удаления спама
            mp.track(
                chat_id,
                "spam_message_deleted",
                {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "user_id": user_id,
                    "auto_delete": True,
                },
            )

        # Уведомление администраторов...
        for admin in admins:
            if admin.user.is_bot:
                continue

            try:
                keyboard = None
                if not all_admins_delete:
                    keyboard = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="🗑️ Удалить",
                                    callback_data=f"spam_delete:{message_id}:{chat_id}",
                                ),
                                InlineKeyboardButton(
                                    text="✅ Не спам",
                                    callback_data=f"spam_ignore:{message_id}:{chat_id}",
                                ),
                            ]
                        ]
                    )

                admin_msg = (
                    f"⚠️ ТРЕВОГА! Обнаружено вторжение в {group_name} (@{chat.username})!\n"
                    f"Нарушитель: {user_id} (@{spammer_username})\n"
                    f"Содержание угрозы:\n\n{text}\n\n"
                )

                if all_admins_delete:
                    admin_msg += "Вредоносное сообщение уничтожено"
                else:
                    admin_msg += f"Ссылка на сообщение: {link}"
                    admin_msg += "\n(Выберите действие с сообщением)"

                await bot.send_message(admin.user.id, admin_msg, reply_markup=keyboard)

                # Трекинг уведомления админа
                mp.track(
                    admin.user.id,
                    "admin_spam_notification",
                    {
                        "admin_id": admin.user.id,
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "auto_delete": all_admins_delete,
                    },
                )

            except Exception as e:
                logger.warning(f"Failed to notify admin {admin.user.id}: {e}")
                # Трекинг ошибки уведомления
                mp.track(
                    admin.user.id,
                    "error_admin_notification",
                    {
                        "admin_id": admin.user.id,
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                    },
                )

    except Exception as e:
        logger.error(f"Error handling spam: {e}", exc_info=True)
        # Трекинг ошибки обработки спама
        mp.track(
            chat_id,
            "error_spam_handling",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        raise


@dp.message(filter_handle_message)
async def handle_message(message: types.Message):
    """Обработчик всех текстовых сообщений"""
    try:
        if not message.text:
            return

        chat_id = message.chat.id
        user_id = message.from_user.id

        # Трекинг начала обработки сообщения
        mp.track(
            chat_id,
            "message_processing_started",
            {
                "chat_id": chat_id,
                "user_id": user_id,
                "message_length": len(message.text),
            },
        )

        admins = await bot.get_chat_administrators(chat_id)
        admin_ids = [admin.user.id for admin in admins if not admin.user.is_bot]
        await ensure_group_exists(chat_id, admin_ids)

        if not await is_moderation_enabled(chat_id):
            # Трекинг пропуска из-за отключенной модерации
            mp.track(
                chat_id,
                "message_skipped_moderation_disabled",
                {"chat_id": chat_id, "user_id": user_id},
            )
            return

        is_known_user = await is_user_in_group(chat_id, user_id)

        if is_known_user:
            if await try_deduct_credits(chat_id, SKIP_PRICE, "skip check"):
                update_stats(chat_id, "processed")
                # Трекинг пропуска известного пользователя
                mp.track(
                    chat_id,
                    "message_skipped_known_user",
                    {"chat_id": chat_id, "user_id": user_id},
                )
            return

        user = message.from_user
        user_info = await bot.get_chat(user.id)
        bio = user_info.bio if user_info else None

        spam_score = await is_spam(
            comment=message.text, name=user.full_name, bio=bio, user_id=user.id
        )

        # Трекинг результата проверки на спам
        mp.track(
            chat_id,
            "spam_check_result",
            {
                "chat_id": chat_id,
                "user_id": user_id,
                "spam_score": spam_score,
                "is_spam": spam_score > 50,
                "message_length": len(message.text),
                "has_bio": bool(bio),
            },
        )

        if spam_score > 50:
            if await try_deduct_credits(chat_id, DELETE_PRICE, "delete spam"):
                await handle_spam(message.message_id, chat_id, user_id, message.text)
            return

        if await try_deduct_credits(chat_id, APPROVE_PRICE, "approve user"):
            await add_unique_user(chat_id, user_id)
            update_stats(chat_id, "processed")
            # Трекинг одобрения пользователя
            mp.track(
                chat_id,
                "user_approved",
                {"chat_id": chat_id, "user_id": user_id, "spam_score": spam_score},
            )

    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
        # Трекинг необработанной ошибки
        mp.track(
            chat_id,
            "error_message_processing",
            {
                "chat_id": chat_id,
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        raise
