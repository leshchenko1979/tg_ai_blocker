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
from ..common.utils import (
    get_setup_guide_url,
    get_spam_guide_url,
    retry_on_network_error,
    sanitize_html,
)
from ..database import get_admins_map
from ..database.group_operations import remove_member_from_group

logger = logging.getLogger(__name__)


async def handle_spam(
    message: types.Message, admin_ids: list[int], reason: str | None = None
) -> str:
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
        notification_sent = await notify_admins(message, all_admins_delete, admin_ids, reason)

        if all_admins_delete:
            await handle_spam_message_deletion(message, admin_ids)
            await ban_user_for_spam(
                message.chat.id, message.from_user.id, admin_ids, message.chat.title
            )
            return "spam_auto_deleted"

        return "spam_admins_notified" if notification_sent else "spam_notification_failed"

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
    if not admin_ids:
        return False

    admins_map = await get_admins_map(admin_ids)
    for admin_id in admin_ids:
        admin_user = admins_map.get(admin_id)
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


def format_missing_permission_message(chat_title: str, permission_name: str) -> str:
    """
    Форматирует сообщение о отсутствии прав доступа.

    Args:
        chat_title: Название группы
        permission_name: Название отсутствующего права

    Returns:
        str: Отформатированное сообщение для администраторов
    """
    # Map permission names to user-friendly descriptions
    permission_descriptions = {
        "Удаление сообщений": "удалять спам-сообщения",
        "Блокировка пользователей": "блокировать пользователей",
    }

    action_description = permission_descriptions.get(permission_name, permission_name.lower())

    return (
        f"❗️ У меня нет права {action_description}. "
        f"Пожалуйста, дайте мне право '{permission_name}' для полной защиты.\n\n"
        f"Группа: <b>{sanitize_html(chat_title)}</b>\n\n"
        f'<a href="{get_setup_guide_url()}">ℹ️ Как выдать права боту</a>'
    )


async def handle_permission_error(
    error: Exception,
    chat_id: int,
    admin_ids: list[int] | None,
    group_title: str | None,
    permission_name: str,
    action_description: str,
) -> bool:
    """
    Обрабатывает ошибки связанные с отсутствием прав доступа.

    Args:
        error: Исключение, которое произошло
        chat_id: ID чата
        admin_ids: Список ID администраторов для уведомления
        group_title: Название группы
        permission_name: Название отсутствующего права
        action_description: Описание действия, которое пытались выполнить

    Returns:
        bool: True если это была ошибка прав доступа, False иначе
    """
    if not isinstance(error, TelegramBadRequest):
        return False

    error_message = str(error).lower()
    is_permission_error = (
        "not enough rights" in error_message
        or "need administrator rights" in error_message
        or "chat admin required" in error_message
        or "can_delete_messages" in error_message
        or "can_restrict_members" in error_message
        or "message can't be deleted" in error_message
    )

    if is_permission_error:
        logger.warning(
            f"Cannot {action_description} in chat {chat_id}: {error}",
            exc_info=True,
        )
        # Notify admins about missing permission
        if admin_ids:
            try:
                display_title = group_title or str(chat_id)
                await notify_admins_with_fallback_and_cleanup(
                    bot,
                    admin_ids,
                    chat_id,
                    private_message=format_missing_permission_message(
                        display_title, permission_name
                    ),
                    group_message_template=(
                        f"{{mention}}, у меня нет права {permission_name}. "
                        f"Пожалуйста, дайте мне право '{permission_name}'!\n\n"
                        f'<a href="{get_setup_guide_url()}">ℹ️ Как выдать права боту</a>'
                    ),
                    cleanup_if_group_fails=True,
                    parse_mode="HTML",
                )
            except Exception as notify_exc:
                logger.warning(
                    f"Failed to notify admins about missing rights for {action_description}: {notify_exc}"
                )
        return True

    return False


def format_admin_notification_message(
    message: types.Message, all_admins_delete: bool, reason: str | None = None
) -> str:
    """
    Форматирует текст уведомления для администратора.

    Args:
        message: Спам-сообщение
        all_admins_delete: Флаг автоудаления спама
        reason: Причина классификации как спам

    Returns:
        str: Отформатированный текст уведомления
    """
    if not message.from_user:
        return "Ошибка: сообщение без информации о пользователе"

    content_text = message.text or message.caption or "[MEDIA_MESSAGE]"
    # Escape HTML entities in content to prevent parsing errors
    content_text = sanitize_html(content_text)
    chat_username_str = f" (@{message.chat.username})" if message.chat.username else ""
    user_username_str = f" (@{message.from_user.username})" if message.from_user.username else ""

    reason_text = (
        f"<b>Причина:</b><blockquote expandable>{sanitize_html(reason)}</blockquote>\n"
        if reason
        else ""
    )

    admin_msg = (
        "⚠️ <b>ВТОРЖЕНИЕ!</b>\n\n"
        f"<b>Группа:</b> {sanitize_html(message.chat.title)}{chat_username_str}\n\n"
        f"<b>Нарушитель:</b> {sanitize_html(message.from_user.full_name)}{user_username_str}\n\n"
        f"<b>Содержание угрозы:</b>\n<blockquote expandable>{content_text}</blockquote>\n\n"
        f"{reason_text}\n"
    )

    if all_admins_delete:
        admin_msg += "<b>Вредоносное сообщение уничтожено, пользователь заблокирован.</b>"
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
    message: types.Message,
    all_admins_delete: bool,
    admin_ids: list[int],
    reason: str | None = None,
) -> bool:
    """
    Отправляет уведомления администраторам о спам-сообщении.

    Args:
        message: Спам-сообщение
        all_admins_delete: Флаг автоудаления спама
        admin_ids: IDs of admins to notify
        reason: Причина классификации как спам

    Returns:
        bool: True если хотя бы одно уведомление отправлено успешно
    """
    if not message.from_user:
        return False

    # admin_ids are passed as parameter
    private_message = format_admin_notification_message(message, all_admins_delete, reason)
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


async def handle_spam_message_deletion(message: types.Message, admin_ids: list[int]) -> None:
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
        logger.info(f"Deleted spam message {message.message_id} in chat {message.chat.id}")

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
        # Handle permission errors using unified helper
        if not await handle_permission_error(
            e,
            message.chat.id,
            admin_ids,
            message.chat.title,
            "Удаление сообщений",
            "delete spam message",
        ):
            # Not a permission error, log as general error
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


async def ban_user_for_spam(
    chat_id: int,
    user_id: int,
    admin_ids: list[int] | None = None,
    group_title: str | None = None,
) -> None:
    """
    Банит пользователя в группе и удаляет из approved_members.
    Args:
        chat_id: ID чата
        user_id: ID пользователя
        admin_ids: Список ID администраторов для уведомления об ошибках
        group_title: Название группы (для уведомлений)
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
    except TelegramBadRequest as e:
        # Handle permission errors using unified helper
        if not await handle_permission_error(
            e,
            chat_id,
            admin_ids,
            group_title,
            "Блокировка пользователей",
            "ban user",
        ):
            # Not a permission error, log as general error
            logger.warning(f"Failed to ban user {user_id} in chat {chat_id}: {e}", exc_info=True)
    except Exception as e:
        logger.warning(f"Failed to ban user {user_id} in chat {chat_id}: {e}", exc_info=True)
    try:
        await remove_member_from_group(user_id, chat_id)
    except Exception as e:
        logger.warning(f"Failed to remove user {user_id} from approved_members: {e}", exc_info=True)
