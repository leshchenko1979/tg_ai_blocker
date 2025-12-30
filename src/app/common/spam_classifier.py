import asyncio
import json
import logging
import re
import time
from typing import List, Optional, Tuple

import logfire

from ..database.spam_examples import get_spam_examples
from .llms import LocationNotSupported, RateLimitExceeded, get_openrouter_response

logger = logging.getLogger(__name__)

MAX_RETRIES = 3

# Create metrics once at module level
spam_score_gauge = logfire.metric_gauge("spam_score")
attempts_histogram = logfire.metric_histogram("attempts")


class ExtractionFailedError(Exception):
    pass


async def is_spam(
    comment: str,
    name: str | None = None,
    bio: str | None = None,
    admin_ids: List[int] | None = None,
    linked_channel_fragment: str | None = None,
    stories_context: str | None = None,
    reply_context: str | None = None,
    account_age_context: str | None = None,
) -> Tuple[int, str]:
    """
    Классифицирует сообщение как спам или не спам

    Args:
        comment: Текст сообщения
        name: Имя отправителя (опционально)
        bio: Биография отправителя (опционально)
        admin_ids: Список ID администраторов для получения их персональных примеров спама (опционально)

    Returns:
        tuple[int, str]:
            - int: Положительное число, если спам (0 до 100), отрицательное, если не спам (-100 до 0)
            - str: Комментарий с причиной оценки
    """
    prompt = await get_system_prompt(
        admin_ids,
        include_linked_channel_guidance=linked_channel_fragment is not None,
        include_stories_guidance=stories_context is not None,
        include_reply_context_guidance=reply_context is not None,
        include_account_age_guidance=account_age_context is not None,
    )
    messages = get_messages(
        comment,
        name,
        bio,
        prompt,
        linked_channel_fragment,
        stories_context,
        reply_context,
        account_age_context,
    )

    last_response = None
    last_error = None
    attempt = 0
    unknown_errors = 0

    schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "spam_classification",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "is_spam": {
                        "type": "boolean",
                        "description": "True если сообщение является спамом, иначе False",
                    },
                    "confidence": {
                        "type": "integer",
                        "description": "Уверенность в классификации от 0 до 100",
                        "minimum": 0,
                        "maximum": 100,
                    },
                    "reason": {
                        "type": "string",
                        "description": "Причина такой классификации и какие элементы входящих данных содержат спам",
                    },
                },
                "required": ["is_spam", "confidence", "reason"],
                "additionalProperties": False,
            },
        },
    }

    while unknown_errors < MAX_RETRIES:
        attempt += 1
        with logfire.span(f"Getting spam classifier response, attempt #{attempt}"):
            try:
                response = await get_openrouter_response(
                    messages, temperature=0.0, response_format=schema
                )
                last_response = response
                logger.info(f"Spam classifier response: {response}")
                score, reason = extract_spam_score(response)
                spam_score_gauge.set(score)
                attempts_histogram.record(attempt)
                return score, reason

            except RateLimitExceeded as e:
                if e.is_upstream_error:
                    # Для ошибок upstream-провайдера продолжаем немедленно
                    logger.info(
                        "Upstream provider rate limit hit, retrying immediately"
                    )
                else:
                    # Для ошибок OpenRouter ждем до reset_time
                    # Convert milliseconds to seconds for reset_time
                    reset_time_seconds = int(e.reset_time) / 1000
                    wait_time = reset_time_seconds - time.time()
                    if wait_time > 0:
                        reset_time_str = time.strftime(
                            "%Y-%m-%d %H:%M:%S", time.localtime(reset_time_seconds)
                        )
                        logger.info(
                            f"OpenRouter rate limit hit, waiting {wait_time:.2f} seconds until {reset_time_str}"
                        )
                        await asyncio.sleep(wait_time)
                continue
            except LocationNotSupported as e:
                # Location not supported тоже считаем транзиентной ошибкой
                logger.info(f"Location not supported for provider {e.provider}")
                continue

            except Exception as e:
                last_error = e
                unknown_errors += 1

    logger.warning(
        "Spam classifier failed after %s attempts. comment=%r, name=%r, bio=%r, response=%r, last_error=%r",
        MAX_RETRIES,
        comment,
        name,
        bio,
        last_response,
        last_error,
    )
    raise ExtractionFailedError(
        f"Failed to classify message after {MAX_RETRIES} attempts: {str(last_error)}"
    ) from last_error


async def get_system_prompt(
    admin_ids: Optional[List[int]] = None,
    include_linked_channel_guidance: bool = False,
    include_stories_guidance: bool = False,
    include_reply_context_guidance: bool = False,
    include_account_age_guidance: bool = False,
):
    """Get the full prompt with spam examples from database"""
    prompt = """Ты - классификатор спама. Администратор группы телеграм подает тебе
тексты сообщений от пользователей, а также их имена и биографии из профиля,
а ты должен определить, спам это или нет, и дать оценку своей уверенности в процентах."""

    if include_linked_channel_guidance:
        prompt += """

Раздел <связанный канал> содержит данные о канале, привязанном к профилю автора.

Обращай внимание на эти поля:
- subscribers — количество подписчиков канала
- total_posts — сколько постов опубликовано за всё время
- age_delta — разница между первым и последним постом (в месяцах, формат "11mo")
- recent_posts — содержание последних постов канала (если доступно)

Считай пользователя подозрительным, если у него одновременно:
- subscribers < 10
- total_posts < 50
- age_delta < 10mo

АНАЛИЗИРУЙ СОДЕРЖАНИЕ ПОСТОВ: Если recent_posts содержит признаки порно-контента, рекламы,
мошенничества, спама или других подозрительных материалов, это ВЫСОКИЙ индикатор спама,
даже если основной комментарий выглядит безобидно. Каналы с порно-контентом часто используются
для привлечения трафика через невинные комментарии."""

    if include_stories_guidance:
        prompt += """

Раздел <истории_пользователя> содержит информацию из актуальных сторис профиля автора.
Спамеры часто используют сторис для размещения рекламы, ссылок на каналы или мошеннических предложений,
оставляя при этом "чистый" комментарий, чтобы спровоцировать пользователя зайти в профиль.

Если в историях есть:
- Рекламные ссылки
- Призывы перейти в канал/профиль
- Предложения заработка, криптовалют, инвестиций
- Ссылки на другие каналы

Считай это ВЫСОКИМ индикатором спама, даже если сам комментарий выглядит безобидно."""

    if include_account_age_guidance:
        prompt += """

Раздел <возраст_аккаунта> содержит информацию о "возрасте" (давности) фотографии профиля пользователя.
Это мощный индикатор спама, так как спамеры часто создают аккаунты и сразу начинают рассылку.

Интерпретация:
- `photo_age=unknown` или отсутствует фото: ВЫСОКИЙ риск спама для новых сообщений.
- `photo_age=0mo` (меньше месяца): ВЫСОКИЙ риск спама. Вероятно, аккаунт "свежий".
- `photo_age=1mo`...`3mo`: СРЕДНИЙ риск.
- `photo_age > 12mo`: НИЗКИЙ риск (фактор доверия). Старое фото говорит о долгоживущем аккаунте."""

    if include_reply_context_guidance:
        prompt += """

Раздел <контекст_обсуждения> содержит текст поста, на который отвечает пользователь.

ВЫСОКИЙ ИНДИКАТОР СПАМА: Комментарии, полностью не связанные с темой обсуждения.
Это распространенная тактика мошенников: сначала "подружиться" через нерелевантные комментарии,
затем в личных сообщениях предлагать инвестиции, криптовалюту или другие схемы.

ПРИЗНАКИ ОТСУТСТВИЯ РЕЛЕВАНТНОСТИ:
- Комментарий игнорирует основную тему оригинального поста
- Переход на личные темы (книги, фильмы, хобби) без связи с обсуждением
- Общие фразы вроде "интересно", "согласен" без конкретного отношения к контенту
- Самореклама под видом "полезного совета" по несвязанной теме"""

    prompt += """

ИСПОЛЬЗУЙ JSON ФОРМАТ ОТВЕТА:
{
    "is_spam": boolean,
    "confidence": integer (0-100),
    "reason": string
}

ПРИМЕРЫ:
"""

    # Get spam examples, including user-specific examples
    examples = await get_spam_examples(admin_ids)

    # Add examples to prompt
    for example in examples:
        example_request = format_spam_request(
            text=example["text"], name=example.get("name"), bio=example.get("bio")
        )

        is_spam_ex = example["score"] > 0
        confidence_ex = abs(example["score"])

        prompt += f"""
{example_request}
<ответ>
{{
    "is_spam": {"true" if is_spam_ex else "false"},
    "confidence": {confidence_ex}
}}
</ответ>
"""
    return prompt


def get_messages(
    comment: str,
    name: str | None,
    bio: str | None,
    prompt: str,
    linked_channel_fragment: str | None,
    stories_context: str | None = None,
    reply_context: str | None = None,
    account_age_context: str | None = None,
):
    user_request = format_spam_request(
        comment,
        name,
        bio,
        linked_channel_fragment,
        stories_context,
        reply_context,
        account_age_context,
    )
    user_message = f"""
{user_request}
<ответ>
"""

    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_message},
    ]


def format_spam_request(
    text: str,
    name: Optional[str] = None,
    bio: Optional[str] = None,
    linked_channel_fragment: Optional[str] = None,
    stories_context: Optional[str] = None,
    reply_context: Optional[str] = None,
    account_age_context: Optional[str] = None,
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

    if linked_channel_fragment:
        request += f"<связанный_канал>{linked_channel_fragment}</связанный_канал>\n"

    if stories_context:
        request += (
            f"<истории_пользователя>\n{stories_context}\n</истории_пользователя>\n"
        )

    if account_age_context:
        request += f"<возраст_аккаунта>\n{account_age_context}\n</возраст_аккаунта>\n"

    if reply_context:
        request += f"<контекст_обсуждения>\n{reply_context}\n</контекст_обсуждения>\n"

    request += "</запрос>"
    return request


def extract_spam_score(response: str):
    """
    Извлекает оценку спама и причину из ответа LLM.
    Поддерживает JSON формат и старый текстовый формат.
    """
    # First try to parse as JSON
    try:
        import json

        data = json.loads(response)
        if isinstance(data, dict):
            is_spam = data.get("is_spam", False)
            confidence = data.get("confidence", 0)
            reason = data.get("reason", "No reason provided")

            score = confidence if is_spam else -confidence
            return score, reason
    except (json.JSONDecodeError, KeyError, TypeError):
        pass

    # Fallback to old text format parsing
    flags = re.IGNORECASE | re.DOTALL
    match = re.search(r"<[^>]+>(.*?)<[^>]+>", response, flags=flags)
    if match:
        answer = match[1].strip()
    else:
        # Если есть только закрывающий тег, берём всё до него
        match_end = re.search(r"^(.*)<[^>]+>", response, flags=flags)
        answer = match_end[1].strip() if match_end else response.strip()

    parts = answer.lower().split()
    if len(parts) >= 2:
        if parts[0] == "да":
            score = int(parts[1].replace("%", "").strip())
            return score, f"Классифицировано как спам с уверенностью {score}%"
        elif parts[0] == "нет":
            score = -int(parts[1].replace("%", "").strip())
            return score, f"Классифицировано как не спам с уверенностью {abs(score)}%"

    raise ExtractionFailedError(
        f"Failed to extract spam score from response: {response}"
    )
