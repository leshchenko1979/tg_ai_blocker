from aiogram.types import CallbackQuery

from common.bot import bot
from common.database.spam_examples import add_spam_example
from common.dp import dp
from common.mp import mp
from common.yandex_logging import get_yandex_logger, log_function_call

logger = get_yandex_logger(__name__)


@dp.callback_query(lambda c: c.data.startswith("spam_ignore:"))
@log_function_call(logger)
async def handle_spam_ignore_callback(callback: CallbackQuery):
    """
    Обработчик колбэка для игнорирования спам-сообщения и добавления в базу безопасных примеров
    """
    try:
        # Разбираем callback_data
        author_id = callback.data.split()[1]
        author_info = await bot.get_chat(author_id)
        admin_id = callback.from_user.id

        # Трекинг начала обработки колбэка
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

        # Добавляем сообщение как безопасный пример
        await add_spam_example(
            text=callback.message.text,
            score=-100,  # Безопасное сообщение с отрицательным score
            name=author_info.full_name if author_info else None,
            bio=author_info.bio if author_info else None,
            user_id=admin_id,
        )

        # Удаляем сообщение с кнопками
        await callback.message.delete()

        await callback.answer(
            "✅ Сообщение добавлено как безопасный пример", show_alert=False
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
        await callback.answer("Произошла ошибка при обработке", show_alert=True)


@dp.callback_query(lambda c: c.data == "spam_confirm")
@log_function_call(logger)
async def handle_spam_confirm_callback(callback: CallbackQuery):
    """
    Обработчик колбэка для подтверждения спам-сообщения
    """
    _, author_id, chat_id, message_id = callback.data.split(":")
    try:
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

        # Удаляем сообщение
        await bot.delete_message(chat_id, message_id)

        # Редактируем сообщение, убирая клавиатуру
        await callback.message.edit_reply_markup(reply_markup=None)

        await callback.answer("✅ Принято", show_alert=False)

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
        await callback.answer("Произошла ошибка при обработке", show_alert=True)
