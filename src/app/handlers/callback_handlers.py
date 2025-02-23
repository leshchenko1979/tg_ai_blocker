import asyncio
import logging

from aiogram import F, types
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from ..common.bot import bot
from ..common.mp import mp
from ..database.spam_examples import add_spam_example
from .dp import dp

logger = logging.getLogger(__name__)


@dp.callback_query(F.data.startswith("mark_as_not_spam:"))
async def handle_spam_ignore_callback(callback: CallbackQuery) -> str:
    """
    Обработчик колбэка для добавления сообщения в базу безопасных примеров
    """
    try:
        if not callback.data or not callback.message:
            return "callback_invalid_data"

        # Разбираем callback_data
        author_id = int(callback.data.split(":")[1])
        author_info = await bot.get_chat(author_id)
        admin_id = callback.from_user.id

        # Get message text safely
        message = callback.message
        if not isinstance(message, types.Message):
            return "callback_invalid_message_type"

        message_text = message.text or message.caption
        if not message_text:
            return "callback_no_message_text"

        add_safe_example_task = asyncio.create_task(
            add_spam_example(
                text=message_text,
                score=-100,  # Безопасное сообщение с отрицательным score
                name=author_info.full_name if author_info else None,
                bio=author_info.bio if author_info else None,
                admin_id=admin_id,
            )
        )

        delete_message_task = asyncio.create_task(
            bot.delete_message(callback.message.chat.id, callback.message.message_id)
        )

        answer_callback_task = asyncio.create_task(
            bot(
                callback.answer(
                    "✅ Сообщение добавлено как безопасный пример",
                    show_alert=False,
                )
            )
        )

        await asyncio.gather(
            add_safe_example_task,
            delete_message_task,
            answer_callback_task,
        )

        # Трекинг обработки колбэка
        mp.track(
            admin_id,
            "callback_spam_ignore",
            {
                "author_id": author_id,
                "text": message_text,
                "name": author_info.full_name,
                "bio": author_info.bio,
            },
        )
        return "callback_marked_as_not_spam"

    except Exception as e:
        # Трекинг ошибок
        mp.track(
            admin_id,
            "error_callback_spam_ignore",
            {
                "error_type": type(e).__name__,
                "error_message": str(e),
                "callback_data": callback.data,
            },
        )
        logger.error(f"Error in spam ignore callback: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка", show_alert=True)
        return "callback_error_marking_not_spam"


@dp.callback_query(F.data.startswith("delete_spam_message:"))
async def handle_spam_confirm_callback(callback: CallbackQuery) -> str:
    """
    Обработчик подтверждения спама. Удаляет оригинальное спам-сообщение из группы
    и убирает клавиатуру с сообщения-уведомления.

    Args:
        callback (CallbackQuery): Callback запрос от Telegram

    Returns:
        str: Статус обработки callback
    """
    if not callback.data:
        return "callback_invalid_data"

    try:
        # Разбираем данные из callback
        # chat_id и message_id относятся к оригинальному сообщению в группе
        _, author_id, original_chat_id, original_message_id = callback.data.split(":")

        # Проверяем, что callback относится к сообщению-уведомлению
        if not callback.message:
            logger.warning("No notification message in callback")
            await callback.answer("❌ Неверный callback", show_alert=True)
            return "callback_invalid_message"

        # Удаляем клавиатуру с сообщения-уведомления
        try:
            await bot.edit_message_reply_markup(
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
                reply_markup=None,
            )
        except Exception as e:
            logger.warning(f"Failed to remove keyboard from notification: {e}")

        # Удаляем оригинальное спам-сообщение из группы
        try:
            await bot.delete_message(int(original_chat_id), int(original_message_id))
        except Exception as e:
            logger.warning(f"Failed to delete original spam message: {e}")
            await callback.answer("❌ Не удалось удалить сообщение", show_alert=True)
            return "callback_error_deleting_original"

        # Отвечаем на callback в случае успеха
        await callback.answer("✅ Спам удален", show_alert=False)

        # Трекинг подтверждения спама
        mp.track(
            callback.from_user.id,
            "callback_spam_confirm",
            {
                "author_id": author_id,
                "chat_id": int(original_chat_id),
                "message_id": int(original_message_id),
                "notification_chat_id": callback.message.chat.id,
                "notification_message_id": callback.message.message_id,
            },
        )
        return "callback_spam_message_deleted"

    except Exception as e:
        # Трекинг ошибок
        mp.track(
            callback.from_user.id,
            "error_callback_spam_confirm",
            {
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        logger.error(f"Error in spam confirm callback: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка", show_alert=True)
        return "callback_error_deleting_spam"
