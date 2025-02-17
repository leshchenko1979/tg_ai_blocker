import asyncio
import logging
import pathlib
from typing import Any, Dict, cast

from aiogram import F, types
from aiogram.filters import or_f

from ..common.bot import bot
from ..common.llms import get_openrouter_response
from ..common.mp import mp
from ..common.utils import config
from ..database import (
    add_spam_example,
    get_admin_credits,
    get_message_history,
    get_spam_examples,
    initialize_new_admin,
    remove_member_from_group,
    save_message,
)
from ..database.constants import INITIAL_CREDITS
from .dp import dp

logger = logging.getLogger(__name__)


class OriginalMessageExtractionError(Exception):
    """Raised when original message information cannot be extracted"""


@dp.message(
    F.chat.type == "private",
    ~F.text.startswith("/"),
    ~F.forward_from,
    ~F.forward_origin,
)
async def handle_private_message(message: types.Message) -> str:
    """
    Отвечает пользователю от имени бота, используя LLM модели и контекст из истории сообщений
    """
    if not message.from_user:
        return "private_no_user_info"

    user = cast(types.User, message.from_user)
    admin_id = user.id
    admin_message = message.text

    if not admin_message:
        return "private_no_message_text"

    # Трекинг получения приватного сообщения
    mp.track(admin_id, "private_message_received", {"message_text": admin_message})

    # Initialize new administrator if needed
    is_new = await initialize_new_admin(admin_id)

    # Update Mixpanel profile with Telegram data
    mp.people_set(
        admin_id,
        {
            "$distinct_id": admin_id,
            "$first_name": user.first_name,
            "$last_name": user.last_name or "",
            "$name": user.username or user.first_name,
            "delete_spam_enabled": True,
            "credits": INITIAL_CREDITS if is_new else await get_admin_credits(admin_id),
        },
    )

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
            example_str = f"<пример>\n<запрос>\n<текст сообщения>\n{example['text']}\n</текст сообщения>"
            if "name" in example:
                example_str += f"\n<имя>{example['name']}</имя>"
            if "bio" in example:
                example_str += f"\n<биография>{example['bio']}</биография>"
            example_str += "\n</запрос>\n<ответ>\n"
            example_str += f"{'да' if example['score'] > 50 else 'нет'} {abs(example['score'])}%\n</ответ>"
            example_str += "\n</пример>"
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
        return "private_message_replied"

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
async def handle_forwarded_message(message: types.Message) -> str:
    """
    Handle forwarded messages in private chats.
    """
    if not message.from_user:
        return "private_forward_no_user_info"

    user = cast(types.User, message.from_user)
    admin_id = user.id

    # Трекинг получения пересланного сообщения
    track_data = {
        "forward_date": str(message.forward_date),
        "message_text": message.text or message.caption,
    }

    if message.forward_from:
        track_data["forward_from_id"] = message.forward_from.id
    elif message.forward_origin:
        track_data["forward_origin_type"] = message.forward_origin.type

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
    return "private_forward_prompt_sent"


@dp.callback_query(F.data.startswith("spam_example:"))
async def process_spam_example_callback(callback: types.CallbackQuery) -> str:
    """
    Process the user's response to the spam example prompt.
    """
    if not callback.from_user or not callback.data or not callback.message:
        return "spam_example_invalid_callback"

    user = cast(types.User, callback.from_user)
    admin_id = user.id
    _, action = callback.data.split(":")

    try:
        if not isinstance(callback.message, types.Message):
            return "spam_example_invalid_message_type"

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

        await asyncio.gather(*tasks)
        return "spam_example_processed"

    except OriginalMessageExtractionError as e:
        logger.error(f"Failed to extract original message info: {e}")
        await callback.answer(
            "❌ Не удалось получить информацию об исходном сообщении", show_alert=True
        )
        return "spam_example_extraction_error"
    except Exception as e:
        logger.error(f"Error processing spam example: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка", show_alert=True)
        return "spam_example_error"


async def extract_original_message_info(
    callback_message: types.Message,
) -> Dict[str, Any]:
    """
    Извлекает информацию об исходном сообщении из пересланного сообщения
    """
    if not callback_message.reply_to_message:
        raise OriginalMessageExtractionError("No reply_to_message found")

    original_message = callback_message.reply_to_message
    if not original_message.forward_from and not original_message.forward_origin:
        raise OriginalMessageExtractionError("No forward information found")

    info: Dict[str, Any] = {
        "text": original_message.text or original_message.caption or "[MEDIA_MESSAGE]",
        "name": None,
        "bio": None,
        "user_id": None,
        "group_chat_id": None,
        "group_message_id": None,
    }

    if original_message.forward_from:
        # Если есть прямая информация о пользователе
        user = original_message.forward_from
        info["name"] = user.full_name
        info["user_id"] = user.id
        user_info = await bot.get_chat(user.id)
        info["bio"] = user_info.bio if user_info else None
    elif original_message.forward_origin:
        # Если есть информация о происхождении сообщения
        origin = original_message.forward_origin
        if isinstance(origin, types.MessageOriginUser):
            info["name"] = origin.sender_user.full_name
        elif isinstance(origin, types.MessageOriginChannel):
            info["name"] = origin.chat.title
            info["group_chat_id"] = origin.chat.id
            info["group_message_id"] = origin.message_id

    return info
