from typing import Optional

from common.database.spam_examples import get_spam_examples
from common.llms import get_openrouter_response
from common.yandex_logging import get_yandex_logger
from utils import config

logger = get_yandex_logger(__name__)

base_prompt = """
Ты - классификатор спама. Пользователь подает тебе сообщения с текстом, именем и биографией (опционально), а ты должен определить, спам это или нет, и дать оценку своей уверенности в процентах.

ФОРМАТ:
<начало ответа>
да ХХХ%
<конец ответа>

ИЛИ

<начало ответа>
нет ХХХ%
<конец ответа>

где ХХХ% - уровень твоей уверенности от 0 до 100.

Больше ничего к ответу не добавляй.

ПРИМЕРЫ:

"""


async def get_prompt():
    """Get the full prompt with spam examples from Redis"""
    prompt = base_prompt

    # Get spam examples from Redis
    examples = await get_spam_examples()

    # Add examples to prompt
    for example in examples:
        prompt += f"""
<запрос>
<текст сообщения>
{example["text"]}
</текст сообщения>
{'<имя>' + example["name"] + '</имя>' if "name" in example else ''}
{'<биография>' + example["bio"] + '</биография>' if "bio" in example else ''}
</запрос>
<ответ>
{"да" if example["score"] > 0 else "нет"} {abs(example["score"])}%
</ответ>
"""
    return prompt


class ExtractionFailedError(Exception):
    pass


async def is_spam(comment: str, name: Optional[str] = None, bio: Optional[str] = None):
    """
    Классифицирует сообщение как спам или не спам

    Args:
        comment: Текст сообщения
        name: Имя отправителя (опционально)
        bio: Биография отправителя (опционально)

    Returns:
        int: Положительное число, если спам (0 до 100), отрицательное, если не спам (-100 до 0)
    """
    prompt = await get_prompt()
    
    user_message = f"""
<запрос>
<текст сообщения>
{comment}
</текст сообщения>
{f'<имя>{name}</имя>' if name else ''}
{f'<биография>{bio}</биография>' if bio else ''}
</запрос>
<ответ>
"""

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_message}
    ]

    MAX_RETRIES = 3

    for attempt in range(MAX_RETRIES):
        try:
            response = await get_openrouter_response(messages)
            logger.info(f"Spam classifier response: {response}")
            return extract_spam_score(response)
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1} failed: {str(e)}")
            if attempt == MAX_RETRIES - 1:
                raise ExtractionFailedError(
                    "Failed to extract spam score after 3 attempts"
                ) from e


def extract_spam_score(response: str):
    """
    Извлекает оценку спама из ответа LLM
    """
    response = response.strip().lower()
    if response.startswith("да"):
        score = int(response.replace("да", "").replace("%", "").strip())
        return score
    elif response.startswith("нет"):
        score = -int(response.replace("нет", "").replace("%", "").strip())
        return score
    else:
        raise ExtractionFailedError(
            f"Failed to extract spam score from response: {response}"
        )
