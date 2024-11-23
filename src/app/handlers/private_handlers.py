import asyncio
import pathlib
from typing import Any, Dict

from aiogram import F, types

from ..common.bot import bot
from ..common.database import (
    add_spam_example,
    get_message_history,
    get_spam_examples,
    remove_member_from_group,
    save_message,
)
from ..common.dp import dp
from ..common.llms import get_openrouter_response
from ..common.mp import mp
from ..common.yandex_logging import get_yandex_logger, log_function_call
from ..utils import config

logger = get_yandex_logger(__name__)


class OriginalMessageExtractionError(Exception):
    """Raised when original message information cannot be extracted"""


@dp.message(F.chat.type == "private", ~F.text.startswith("/"), ~F.forward_from)
@log_function_call(logger)
async def handle_private_message(message: types.Message):
    """
    Отвечает пользователю от имени бота, используя LLM модели и контекст из истории сообщений
    """

    admin_id = message.from_user.id
    admin_message = message.text

    # Трекинг получения приватного сообщения
    mp.track(admin_id, "private_message_received", {"message_text": admin_message})

    # Save user message to history
    await save_message(admin_id, "user", admin_message)

    try:
        # Get conversation history
        message_history = await get_message_history(admin_id)

        # Трекинг запроса к LLM
        mp.track(
            admin_id,
            "llm_request_started",
            {
                "history_length": len(message_history),
                "message_text": admin_message,
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
            example_str += f"{'да' if example['score'] > 0 else 'нет'} {abs(example['score'])}%\n</отве��>"
            formatted_examples.append(example_str)

        system_prompt = f"""
        Ты - нейромодератор, киберсущность, защищающая пользователя от спама.
        Твой функционал описан ниже.

        <функционал и стиль ответа>
        {prd_text}
        </функционал и стиль ответа>

        Также используй эту информацию, которую получает пользователь по команде /start:

        <текст сообщения>
        {config['help_text']}
        </текст сообщения>

        А вот примеры того, что ты считаешь спамом, а что нет
        (если spam_score > 50, то сообщение считается спамом):
        <примеры>
        {'\n'.join(formatted_examples)}
        </примеры>

        Отвечай от имени бота и используй указанный стиль ответа.

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
            admin_id,
            "llm_response_received",
            {"response_text": response},
        )

        # Save bot's response to history
        await save_message(admin_id, "assistant", response)

        await message.reply(response, parse_mode="markdown")

    except Exception as e:
        # Трекинг ошибок
        mp.track(
            admin_id,
            "error_private_message",
            {
                "error_type": type(e).__name__,
                "error_message": str(e),
                "message_text": admin_message,
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
    admin_id = message.from_user.id

    # Трекинг получения пересланного сообщения
    mp.track(
        admin_id,
        "forwarded_message_received",
        {
            "forward_from_id": message.forward_from.id,
            "forward_date": str(message.forward_date),
            "message_text": message.text or message.caption,
        },
    )

    # Ask the user if they want to add this as a spam example
    row = [
        types.InlineKeyboardButton(text="⚠️ Спам", callback_data="spam_example:spam"),
        types.InlineKeyboardButton(
            text="💚 Не спам", callback_data="spam_example:not_spam"
        ),
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[row])

    await message.reply(
        "Добавить это сообщение в базу примеров?", reply_markup=keyboard
    )


@dp.callback_query(F.data.startswith("spam_example:"))
@log_function_call(logger)
async def process_spam_example_callback(callback: types.CallbackQuery):
    """
    Process the user's response to the spam example prompt.
    """
    admin_id = callback.from_user.id
    _, action = callback.data.split(":")

    try:
        info = await extract_original_message_info(callback.message)

        callback_answer_task = asyncio.create_task(
            bot(
                callback.answer(
                    (
                        "Сообщение добавлено как пример спама, пользователь удален из одобренных."
                        if action == "spam"
                        else "Сообщение добавлено как пример ценного сообщения."
                    ),
                )
            )
        )

        add_spam_example_task = asyncio.create_task(
            add_spam_example(
                info["text"],
                name=info["name"],
                bio=info["bio"],
                score=100 if action == "spam" else -100,
                admin_id=admin_id,
            )
        )

        remove_member_from_group_task = (
            asyncio.create_task(remove_member_from_group(member_id=info["user_id"]))
            if action == "spam"
            else None
        )

        edit_message_task = asyncio.create_task(
            bot.edit_message_text(
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
                text=f"Сообщение добавлено как пример {'спама' if action == 'spam' else 'ценного сообщения'}.",
            )
        )

        await asyncio.gather(
            callback_answer_task,
            add_spam_example_task,
            remove_member_from_group_task,
            edit_message_task,
        )

        # Трекинг успешного добавления примера
        mp.track(
            admin_id,
            "spam_example_added",
            {
                "message_text": info["text"],
                "name": info["name"],
                "bio": info["bio"],
                "action": action,
            },
        )

    except OriginalMessageExtractionError:
        # Трекинг ошибки извлечения информации
        mp.track(admin_id, "error_message_extraction", {"action": action})
        logger.error("Failed to extract original message info", exc_info=True)

    except Exception as e:
        # Трекинг других ошибок
        mp.track(
            admin_id,
            "error_spam_example_processing",
            {
                "error_type": type(e).__name__,
                "error_message": str(e),
                "action": action,
            },
        )
        logger.error(f"Error processing spam example: {e}", exc_info=True)


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
            user_id = original_message.forward_from.id
            user = await bot.get_chat(user_id)
            bio = user.bio
        except Exception:
            bio = None

        return {
            "user_id": user_id,
            "name": name,
            "bio": bio,
            "text": text,
        }

    raise OriginalMessageExtractionError(
        "Cannot extract meaningful message information from forwarded message"
    )
