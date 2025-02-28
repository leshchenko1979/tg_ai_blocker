import logging
from typing import List, Optional

import logfire

from ..database.spam_examples import get_spam_examples
from .llms import TransientOpenRouterError, get_openrouter_response

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


class ExtractionFailedError(Exception):
    pass


async def is_spam(
    comment: str,
    name: str | None = None,
    bio: str | None = None,
    admin_ids: List[int] | None = None,
):
    """
    Классифицирует сообщение как спам или не спам

    Args:
        comment: Текст сообщения
        name: Имя отправителя (опционально)
        bio: Биография отправителя (опционально)
        admin_ids: Список ID администраторов для получения их персональных примеров спама (опционально)

    Returns:
        int: Положительное число, если спам (0 до 100), отрицательное, если не спам (-100 до 0)
    """
    prompt = await get_system_prompt(admin_ids)
    messages = get_messages(comment, name, bio, prompt)

    last_response = None
    last_error = None
    attempt = 0
    unknown_errors = 0

    while unknown_errors < MAX_RETRIES:
        attempt += 1
        with logfire.span(f"Getting spam classifier response, attempt #{attempt}"):
            try:
                response = await get_openrouter_response(messages)
                last_response = response
                logger.info(f"Spam classifier response: {response}")
                score = extract_spam_score(response)
                logfire.metric_gauge("spam_score").set(score)
                logfire.metric_gauge("attempts").set(attempt)
                return score
            except TransientOpenRouterError as e:
                # Don't count transient errors towards retry attempts
                continue
            except Exception as e:
                last_error = e
                unknown_errors += 1

    logfire.exception(
        "Spam classifier failed",
        response=last_response,
        error=str(last_error),
        comment=comment,
        name=name,
        bio=bio,
        admin_ids=admin_ids,
        prompt=prompt,
        _tags=["spam_classifier_failed"],
    )
    raise ExtractionFailedError(
        f"Failed to classify message after {MAX_RETRIES} attempts: {str(last_error)}"
    ) from last_error


async def get_system_prompt(admin_ids: Optional[List[int]] = None):
    """Get the full prompt with spam examples from database"""
    prompt = """Ты - классификатор спама. Пользователь подает тебе сообщения с текстом, именем и биографией (опционально),
а ты должен определить, спам это или нет, и дать оценку своей уверенности в процентах.

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

    # Get spam examples, including user-specific examples
    examples = await get_spam_examples(admin_ids)

    # Add examples to prompt
    for example in examples:
        example_request = format_spam_request(
            text=example["text"], name=example.get("name"), bio=example.get("bio")
        )

        prompt += f"""
{example_request}
<ответ>
{"да" if example["score"] > 0 else "нет"} {abs(example["score"])}%
</ответ>
"""
    return prompt


def get_messages(comment: str, name: str | None, bio: str | None, prompt: str):
    user_request = format_spam_request(comment, name, bio)
    user_message = f"""
{user_request}
<ответ>
"""

    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_message},
    ]


def format_spam_request(
    text: str, name: Optional[str] = None, bio: Optional[str] = None
) -> str:
    """
    Форматирует запрос для классификации спама.

    Args:
        text: Текст сообщения
        name: Имя отправителя (опционально)
        bio: Биография отправителя (опционально)

    Returns:
        str: Отформатированный запрос
    """
    request = f"""
<запрос>
<текст сообщения>
{text}
</текст сообщения>
"""

    if name:
        request += f"<имя>{name}</имя>\n"

    if bio:
        request += f"<биография>{bio}</биография>\n"

    request += "</запрос>"
    return request


def extract_spam_score(response: str):
    """
    Извлекает оценку спама из ответа LLM
    """
    parts = response.strip().lower().split()
    if parts[0] == "да":
        return int(parts[1].replace("%", "").strip())
    elif parts[0] == "нет":
        return -int(parts[1].replace("%", "").strip())
    else:
        raise ExtractionFailedError(
            f"Failed to extract spam score from response: {response}"
        )
