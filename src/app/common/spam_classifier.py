import logging
from typing import List, Optional

import logfire

from ..database.spam_examples import get_spam_examples
from .llms import LocationNotSupported, RateLimitExceeded, get_openrouter_response

logger = logging.getLogger(__name__)

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

MAX_RETRIES = 3


async def get_prompt(admin_ids: Optional[List[int]] = None):
    """Get the full prompt with spam examples from database"""
    prompt = base_prompt

    # Get spam examples, including user-specific examples
    examples = await get_spam_examples(admin_ids)

    # Add examples to prompt
    for example in examples:
        prompt += f"""
<запрос>
<текст сообщения>
{example["text"]}
</текст сообщения>
{'<имя>' + example["name"] + '</имя>' if example.get("name") else ''}
{'<биография>' + example["bio"] + '</биография>' if example.get("bio") else ''}
</запрос>
<ответ>
{"да" if example["score"] > 0 else "нет"} {abs(example["score"])}%
</ответ>
"""
    return prompt


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
    prompt = await get_prompt(admin_ids)

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
        {"role": "user", "content": user_message},
    ]

    last_response = None
    last_error = None
    attempt = 0

    while attempt < MAX_RETRIES:
        try:
            response = await get_openrouter_response(messages)
            last_response = response
            logger.info(f"Spam classifier response: {response}")
            score = extract_spam_score(response)
            logfire.metric_gauge("spam_score").set(score)
            return score
        except (RateLimitExceeded, LocationNotSupported) as e:
            # Don't count these errors towards retry attempts
            # Just log and continue the loop
            if isinstance(e, RateLimitExceeded):
                logfire.info(
                    "Rate limit exceeded in spam classifier",
                    reset_time=e.reset_time,
                    attempt=attempt,
                    admin_ids=admin_ids,
                )
            else:  # LocationNotSupported
                logfire.info(
                    "Provider location not supported in spam classifier",
                    provider=e.provider,
                    attempt=attempt,
                    admin_ids=admin_ids,
                )
            continue
        except Exception as e:
            last_error = e
            attempt += 1
            if attempt == MAX_RETRIES:
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
            continue


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
