from aiogram import F, types
from aiogram.filters import Command

from common.database.message_operations import get_message_history, save_message
from common.database.spam_examples import get_spam_examples
from common.dp import dp
from common.llms import get_openrouter_response
from common.yandex_logging import get_yandex_logger, log_function_call
from spam_classifier import is_spam
from utils import config

logger = get_yandex_logger(__name__)


@dp.message(F.chat.type == "private", ~F.text.startswith("/"))
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
    with open("PRD.md") as f:
        prd_text = f.read()

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
