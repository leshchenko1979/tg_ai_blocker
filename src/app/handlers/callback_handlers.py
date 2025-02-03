import asyncio
import logging

from aiogram import F
from aiogram.types import CallbackQuery

from ..common.bot import bot
from ..common.mp import mp
from ..database.spam_examples import add_spam_example
from .dp import dp

logger = logging.getLogger(__name__)


@dp.callback_query(F.data.startswith("mark_as_not_spam:"))
async def handle_spam_ignore_callback(callback: CallbackQuery):
    """
    Обработчик колбэка для добавления сообщения в базу безопасных примеров
    """
    try:
        # Разбираем callback_data
        author_id = int(callback.data.split(":")[1])
        author_info = await bot.get_chat(author_id)
        admin_id = callback.from_user.id

        add_safe_example_task = asyncio.create_task(
            add_spam_example(
                text=callback.message.text,
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
                "text": callback.message.text,
                "name": author_info.full_name,
                "bio": author_info.bio,
            },
        )

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


@dp.callback_query(F.data.startswith("delete_spam_message:"))
async def handle_spam_confirm_callback(callback: CallbackQuery):
    """
    Обработчик колбэка для удаления спам-сообщения
    """
    _, author_id, chat_id, message_id = callback.data.split(":")
    try:
        delete_message_task = asyncio.create_task(
            bot.delete_message(chat_id, message_id)
        )
        edit_message_task = asyncio.create_task(
            bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
        )
        answer_callback_task = asyncio.create_task(
            bot(callback.answer("✅ Принято", show_alert=False))
        )

        await asyncio.gather(
            delete_message_task, edit_message_task, answer_callback_task
        )

        # Трекинг подтверждения спама
        mp.track(
            callback.from_user.id,
            "callback_spam_confirm",
            {
                "author_id": author_id,
                "chat_id": chat_id,
                "message_id": message_id,
            },
        )

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
