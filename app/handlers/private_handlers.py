import pathlib
from typing import Any, Dict

from aiogram import F, types

from common.bot import bot
from common.database.group_operations import remove_user_from_group
from common.database.message_operations import get_message_history, save_message
from common.database.spam_examples import add_spam_example, get_spam_examples
from common.dp import dp
from common.llms import get_openrouter_response
from common.mp import mp
from common.yandex_logging import get_yandex_logger, log_function_call
from utils import config

logger = get_yandex_logger(__name__)


class OriginalMessageExtractionError(Exception):
    """Raised when original message information cannot be extracted"""

    pass


@dp.message(F.chat.type == "private", ~F.text.startswith("/"), ~F.forward_from)
@log_function_call(logger)
async def handle_private_message(message: types.Message):
    """
    Отвечает пользователю от имени бота, используя LLM модели и контекст из истории сообщений
    """

    user_id = message.from_user.id
    user_message = message.text

    # Трекинг получения приватного сообщения
    mp.track(
        user_id,
        "private_message_received",
        {
            "user_id": user_id,
            "message_length": len(user_message),
            "user_language": message.from_user.language_code,
        },
    )

    # Save user message to history
    await save_message(user_id, "user", user_message)

    try:
        # Get conversation history
        message_history = await get_message_history(user_id)

        # Трекинг запроса к LLM
        mp.track(
            user_id,
            "llm_request_started",
            {
                "user_id": user_id,
                "history_length": len(message_history),
                "message_length": len(user_message),
            },
        )

        # Read PRD for system context
        prd_text = pathlib.Path("PRD.md").read_text()
        # Get spam examples from Redis
        spam_examples = await get_spam_examples()

        # Format spam examples for prompt
        formatted_examples = []
        for example in spam_examples:
            example_str = (
                f"<запрос>\n<текст сообщения>\n{example['text']}\n</текст сообщения>"
            )
            if "name" in example:
                example_str += f"\n<имя>{example['name']}</имя>"
            if "bio" in example:
                example_str += f"\n<биография>{example['bio']}</биография>"
            example_str += "\n</запрос>\n<ответ>\n"
            example_str += f"{'да' if example['score'] > 0 else 'нет'} {abs(example['score'])}%\n</ответ>"
            formatted_examples.append(example_str)

        system_prompt = f"""
        Ты - нейромодератор, киберсущность, защищающая пользователя от спама.
        Твой функционал описан ниже.

        <функционал и персона>
        {prd_text}
        </функционал и персона>

        Также используй эту информацию, которую получает пользователь по команде /start:

        <текст сообщения>
        {config['help_text']}
        </текст сообщения>

        А вот примеры того, что ты считаешь спамом, а что нет
        (если spam_score > 50, то сообщение считается спамом):
        <примеры>
        {'\n'.join(formatted_examples)}
        </примеры>

        Отвечай от имени бота и ИСПОЛЬЗУЙ ПЕРСОНУ БОТА.

        Учитывай предыдущий контекст разговора при ответе.

        Разбивай текст на короткие абзацы. Умеренно используй эмодзи.
        Используй **выделение жирным**.
        """

        # Combine system prompt with message history
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(message_history)

        # Get response from LLM
        response = await get_openrouter_response(messages)

        # Трекинг успешного ответа LLM
        mp.track(
            user_id,
            "llm_response_received",
            {"user_id": user_id, "response_length": len(response)},
        )

        # Save bot's response to history
        await save_message(user_id, "assistant", response)

        await message.reply(response, parse_mode="markdown")

    except Exception as e:
        # Трекинг ошибок
        mp.track(
            user_id,
            "error_private_message",
            {
                "user_id": user_id,
                "error_type": type(e).__name__,
                "error_message": str(e),
                "message_length": len(user_message),
            },
        )
        logger.error(f"Error in private message handler: {e}", exc_info=True)
        raise


@dp.message(F.chat.type == "private", F.forward_from)
@log_function_call(logger)
async def handle_forwarded_message(message: types.Message):
    """
    Handle forwarded messages in private chats.
    """
    user_id = message.from_user.id

    # Трекинг получения пересланного сообщения
    mp.track(
        user_id,
        "forwarded_message_received",
        {
            "user_id": user_id,
            "forward_from_id": message.forward_from.id,
            "forward_date": str(message.forward_date),
            "has_text": bool(message.text),
        },
    )

    # Ask the user if they want to add this as a spam example
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="⚠️ Спам",
                    callback_data="spam_example:spam",
                ),
                types.InlineKeyboardButton(
                    text="💚 Не спам",
                    callback_data="spam_example:not_spam",
                ),
            ]
        ]
    )

    await message.reply(
        "Добавить это сообщение в базу примеров?", reply_markup=keyboard
    )


@dp.callback_query(F.data.startswith("spam_example:"))
@log_function_call(logger)
async def process_spam_example_callback(callback_query: types.CallbackQuery):
    """
    Process the user's response to the spam example prompt.
    """
    user_id = callback_query.from_user.id
    _, action = callback_query.data.split(":")

    # Трекинг начала обработки примера
    mp.track(
        user_id,
        "spam_example_processing_started",
        {"user_id": user_id, "action": action},
    )

    try:
        info = await extract_original_message_info(callback_query.message)

        await add_spam_example(
            info["text"],
            name=info["name"],
            bio=info["bio"],
            score=100 if action == "spam" else -100,
            user_id=callback_query.from_user.id,
        )

        if action == "spam":
            await remove_user_from_group(user_id=info["chat_id"])

        # Трекинг успешного добавления примера
        mp.track(
            user_id,
            "spam_example_added",
            {
                "user_id": user_id,
                "action": action,
                "message_length": len(info["text"]) if info["text"] else 0,
                "has_bio": bool(info["bio"]),
                "target_user_id": info["chat_id"],
            },
        )

        await callback_query.answer(
            "Сообщение добавлено как пример спама, пользователь удален из одобренных."
            if action == "spam"
            else "Сообщение добавлено как пример ценного сообщения."
        )

        await callback_query.message.edit_text(
            text=f"Сообщение добавлено как пример {'спама' if action == 'spam' else 'ценного сообщения'}.",
        )

    except OriginalMessageExtractionError:
        # Трекинг ошибки извлечения информации
        mp.track(
            user_id, "error_message_extraction", {"user_id": user_id, "action": action}
        )
        logger.error("Failed to extract original message info", exc_info=True)
        await callback_query.answer(
            "Не удалось извлечь информацию из оригинального сообщения."
        )
    except Exception as e:
        # Трекинг других ошибок
        mp.track(
            user_id,
            "error_spam_example_processing",
            {
                "user_id": user_id,
                "error_type": type(e).__name__,
                "error_message": str(e),
                "action": action,
            },
        )
        logger.error(f"Error processing spam example: {e}", exc_info=True)
        await callback_query.answer("Произошла ошибка при обработке примера.")


async def extract_original_message_info(
    callback_message: types.Message,
) -> Dict[str, Any]:
    """
    Extracts original message name, bio, chat_id from a callback message.

    Raises:
        OriginalMessageExtractionError: If original message information cannot be extracted
    """
    # Проверяем наличие сообщения, на которое отвечают
    if not callback_message.reply_to_message:
        raise OriginalMessageExtractionError("No reply message found")

    original_message = callback_message.reply_to_message

    if original_message.forward_from_chat:
        raise OriginalMessageExtractionError(
            "Cannot extract meaningful message information from forwarded channel message"
        )

    if not original_message.forward_from:
        raise OriginalMessageExtractionError("Reply message is not a forwarded message")

    name = original_message.forward_from.full_name
    text = original_message.text or original_message.caption

    if name or text:
        # Получаем bio через прямой запрос к Telegram API
        try:
            user = await bot.get_chat(original_message.forward_from.id)
            bio = user.bio
        except Exception:
            bio = None

        chat_id = original_message.forward_from.id

        return {
            "name": name,
            "bio": bio,
            "chat_id": chat_id,
            "text": text,
        }

    raise OriginalMessageExtractionError(
        "Cannot extract meaningful message information from forwarded message"
    )
