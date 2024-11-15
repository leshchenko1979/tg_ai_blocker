import pathlib
from aiogram import F, types

from common.bot import bot
from common.database.message_operations import get_message_history, save_message
from common.database.spam_examples import add_spam_example, get_spam_examples
from common.dp import dp
from common.llms import get_openrouter_response
from common.yandex_logging import get_yandex_logger, log_function_call
from utils import config

logger = get_yandex_logger(__name__)


@dp.message(F.chat.type == "private", ~F.text.startswith("/"), ~F.forward)
@log_function_call(logger)
async def handle_private_message(message: types.Message):
    """
    Отвечает пользователю от имени бота, используя LLM модели и контекст из истории сообщений
    """

    user_id = message.from_user.id
    user_message = message.text

    # Save user message to history
    await save_message(user_id, "user", user_message)

    # Get conversation history
    message_history = await get_message_history(user_id)

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

    # Save bot's response to history
    await save_message(user_id, "assistant", response)

    # Send response to user
    await message.reply(response, parse_mode="markdown")


@dp.message(F.chat.type == "private", F.forward)
@log_function_call(logger)
async def handle_forwarded_message(message: types.Message):
    """
    Handle forwarded messages in private chats.
    """
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

    await message.reply("Добавить это сообщение в базу примеров?", reply_markup=keyboard)


@dp.callback_query(F.data.startswith("spam_example:"))
@log_function_call(logger)
async def process_spam_example_callback(callback_query: types.CallbackQuery):
    """
    Process the user's response to the spam example prompt.
    """
    _, action = callback_query.data.split(":")

    info = extract_original_message_info(callback_query.message)

    await add_spam_example(
        info["text"],
        name=info["name"],
        bio=info["bio"],
        score=100 if action == "spam" else -100,
    )

    if action == "spam":
        # Attempt to delete the original message if available
        if info["chat_id"] and info["message_id"]:
            try:
                await bot.delete_message(info["chat_id"], info["message_id"])
                await callback_query.answer(
                    "Сообщение добавлено как пример спама и оригинальное сообщение удалено."
                )
            except Exception as e:
                await callback_query.answer(
                    "Сообщение добавлено как пример спама, но не удалось удалить оригинальное сообщение."
                )
    elif action == "not_spam":
        await callback_query.answer("Сообщение добавлено как пример ценного сообщения.")

    # Update the original message text to reflect the user's choice
    await callback_query.message.edit_text(
        text=f"Сообщение добавлено как пример {'спама' if action == 'spam' else 'ценного сообщения'}.",
    )


def extract_original_message_info(callback_message: types.Message):
    """
    Extracts original message name, bio, chat_id, and message_id from a callback message.
    """
    original_message = (
        callback_message.reply_to_message.forward
        if callback_message.reply_to_message
        and callback_message.reply_to_message.forward
        else None
    )
    name = (
        original_message.from_user.full_name
        if original_message and original_message.from_user
        else None
    )
    bio = (
        original_message.from_user.bio
        if original_message and original_message.from_user
        else None
    )
    chat_id = original_message.chat.id if original_message else None
    message_id = original_message.message_id if original_message else None
    text = (
        callback_message.reply_to_message.text
        if callback_message.reply_to_message
        else None
    )

    return {
        "name": name,
        "bio": bio,
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
    }
