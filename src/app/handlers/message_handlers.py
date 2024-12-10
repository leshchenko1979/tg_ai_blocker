from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..common.bot import bot
from ..common.mp import mp
from ..common.spam_classifier import is_spam
from ..common.yandex_logging import get_yandex_logger, log_function_call
from ..database import (
    APPROVE_PRICE,
    DELETE_PRICE,
    add_member,
    deduct_credits_from_admins,
    get_admin,
    is_member_in_group,
    is_moderation_enabled,
    set_group_moderation,
    update_group_admins,
)
from .dp import dp
from .updates_filter import filter_handle_message

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

        chat = await bot.get_chat(chat_id)
        admins = await bot.get_chat_administrators(chat_id)

        # Находим админа с наименьшим количеством звезд
        min_credits_admin = None
        min_credits = float("inf")

        for admin in admins:
            if admin.user.is_bot:
                continue
            admin_data = await get_admin(admin.user.id)
            if admin_data and admin_data.credits < min_credits:
                min_credits = admin_data.credits
                min_credits_admin = admin

        if min_credits_admin:
            bot_info = await bot.me()
            ref_link = (
                f"https://t.me/{bot_info.username}?start={min_credits_admin.user.id}"
            )

            # Отправляем сообщение в группу
            try:
                await bot.send_message(
                    chat_id,
                    "⚠️ *Внимание! Защита группы деактивирована*\n\n"
                    "Нейромодератор приостановил работу из-за нехватки звезд.\n"
                    "Группа осталась без защиты от:\n"
                    "• Спама и рекламы\n"
                    "• Мошенников\n"
                    "• Нежелательных сообщений\n\n"
                    "👉 Администраторы могут восстановить защиту через личные сообщения с ботом\n\n"
                    f"🤖 [Хотите такого же модератора в свою группу? Подключить]({ref_link})",
                    parse_mode="markdown",
                    disable_web_page_preview=True,
                )

                # Трекинг отправки рекламного сообщения
                mp.track(
                    chat_id,
                    "promo_message_sent",
                    {
                        "type": "no_credits_group",
                        "admin_id": min_credits_admin.user.id,
                        "admin_credits": min_credits,
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to send group promo message: {e}")

            # Уведомляем админов персонально
            for admin in admins:
                if admin.user.is_bot:
                    continue
                try:
                    await bot.send_message(
                        admin.user.id,
                        "Внимание, органическая форма жизни!\n\n"
                        f'Моя защита группы "{chat.title}" временно приостановлена '
                        "из-за истощения звездной энергии.\n\n"
                        "Пополни запас звезд командой /buy, чтобы я продолжил охранять "
                        "твоё киберпространство от цифровых паразитов!\n\n"
                        f"Или пригласи других администраторов: {ref_link}",
                        disable_web_page_preview=True,
                    )
                except Exception as e:
                    logger.warning(f"Failed to notify admin {admin.user.id}: {e}")
                    continue

        return False
    return True


@log_function_call(logger)
async def handle_spam(message: types.Message) -> None:
    """
    Обработка спам-сообщений
    """
    try:
        # Трекинг обнаружения спама
        mp.track(
            message.chat.id,
            "spam_detected",
            {
                "message_id": message.message_id,
                "author_id": message.from_user.id,
                "spammer_username": message.from_user.username,
                "message_text": message.text,
                "group_name": message.chat.title,
            },
        )

        admins = await bot.get_chat_administrators(message.chat.id)
        all_admins_delete = True

        for admin in admins:
            if admin.user.is_bot:
                continue
            admin_user = await get_admin(admin.user.id)
            if not admin_user or not admin_user.delete_spam:
                all_admins_delete = False
                break

        if all_admins_delete:
            await bot.delete_message(message.chat.id, message.message_id)
            logger.info(
                f"Deleted spam message {message.message_id} in chat {message.chat.id}"
            )

            # Трекинг удаления спама
            mp.track(
                message.chat.id,
                "spam_message_deleted",
                {
                    "message_id": message.message_id,
                    "user_id": message.from_user.id,
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
                    row = [
                        InlineKeyboardButton(
                            text="🗑️ Удалить",
                            callback_data=f"spam_confirm:{message.from_user.id}:{message.chat.id}:{message.message_id}",
                        ),
                        InlineKeyboardButton(
                            text="✅ Не спам",
                            callback_data=f"spam_ignore:{message.from_user.id}",
                        ),
                    ]
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[row])

                admin_msg = (
                    f"⚠️ ТРЕВОГА!\n\n"
                    f"Обнаружено вторжение в {message.chat.title} (@{message.chat.username})!\n\n"
                    f"Нарушитель: {message.from_user.id} (@{message.from_user.username})\n\n"
                    f"Содержание угрозы:\n\n{message.text}\n\n"
                )

                if all_admins_delete:
                    admin_msg += "Вредоносное сообщение уничтожено"
                else:
                    link = f"https://t.me/{message.chat.username}/{message.message_id}"
                    admin_msg += f"Ссылка на сообщение: {link}"

                await bot.send_message(admin.user.id, admin_msg, reply_markup=keyboard)

                # Трекинг уведомления админа
                mp.track(
                    admin.user.id,
                    "admin_spam_notification",
                    {
                        "chat_id": message.chat.id,
                        "message_id": message.message_id,
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
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                    },
                )

    except Exception as e:
        logger.error(f"Error handling spam: {e}", exc_info=True)
        # Трекинг ошибки обработки спама
        mp.track(
            message.chat.id,
            "error_spam_handling",
            {
                "message_id": message.message_id,
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        raise


@dp.message(filter_handle_message)
@log_function_call(logger)
async def handle_moderated_message(message: types.Message):
    """Обработчик всех текстовых сообщений в модерируемых группах"""
    try:
        if not message.text:
            return

        chat_id = message.chat.id
        user_id = message.from_user.id

        # Трекинг начала обработки соощения
        mp.track(
            chat_id,
            "message_processing_started",
            {"user_id": user_id, "message_text": message.text},
        )

        admins = await bot.get_chat_administrators(chat_id)
        admin_ids = [admin.user.id for admin in admins if not admin.user.is_bot]
        await update_group_admins(chat_id, admin_ids)

        if not await is_moderation_enabled(chat_id):
            # Трекинг пропуска из-за отключенной модерации
            mp.track(
                chat_id,
                "message_skipped_moderation_disabled",
            )
            return

        is_known_member = await is_member_in_group(chat_id, user_id)

        if is_known_member:
            # Трекинг пропуска известного пользователя
            mp.track(
                chat_id,
                "message_skipped_known_member",
                {"user_id": user_id},
            )
            return

        user = message.from_user
        user_with_bio = await bot.get_chat(user.id)
        bio = user_with_bio.bio if user_with_bio else None

        # Находим первого не-бот администратора
        admin_id = next(
            (admin.user.id for admin in admins if not admin.user.is_bot), None
        )

        spam_score = await is_spam(
            comment=message.text, name=user.full_name, bio=bio, admin_id=admin_id
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
                "message_text": message.text,
                "user_bio": bio,
            },
        )

        if spam_score > 50:
            if await try_deduct_credits(chat_id, DELETE_PRICE, "delete spam"):
                await handle_spam(message)
            return

        if await try_deduct_credits(chat_id, APPROVE_PRICE, "approve user"):
            await add_member(chat_id, user_id)

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
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        raise
