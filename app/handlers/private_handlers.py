from aiogram import F, types
from aiogram.filters import Command

from common.database.message_operations import get_message_history, save_message
from common.dp import dp
from common.llms import get_openrouter_response
from common.yandex_logging import get_yandex_logger
from utils import config

logger = get_yandex_logger(__name__)


@dp.message(F.chat.type == "private", ~F.text.startswith("/"))
async def handle_private_message(message: types.Message):
    """
    Отвечает пользователю от имени бота, используя LLM модели и контекст из истории сообщений
    """
    logger.debug("handle_private_message called")

    user_id = message.from_user.id
    user_message = message.text

    # Save user message to history
    await save_message(user_id, "user", user_message)

    # Get conversation history
    message_history = await get_message_history(user_id)

    # Read PRD for system context
    with open("PRD.md") as f:
        prd_text = f.read()

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

    ВАЖНО, чтобы ты отвечал от имени бота и ИСПОЛЬЗУЯ ТОН ПЕРСОНЫ БОТА,
    описанной выше.

    Учитывай предыдущий контекст разговора при ответе.

    Также обрати внимание, что твой ответ появится в телеграм-чате,
    поэтому разбивай текст на короткие абзацы
    и можешь назначительно использовать эмодзи.
    """

    # Combine system prompt with message history
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(message_history)

    # Get response from LLM
    response = await get_openrouter_response(messages)

    # Save bot's response to history
    await save_message(user_id, "assistant", response)

    # Send response to user
    await message.reply(response)
