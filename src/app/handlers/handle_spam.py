"""
Модуль для обработки спам-сообщений в группах Telegram.

Содержит функции для:
- Обработки обнаруженных спам-сообщений
- Уведомления администраторов о спаме
- Автоматического удаления спама
- Блокировки спамеров
"""

import logging

from aiogram import types
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..common.bot import bot
from ..common.mp import mp
from ..common.notifications import notify_admins_with_fallback_and_cleanup
from ..common.tracking import track_group_event, track_spam_detection
from ..common.utils import get_spam_guide_url, retry_on_network_error, sanitize_html
from ..database import get_admin
from ..database.group_operations import remove_member_from_group

logger = logging.getLogger(__name__)


async def handle_spam(message: types.Message, admin_ids: list[int]) -> str:
    """
    Обработка спам-сообщений
    """
    try:
        if not message.from_user:
            logger.warning("Message without user info, skipping spam handling")
            return "spam_no_user_info"

        # Трекинг обнаружения спама
        await track_spam_detection(message)

        # Проверяем настройки автоудаления у админов
        all_admins_delete = await check_admin_delete_preferences(admin_ids)

        # Уведомление администраторов...
        notification_sent = await notify_admins(message, all_admins_delete, admin_ids)

        if all_admins_delete:
            await handle_spam_message_deletion(message, admin_ids)
            await ban_user_for_spam(message.chat.id, message.from_user.id)
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


async def check_admin_delete_preferences(admin_ids: list[int]) -> bool:
    """
    Проверяет настройки автоудаления спама у администраторов.

    Args:
        admin_ids: Список ID администраторов группы

    Returns:
        bool: True если все админы включили автоудаление, False иначе
    """
    for admin_id in admin_ids:
        admin_user = await get_admin(admin_id)
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
                callback_data=f"mark_as_not_spam:{message.from_user.id}:{message.chat.id}",
            ),
        ]
    else:
        row = [
            InlineKeyboardButton(
                text="✅ Это не спам",
                callback_data=f"mark_as_not_spam:{message.from_user.id}:{message.chat.id}",
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
    # Escape HTML entities in content to prevent parsing errors
    content_text = sanitize_html(content_text)
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
        admin_msg += (
            "<b>Вредоносное сообщение уничтожено, пользователь заблокирован.</b>"
        )
    else:
        link = f"https://t.me/{message.chat.username}/{message.message_id}"
        admin_msg += (
            f'<a href="{link}">Ссылка на сообщение</a>\n\n'
            "<b>💡 Совет:</b> Используйте команду /mode, "
            "чтобы переключиться в режим автоматического удаления спама."
        )

    admin_msg += (
        "\n\n"
        f'<a href="{get_spam_guide_url()}">'
        "ℹ️ Подробнее о том, как работает определение спама</a>"
    )

    return admin_msg


async def notify_admins(
    message: types.Message, all_admins_delete: bool, admin_ids: list[int]
) -> bool:
    """
    Отправляет уведомления администраторам о спам-сообщении.

    Args:
        message: Спам-сообщение
        all_admins_delete: Флаг автоудаления спама

    Returns:
        bool: True если хотя бы одно уведомление отправлено успешно
    """
    if not message.from_user:
        return False

    # admin_ids are passed as parameter
    private_message = format_admin_notification_message(message, all_admins_delete)
    keyboard = create_admin_notification_keyboard(message, all_admins_delete)
    result = await notify_admins_with_fallback_and_cleanup(
        bot,
        admin_ids,
        message.chat.id,
        private_message,
        group_message_template="{mention}, я не могу отправить ни одному администратору личное сообщение. Пожалуйста, напишите мне в личку, чтобы получать важные уведомления о группе!",
        cleanup_if_group_fails=True,
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    return bool(result["notified_private"]) or bool(result["group_notified"])


async def handle_spam_message_deletion(
    message: types.Message, admin_ids: list[int]
) -> None:
    """
    Удаляет спам-сообщение и отправляет событие в Mixpanel.

    Args:
        message: Сообщение для удаления
    """
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

        await track_group_event(
            message.chat.id,
            "spam_message_deleted",
            {
                "message_id": message.message_id,
                "user_id": message.from_user.id,
                "auto_delete": True,
            },
        )
    except TelegramBadRequest as e:
        # Check for deletion errors that indicate permission issues
        error_message = str(e).lower()
        is_deletion_error = (
            "not enough rights" in error_message
            or "need administrator rights" in error_message
            or "chat admin required" in error_message
            or "can_delete_messages" in error_message
            or "message can't be deleted" in error_message
        )

        if is_deletion_error:
            logger.warning(
                f"Cannot delete spam message {message.message_id} in chat {message.chat.id}: {e}",
                exc_info=True,
            )
            # Notify admins about missing permission - if this fails, cleanup will happen
            if admin_ids:  # Only notify if there are admins to notify
                try:
                    group_title = message.chat.title or ""
                    notification_result = await notify_admins_with_fallback_and_cleanup(
                        bot,
                        admin_ids,
                        message.chat.id,
                        private_message=(
                            "❗️ У меня нет права удалять спам-сообщения в группе. "
                            f"Пожалуйста, дайте мне право 'Удаление сообщений' для корректной работы.\n\nГруппа: <b>{sanitize_html(group_title)}</b>"
                        ),
                        group_message_template="{mention}, у меня нет права удалять спам-сообщения. Пожалуйста, дайте мне право 'Удаление сообщений'!",
                        cleanup_if_group_fails=True,
                        parse_mode="HTML",
                    )
                    if (
                        not notification_result["notified_private"]
                        and not notification_result["group_notified"]
                    ):
                        logger.error(
                            f"Failed to notify admins about missing spam deletion rights - all notification methods failed for chat {message.chat.id}, cleanup initiated"
                        )
                    elif notification_result["group_cleaned_up"]:
                        logger.info(
                            f"Group {message.chat.id} cleaned up due to inability to notify admins about missing delete permissions for spam"
                        )
                except Exception as notify_exc:
                    logger.warning(
                        f"Failed to notify admins about missing rights for spam deletion: {notify_exc}"
                    )
        else:
            logger.warning(
                f"Could not delete spam message {message.message_id} in chat {message.chat.id}: {e}",
                exc_info=True,
            )
        await track_group_event(
            message.chat.id,
            "spam_message_delete_failed",
            {
                "message_id": message.message_id,
                "user_id": message.from_user.id,
                "error_message": str(e),
            },
        )


async def ban_user_for_spam(chat_id: int, user_id: int) -> None:
    """
    Банит пользователя в группе и удаляет из approved_members.
    Args:
        chat_id: ID чата
        user_id: ID пользователя
    """
    try:

        @retry_on_network_error
        async def ban_spam_user():
            if user_id < 0:
                # It's a channel, use ban_chat_sender_chat
                return await bot.ban_chat_sender_chat(chat_id, sender_chat_id=user_id)
            return await bot.ban_chat_member(chat_id, user_id)

        await ban_spam_user()
        logger.info(f"Banned user {user_id} in chat {chat_id} for spam")
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
