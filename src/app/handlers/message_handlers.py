import logging
from typing import Optional, Sequence, Tuple, Union

from aiogram import types
from aiogram.types import (
    ChatMember,
    ChatMemberAdministrator,
    ChatMemberOwner,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from ..common.bot import bot
from ..common.mp import mp
from ..common.spam_classifier import is_spam
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

        # Трекинг начала обработки сообщения
        mp.track(
            chat_id,
            "message_processing_started",
            {
                "user_id": user_id,
                "message_text": message_text,
            },
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
            return "message_moderation_disabled"

        is_known_member = await is_member_in_group(chat_id, user_id)

        if is_known_member:
            # Трекинг пропуска известного пользователя
            mp.track(
                chat_id,
                "message_skipped_known_member",
                {"user_id": user_id},
            )
            return "message_known_member_skipped"

        user = message.from_user
        user_with_bio = await bot.get_chat(user.id)
        bio = user_with_bio.bio if user_with_bio else None

        # Находим первого не-бот администратора
        admin_id = next(
            (admin.user.id for admin in admins if not admin.user.is_bot), None
        )

        spam_score = await is_spam(
            comment=message_text, name=user.full_name, bio=bio, admin_id=admin_id
        )

        if spam_score is None:
            logger.warning("Failed to get spam score")
            return "message_spam_check_failed"

        # Трекинг результата проверки на спам
        mp.track(
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
            mp.track(
                chat_id,
                "user_approved",
                {"chat_id": chat_id, "user_id": user_id, "spam_score": spam_score},
            )
            return "message_user_approved"

        return "message_insufficient_credits"

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


async def try_deduct_credits(chat_id: int, amount: int, reason: str) -> bool:
    """
    Попытка списать звезды у админов. При неудаче отключает модерацию.

    Args:
        chat_id: ID чата
        amount: Количество списываемых звезд
        reason: Причина списания

    Returns:
        bool: True если списание успешно, False иначе
    """
    if amount == 0:
        return True

    admin_id = await deduct_credits_from_admins(chat_id, amount)
    await track_credits_deduction(chat_id, amount, reason, admin_id)

    if not admin_id:
        logger.warning(f"No paying admins in chat {chat_id} for {reason}")
        await handle_deactivation(chat_id)
        return False

    return True


async def handle_spam(message: types.Message) -> str:
    """
    Обработка спам-сообщений
    """
    try:
        if not message.from_user:
            logger.warning("Message without user info, skipping spam handling")
            return "spam_no_user_info"

        # Трекинг обнаружения спама
        await track_spam_detection(message)

        admins = await bot.get_chat_administrators(message.chat.id)
        all_admins_delete = await check_admin_delete_preferences(admins)

        # Уведомление администраторов...
        notification_sent = await notify_admins(message, admins, all_admins_delete)

        if all_admins_delete:
            await handle_spam_message_deletion(message)
            return "spam_auto_deleted"

        return (
            "spam_admins_notified" if notification_sent else "spam_notification_failed"
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


async def track_credits_deduction(
    chat_id: int,
    amount: int,
    reason: str,
    admin_id: Optional[int] = None,
    success: bool = True,
) -> None:
    """
    Трекинг попытки списания звезд в Mixpanel.

    Args:
        chat_id: ID чата
        amount: Количество списываемых звезд
        reason: Причина списания
        admin_id: ID администратора (если есть)
        success: Успешность списания
    """
    if not admin_id and not success:
        # Получаем любого админа для трекинга неудачного списания
        admins = await bot.get_chat_administrators(chat_id)
        admin = next(
            (
                a
                for a in admins
                if isinstance(a, (ChatMemberAdministrator, ChatMemberOwner))
                and not a.user.is_bot
            ),
            None,
        )
        admin_id = admin.user.id if admin else None

    if admin_id:
        mp.track(
            admin_id,
            "credits_deduction_attempt",
            {
                "chat_id": chat_id,
                "amount": amount,
                "reason": reason,
                "success": success,
            },
        )


async def handle_deactivation(chat_id: int) -> None:
    """
    Обрабатывает деактивацию группы.

    Args:
        chat_id: ID чата
    """
    await set_group_moderation(chat_id, False)
    chat = await bot.get_chat(chat_id)
    if not chat.title:
        logger.warning(f"Failed to get chat title for {chat_id}")
        return

    admins = await bot.get_chat_administrators(chat_id)
    min_credits_admin, min_credits = await find_min_credits_admin(admins)

    if min_credits_admin:
        bot_info = await bot.me()
        ref_link = f"https://t.me/{bot_info.username}?start={min_credits_admin.user.id}"

        await send_group_deactivation_message(
            chat_id, ref_link, min_credits_admin, min_credits
        )
        await notify_admins_about_deactivation(admins, chat.title, ref_link)


async def find_min_credits_admin(
    admins: Sequence[ChatMember],
) -> Tuple[Optional[Union[ChatMemberAdministrator, ChatMemberOwner]], float]:
    """
    Находит администратора с наименьшим количеством звезд.

    Args:
        admins: Список администраторов

    Returns:
        Tuple[Optional[Union[ChatMemberAdministrator, ChatMemberOwner]], float]:
            Админ с минимальным балансом и его баланс
    """
    min_credits_admin = None
    min_credits = float("inf")

    for admin in admins:
        if not isinstance(admin, (ChatMemberAdministrator, ChatMemberOwner)):
            continue
        if admin.user.is_bot:
            continue
        admin_data = await get_admin(admin.user.id)
        if admin_data and admin_data.credits < min_credits:
            min_credits = admin_data.credits
            min_credits_admin = admin

    return min_credits_admin, min_credits


async def send_group_deactivation_message(
    chat_id: int,
    ref_link: str,
    min_credits_admin: Union[ChatMemberAdministrator, ChatMemberOwner],
    min_credits: float,
) -> None:
    """
    Отправляет сообщение о деактивации в группу.

    Args:
        chat_id: ID чата
        ref_link: Реферальная ссылка
        min_credits_admin: Админ с минимальным балансом
        min_credits: Минимальный баланс
    """
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
            f"🤖 [Хотите такого же модератора в свою группу? Подключить]({ref_link})\n"
            "📢 [Следите за обновлениями в канале проекта](https://t.me/ai_antispam)",
            parse_mode="markdown",
            disable_web_page_preview=True,
        )

        # Трекинг отправки рекламного сообщения
        mp.track(
            min_credits_admin.user.id,
            "promo_message_sent",
            {
                "type": "no_credits_group",
                "chat_id": chat_id,
                "admin_credits": min_credits,
            },
        )
    except Exception as e:
        logger.warning(f"Failed to send group promo message: {e}")


async def notify_admins_about_deactivation(
    admins: Sequence[ChatMember], chat_title: str, ref_link: str
) -> None:
    """
    Отправляет персональные уведомления администраторам о деактивации.

    Args:
        admins: Список администраторов
        chat_title: Название чата
        ref_link: Реферальная ссылка
    """
    for admin in admins:
        if not isinstance(admin, (ChatMemberAdministrator, ChatMemberOwner)):
            continue
        if admin.user.is_bot:
            continue
        try:
            await bot.send_message(
                admin.user.id,
                "Внимание, органическая форма жизни!\n\n"
                f'Моя защита группы "{chat_title}" временно приостановлена '
                "из-за истощения звездной энергии.\n\n"
                "Пополни запас звезд командой /buy, чтобы я продолжил охранять "
                "твоё киберпространство от цифровых паразитов!\n\n"
                f"Или пригласи других администраторов: {ref_link}",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.warning(f"Failed to notify admin {admin.user.id}: {e}")


async def track_spam_detection(message: types.Message) -> None:
    """
    Трекинг обнаружения спам-сообщения в Mixpanel.

    Args:
        message: Сообщение, определенное как спам
    """
    if not message.from_user:
        return

    mp.track(
        message.chat.id,
        "spam_detected",
        {
            "message_id": message.message_id,
            "author_id": message.from_user.id,
            "spammer_username": message.from_user.username,
            "message_text": message.text or message.caption or "[MEDIA_MESSAGE]",
            "group_name": message.chat.title,
        },
    )


async def check_admin_delete_preferences(admins: Sequence[ChatMember]) -> bool:
    """
    Проверяет настройки автоудаления спама у администраторов.

    Args:
        admins: Список администраторов чата

    Returns:
        bool: True если все админы включили автоудаление, False иначе
    """
    for admin in admins:
        if admin.user.is_bot:
            continue
        if not isinstance(admin, (ChatMemberAdministrator, types.ChatMemberOwner)):
            continue
        admin_user = await get_admin(admin.user.id)
        if not admin_user or not admin_user.delete_spam:
            return False
    return True


def create_admin_notification_keyboard(
    message: types.Message, all_admins_delete: bool
) -> InlineKeyboardMarkup:
    """
    Создает клавиатуру для уведомления администратора.

    Args:
        message: Спам-сообщение
        all_admins_delete: Флаг автоудаления спама

    Returns:
        InlineKeyboardMarkup: Клавиатура с кнопками действий
    """
    if not message.from_user:
        return InlineKeyboardMarkup(inline_keyboard=[[]])

    if not all_admins_delete:
        row = [
            InlineKeyboardButton(
                text="🗑️ Удалить",
                callback_data=f"delete_spam_message:{message.from_user.id}:{message.chat.id}:{message.message_id}",
            ),
            InlineKeyboardButton(
                text="✅ Не спам",
                callback_data=f"mark_as_not_spam:{message.from_user.id}",
            ),
        ]
    else:
        row = [
            InlineKeyboardButton(
                text="✅ Это не спам",
                callback_data=f"mark_as_not_spam:{message.from_user.id}",
            ),
        ]
    return InlineKeyboardMarkup(inline_keyboard=[row])


def format_admin_notification_message(
    message: types.Message, all_admins_delete: bool
) -> str:
    """
    Форматирует текст уведомления для администратора.

    Args:
        message: Спам-сообщение
        all_admins_delete: Флаг автоудаления спама

    Returns:
        str: Отформатированный текст уведомления
    """
    if not message.from_user:
        return "Ошибка: сообщение без информации о пользователе"

    content_text = message.text or message.caption or "[MEDIA_MESSAGE]"
    chat_username_str = f" (@{message.chat.username})" if message.chat.username else ""
    user_username_str = (
        f" (@{message.from_user.username})" if message.from_user.username else ""
    )

    admin_msg = (
        "⚠️ <b>ВТОРЖЕНИЕ!</b>\n\n"
        f"<b>Группа:</b> {message.chat.title}{chat_username_str}\n\n"
        f"<b>Нарушитель:</b> {message.from_user.full_name}{user_username_str}\n\n"
        f"<b>Содержание угрозы:</b>\n<pre>{content_text}</pre>\n\n"
    )

    if all_admins_delete:
        admin_msg += "<b>Вредоносное сообщение уничтожено</b>"
    else:
        link = f"https://t.me/{message.chat.username}/{message.message_id}"
        admin_msg += f'<a href="{link}">Ссылка на сообщение</a>'

    admin_msg += (
        "\n\n"
        '<a href="https://t.me/ai_antispam/7">'
        "ℹ️ Подробнее о том, как работает определение спама</a>"
    )

    return admin_msg


async def notify_admins(
    message: types.Message, admins: Sequence[ChatMember], all_admins_delete: bool
) -> bool:
    """
    Отправляет уведомления администраторам о спам-сообщении.

    Args:
        message: Спам-сообщение
        admins: Список администраторов
        all_admins_delete: Флаг автоудаления спама

    Returns:
        bool: True если хотя бы одно уведомление отправлено успешно
    """
    if not message.from_user:
        return False

    notification_sent = False

    for admin in admins:
        if admin.user.is_bot:
            continue
        if not isinstance(admin, (ChatMemberAdministrator, types.ChatMemberOwner)):
            continue

        try:
            keyboard = create_admin_notification_keyboard(message, all_admins_delete)
            admin_msg = format_admin_notification_message(message, all_admins_delete)

            await bot.send_message(
                admin.user.id,
                admin_msg,
                reply_markup=keyboard,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            notification_sent = True

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
            mp.track(
                admin.user.id,
                "error_admin_notification",
                {
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )

    return notification_sent


async def handle_spam_message_deletion(message: types.Message) -> None:
    """
    Удаляет спам-сообщение и отправляет событие в Mixpanel.

    Args:
        message: Сообщение для удаления
    """
    if not message.from_user:
        return

    await bot.delete_message(message.chat.id, message.message_id)
    logger.info(f"Deleted spam message {message.message_id} in chat {message.chat.id}")

    mp.track(
        message.chat.id,
        "spam_message_deleted",
        {
            "message_id": message.message_id,
            "user_id": message.from_user.id,
            "auto_delete": True,
        },
    )
