import asyncio
import pathlib
from typing import Any, Dict

from aiogram import F, types
from aiogram.filters import or_f

from ..common.bot import bot
from ..common.llms import get_openrouter_response
from ..common.mp import mp
from ..common.utils import config
from ..common.yandex_logging import get_yandex_logger, log_function_call
from ..database import (
    add_spam_example,
    get_message_history,
    get_spam_examples,
    remove_member_from_group,
    save_message,
)
from .dp import dp

logger = get_yandex_logger(__name__)


class OriginalMessageExtractionError(Exception):
    """Raised when original message information cannot be extracted"""


@dp.message(
    F.chat.type == "private",
    ~F.text.startswith("/"),
    ~F.forward_from,
    ~F.forward_origin,
)
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
            example_str += f"{'да' if example['score'] > 0 else 'нет'} {abs(example['score'])}%\n</ответ>"
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


@dp.message(F.chat.type == "private", or_f(F.forward_from, F.forward_origin))
@log_function_call(logger)
async def handle_forwarded_message(message: types.Message):
    """
    Handle forwarded messages in private chats.
    """
    admin_id = message.from_user.id

    # Трекинг получения пересланного сообщения
    track_data = {
        "forward_date": str(message.forward_date),
        "message_text": message.text or message.caption,
    }

    if message.forward_from:
        track_data["forward_from_id"] = message.forward_from.id
    elif message.forward_origin:
        track_data["forward_origin_type"] = message.forward_origin.type
        if hasattr(message.forward_origin, "sender_user_name"):
            track_data["forward_sender_name"] = message.forward_origin.sender_user_name

    mp.track(
        admin_id,
        "forwarded_message_received",
        track_data,
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

        tasks = [
            bot(
                callback.answer(
                    (
                        "Сообщение добавлено как пример спама, пользователь удален из одобренных."
                        if action == "spam"
                        else "Сообщение добавлено как пример ценного сообщения."
                    ),
                )
            ),
            add_spam_example(
                info["text"],
                name=info["name"],
                bio=info["bio"],
                score=100 if action == "spam" else -100,
                admin_id=admin_id,
            ),
            bot.edit_message_text(
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
                text=f"Сообщение добавлено как пример {'спама' if action == 'spam' else 'ценного сообщения'}.",
            ),
        ]

        if action == "spam":
            if info.get("user_id"):
                tasks.append(remove_member_from_group(member_id=info["user_id"]))
            else:
                logger.warning("User ID not found in info, skipping removal from group")

            # Добавляем удаление сообщения из группы, если есть информация о нем
            if info.get("group_chat_id") and info.get("group_message_id"):
                tasks.append(
                    bot.delete_message(
                        chat_id=info["group_chat_id"],
                        message_id=info["group_message_id"],
                    )
                )
            else:
                logger.warning(
                    "Group chat ID or message ID not found in info, skipping message deletion"
                )

        results = await asyncio.gather(
            *(asyncio.create_task(task) for task in tasks), return_exceptions=True
        )

        # Check if there are exceptions in results
        for result in results:
            if isinstance(result, Exception):
                logger.error(
                    f"Error in spam example processing: {result}", exc_info=True
                )

        # Трекинг успешного добавления примера
        track_data = {
            "message_text": info["text"],
            "name": info["name"],
            "bio": info["bio"],
            "action": action,
        }
        if info.get("group_chat_id"):
            track_data["group_chat_id"] = info["group_chat_id"]

        mp.track(admin_id, "spam_example_added", track_data)

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
    Extracts original message name, bio, chat_id and message info from a callback message.
    """
    # Проверяем наличие сообщения, на которое отвечают
    if not callback_message.reply_to_message:
        raise OriginalMessageExtractionError("No reply message found")

    original_message = callback_message.reply_to_message

    if original_message.forward_from_chat:
        raise OriginalMessageExtractionError(
            "Cannot extract meaningful message information from forwarded channel message"
        )

    text = original_message.text or original_message.caption

    if original_message.forward_from:
        # Обычное пересланное сообщение
        name = original_message.forward_from.full_name
        try:
            user = await bot.get_chat(original_message.forward_from.id)
            bio = user.bio
        except Exception:
            bio = None
    elif (
        original_message.forward_origin
        and original_message.forward_origin.type == "hidden_user"
    ):
        # Сообщение от скрытого пользователя
        name = original_message.forward_sender_name
        bio = None
    else:
        raise OriginalMessageExtractionError("Reply message is not a forwarded message")

    if name or text:
        result = {
            "user_id": original_message.forward_from.id
            if original_message.forward_from
            else None,
            "name": name,
            "bio": bio,
            "text": text,
        }

        # Добавляем информацию о сообщении из группы, если она есть
        if hasattr(original_message.forward_origin, "chat_id") and hasattr(
            original_message.forward_origin, "message_id"
        ):
            result["group_chat_id"] = original_message.forward_origin.chat_id
            result["group_message_id"] = original_message.forward_origin.message_id

        return result

    raise OriginalMessageExtractionError(
        "Cannot extract meaningful message information from forwarded message"
    )
