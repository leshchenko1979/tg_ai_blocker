import asyncio
import logging

from aiogram import F, types
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from ..common.bot import bot
from ..spam.user_profile import collect_user_context
from ..common.utils import load_config, retry_on_network_error
from ..database.group_operations import add_member
from ..database.spam_examples import add_spam_example
from .dp import dp

logger = logging.getLogger(__name__)


def create_help_keyboard(config):
    """Создает клавиатуру помощи из конфигурации"""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    help_config = config.get("help_system", {})
    buttons_config = help_config.get("buttons", [])

    if not buttons_config:
        return InlineKeyboardMarkup(inline_keyboard=[])

    inline_keyboard = []
    for row_config in buttons_config:
        row = []
        # row_config - это массив вида ["text1", "callback1", "text2", "callback2", ...]
        for i in range(0, len(row_config), 2):
            if i + 1 < len(row_config):
                text = row_config[i]
                callback_data = row_config[i + 1]
                row.append(InlineKeyboardButton(text=text, callback_data=callback_data))
        if row:  # Добавляем только непустые ряды
            inline_keyboard.append(row)

    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


@dp.callback_query(F.data.startswith("help_") & ~F.data.in_(["help_back"]))
async def handle_help_pages(callback: CallbackQuery) -> str:
    """Единый обработчик для всех страниц помощи"""
    if not callback.message or not isinstance(callback.message, types.Message):
        await callback.answer("❌ Сообщение недоступно", show_alert=True)
        return "callback_message_inaccessible"

    config = load_config()
    help_config = config.get("help_system", {})

    callback_data = callback.data

    # Вычисляем всё на лету
    text_key = f"{callback_data}_text"
    return_value = f"{callback_data}_shown"
    default_text = help_config.get(
        "default_page_text", "Информация временно недоступна."
    )

    # Получаем текст страницы
    text = config.get(text_key, default_text)

    # Создаем кнопку "Назад"
    back_button_text = help_config.get("back_button_text", "⬅️ Назад к справке")
    back_button = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=back_button_text, callback_data="help_back")]
        ]
    )

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=back_button,
        disable_web_page_preview=True,
    )
    await callback.answer()

    return return_value


@dp.callback_query(F.data == "help_back")
async def handle_help_back(callback: CallbackQuery) -> str:
    """Возвращает к основному меню помощи"""
    if not callback.message or not isinstance(callback.message, types.Message):
        await callback.answer("❌ Сообщение недоступно", show_alert=True)
        return "callback_message_inaccessible"

    config = load_config()

    # Получаем текст главного меню (всегда "help_text")
    text = config.get("help_text", "Справка временно недоступна.")

    # Создаем клавиатуру
    keyboard = create_help_keyboard(config)

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )
    await callback.answer()
    return "help_back_shown"


@dp.callback_query(F.data.startswith("mark_as_not_spam:"))
async def handle_spam_ignore_callback(callback: CallbackQuery) -> str:
    """
    Обработчик колбэка для добавления сообщения в базу безопасных примеров.
    Обновляет сообщение-уведомление, отмечая его как "Не спам".
    """
    try:
        admin_id = callback.from_user.id

        if not callback.data or not callback.message:
            return "callback_invalid_data"

        # Быстрый ответ Telegram, чтобы избежать таймаута
        try:
            await callback.answer(
                "✅ Сообщение добавлено как безопасный пример", show_alert=False
            )
        except Exception:
            # Игнорируем ошибки ответа на колбэк (например, если он устарел),
            # чтобы не прерывать основную логику
            pass

        # Разбираем callback_data
        # Ожидается формат: mark_as_not_spam:{user_id}:{chat_id}
        parts = callback.data.split(":")
        if len(parts) < 3:
            return "callback_invalid_data_format"
        author_id = int(parts[1])
        group_id = int(parts[2])
        author_info = await bot.get_chat(author_id)

        # Get message text safely
        message = callback.message
        if not isinstance(message, types.Message):
            return "callback_invalid_message_type"

        message_text = message.text or message.caption
        if not message_text:
            return "callback_no_message_text"

        # Обновляем текст сообщения, добавляя пометку "Не спам"
        updated_message_text = f"{message_text}\n\n✅ <b>Отмечено как НЕ СПАМ</b>"

        channel_fragment = None
        try:
            user_context = await collect_user_context(
                author_id, username=author_info.username if author_info else None
            )
        except Exception as exc:  # noqa: BLE001
            logger.info(
                "Failed to load user context for author",
                extra={
                    "author_id": author_id,
                    "username": author_info.username if author_info else None,
                    "error": str(exc),
                },
            )
            user_context = None
        if user_context and user_context.linked_channel.status == "found":
            assert user_context.linked_channel.content is not None
            channel_fragment = user_context.linked_channel.content.to_prompt_fragment()

        # Все тяжелые операции параллельно
        async with asyncio.TaskGroup() as tg:
            tg.create_task(
                bot.unban_chat_member(group_id, author_id, only_if_banned=True)
            )
            tg.create_task(add_member(group_id, author_id))
            tg.create_task(
                add_spam_example(
                    text=message_text,
                    score=-100,  # Безопасное сообщение с отрицательным score
                    name=author_info.full_name if author_info else None,
                    bio=author_info.bio if author_info else None,
                    admin_id=admin_id,
                    linked_channel_fragment=channel_fragment,
                    stories_context=None,  # Not available for user approvals
                    reply_context=None,  # Not available for user approvals
                    account_age_context=None,  # Not available for user approvals
                )
            )

            tg.create_task(
                bot.edit_message_text(
                    chat_id=callback.message.chat.id,
                    message_id=callback.message.message_id,
                    text=updated_message_text,
                    parse_mode="HTML",
                    reply_markup=None,  # Убираем клавиатуру
                )
            )

        return "callback_marked_as_not_spam"

    except Exception as e:
        logger.error(f"Error in spam ignore callback: {e}", exc_info=True)
        try:
            await callback.answer("❌ Произошла ошибка", show_alert=True)
        except Exception:
            pass
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
        # Быстрый ответ Telegram, чтобы избежать таймаута
        try:
            await callback.answer("✅ Спам удален", show_alert=False)
        except Exception:
            pass

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

            @retry_on_network_error
            async def delete_original_message():
                return await bot.delete_message(
                    int(original_chat_id), int(original_message_id)
                )

            await delete_original_message()
        except Exception as e:
            logger.warning(
                f"Failed to delete original spam message: {e}", exc_info=True
            )
            await callback.answer("❌ Не удалось удалить сообщение", show_alert=True)
            return "callback_error_deleting_original"

        return "callback_spam_message_deleted"

    except Exception as e:
        logger.error(f"Error in spam confirm callback: {e}", exc_info=True)
        try:
            await callback.answer("❌ Произошла ошибка", show_alert=True)
        except Exception:
            pass
        return "callback_error_deleting_spam"
