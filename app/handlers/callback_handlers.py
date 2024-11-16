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
        _, message_id, chat_id = callback.data.split(":")
        message_id = int(message_id)
        chat_id = int(chat_id)
        user_id = callback.from_user.id

        # Трекинг начала обработки колбэка
        mp.track(
            user_id,
            "callback_spam_ignore_start",
            {"user_id": user_id, "chat_id": chat_id, "message_id": message_id},
        )

        # Проверяем, что колбэк пришел от администратора чата
        chat_member = await bot.get_chat_member(chat_id, user_id)

        if chat_member.status not in ["administrator", "creator"]:
            # Трекинг неавторизованного доступа
            mp.track(
                user_id,
                "callback_spam_ignore_unauthorized",
                {
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "user_status": chat_member.status,
                },
            )
            await callback.answer(
                "❌ Только администраторы могут принимать решения", show_alert=True
            )
            return

        # Получаем информацию о сообщении
        message = await bot.get_message(chat_id, message_id)
        user = message.from_user
        user_info = await bot.get_chat(user.id)

        # Добавляем сообщение как безопасный пример
        await add_spam_example(
            text=message.text,
            score=-100,  # Безопасное сообщение с отрицательным score
            name=user.full_name,
            bio=user_info.bio if user_info else None,
            user_id=user.id,
        )

        # Трекинг успешного добавления примера
        mp.track(
            user_id,
            "callback_spam_ignore_success",
            {
                "user_id": user_id,
                "chat_id": chat_id,
                "message_id": message_id,
                "target_user_id": user.id,
                "message_length": len(message.text) if message.text else 0,
                "has_bio": bool(user_info.bio if user_info else None),
            },
        )

        # Удаляем сообщение с кнопками
        await callback.message.delete()

        await callback.answer(
            "✅ Сообщение добавлено как безопасный пример", show_alert=False
        )

    except Exception as e:
        # Трекинг ошибок
        mp.track(
            callback.from_user.id,
            "error_callback_spam_ignore",
            {
                "user_id": callback.from_user.id,
                "error_type": type(e).__name__,
                "error_message": str(e),
                "callback_data": callback.data,
            },
        )
        logger.error(f"Error in spam ignore callback: {e}", exc_info=True)
        await callback.answer("Произошла ошибка при обработке", show_alert=True)
