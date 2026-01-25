import asyncio
import logging
import re
import time
from typing import List, Optional, Tuple

import logfire

from ..database.spam_examples import get_spam_examples
from .context_types import ContextResult, ContextStatus, SpamClassificationContext
from ..common.llms import (
    LocationNotSupported,
    RateLimitExceeded,
    get_openrouter_response,
)

logger = logging.getLogger(__name__)

MAX_RETRIES = 3

# Create metrics once at module level
spam_score_gauge = logfire.metric_gauge("spam_score")
attempts_histogram = logfire.metric_histogram("attempts")


class ExtractionFailedError(Exception):
    pass


@logfire.instrument(extract_args=True)
async def is_spam(
    comment: str,
    admin_ids: List[int] | None = None,
    context: SpamClassificationContext | None = None,
) -> Tuple[int, str]:
    """
    Классифицирует сообщение как спам или не спам

    Args:
        comment: Текст сообщения
        admin_ids: Список ID администраторов для получения их персональных примеров спама (опционально)
        context: Контекстная информация для классификации (опционально)

    Returns:
        tuple[int, str]:
            - int: Положительное число, если спам (0 до 100), отрицательное, если не спам (-100 до 0)
            - str: Комментарий с причиной оценки
    """
    # Use empty context if none provided
    if context is None:
        context = SpamClassificationContext()

    prompt = await get_system_prompt(
        admin_ids,
        include_linked_channel_guidance=context.include_linked_channel_guidance,
        include_stories_guidance=context.include_stories_guidance,
        include_reply_context_guidance=context.include_reply_guidance,
        include_account_age_guidance=context.include_account_age_guidance,
    )
    messages = get_messages(
        comment,
        context.name,
        context.bio,
        prompt,
        context,
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
                        "description": "Причина такой классификации и на основании каких элементов "
                        "входящих данных сделан такой вывод. Пиши по-русски.",
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
                    logger.info("Upstream provider rate limit hit, retrying immediately")
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
        "Spam classifier failed after %s attempts. comment=%r, context=%r, response=%r, last_error=%r",
        MAX_RETRIES,
        comment,
        context,
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
    prompt = """You are a spam message classifier for Telegram groups.

Your task: Analyze user messages and determine if they are spam or legitimate.
You will receive the message text, user name, and profile bio.
Return a spam score from -100 to +100, where:
- Positive scores = spam (0 to 100)
- Negative scores = legitimate (-100 to 0)
- Zero = uncertain

Also provide a confidence percentage (0-100) and a brief explanation."""

    if include_linked_channel_guidance:
        prompt += """

## LINKED CHANNEL ANALYSIS
This section contains information about a channel linked to the user's profile.

Key metrics to evaluate:
- subscribers: Number of channel subscribers
- total_posts: Total posts ever published
- age_delta: Channel age in months (format: "11mo")
- recent_posts: Content from recent channel posts (if available)

Consider the user HIGH RISK if these are true:
- subscribers < 200
- total_posts < 10
- age_delta < 5mo

CONTENT ANALYSIS: Examine recent_posts for spam indicators like:
- Pornographic content
- Advertising or promotions
- Scams or fraudulent offers
- Spam patterns

If recent_posts contain suspicious content, this is a STRONG spam indicator,
even if the current message appears innocent. Porn channels often use innocent comments
to drive traffic to their profiles."""

    if include_stories_guidance:
        prompt += """

## USER STORIES ANALYSIS
This section contains content from the user's active profile stories.

Spammers frequently use stories to hide promotional content, links, or scam offers
while posting "clean" comments to lure people into viewing their profile.

Flag as HIGH SPAM if stories contain:
- Advertising links or promotions
- Calls to join channels or follow profiles
- Money-making offers, crypto, or investment schemes
- Links to other channels or external sites

This is a strong spam indicator even if the message itself appears legitimate."""

    if include_account_age_guidance:
        prompt += """

## ACCOUNT AGE ANALYSIS
This section shows the age of the user's profile photo.

Account age is a powerful spam indicator because spammers create new accounts
and immediately start posting spam.

Risk assessment:
- photo_age=unknown OR no photo: HIGH spam risk for new messages
- photo_age=0mo (less than 1 month): HIGH spam risk - likely brand new account
- photo_age=1mo to 3mo: MEDIUM spam risk
- photo_age > 12mo: LOW spam risk - established account with old photo"""

    if include_reply_context_guidance:
        prompt += """

## DISCUSSION CONTEXT ANALYSIS
This section contains the original post that the user is replying to.

IMPORTANT: This context is provided ONLY to evaluate if the user's reply is relevant.
DO NOT score this context content as spam - it may contain any type of content.

HIGH SPAM INDICATOR: User replies that are completely unrelated to the discussion topic.
This is a common scam tactic: post irrelevant comments to "befriend" users,
then send investment/crypto offers via private messages.

Signs of irrelevant replies:
- Reply ignores the main topic of the original post
- Shifts to personal topics (books, movies, hobbies) with no connection
- Generic phrases like "interesting" or "I agree" without specific reference
- Self-promotion disguised as "helpful advice" on unrelated topics"""

    prompt += """

## RESPONSE FORMAT
Always respond with valid JSON in this exact format:
{
    "is_spam": true/false,
    "confidence": 0-100,
    "reason": "Причина такой классификации и на основании каких элементов входящих данных сделан такой вывод. Пиши по-русски."
}

## SPAM CLASSIFICATION EXAMPLES
"""

    # Get spam examples, including user-specific examples
    examples = await get_spam_examples(admin_ids)

    # Add examples to prompt
    for example in examples:
        # Create context from example data
        example_context = SpamClassificationContext(
            name=example.get("name"),
            bio=example.get("bio"),
            linked_channel=ContextResult(
                status=ContextStatus.FOUND,
                content=example.get("linked_channel_fragment"),
            )
            if example.get("linked_channel_fragment")
            else None,
            stories=ContextResult(
                status=ContextStatus.FOUND, content=example.get("stories_context")
            )
            if example.get("stories_context")
            else None,
            reply=example.get("reply_context"),
            account_age=ContextResult(
                status=ContextStatus.FOUND, content=example.get("account_age_context")
            )
            if example.get("account_age_context")
            else None,
        )

        example_request = format_spam_request(
            text=example["text"],
            context=example_context,
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
    context: SpamClassificationContext,
):
    user_request = format_spam_request(
        comment,
        context,
    )
    user_message = f"""{user_request}
Analyze this message and respond with JSON spam classification."""

    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_message},
    ]


def format_spam_request(
    text: str,
    context: Optional[SpamClassificationContext] = None,
) -> str:
    """
    Format a spam classification request for the LLM.

    Args:
        text: Message text to classify
        context: Spam classification context with all optional context data

    Returns:
        str: Formatted request with clear section headers
    """
    # Use empty context if none provided
    if context is None:
        context = SpamClassificationContext()
    request = f"""MESSAGE TO CLASSIFY:
{text}

"""

    if context.name:
        request += f"""USER NAME:
{context.name}

"""

    if context.bio:
        request += f"""USER BIO:
{context.bio}

"""

    if context.linked_channel and context.linked_channel.status.name == "FOUND":
        request += f"""LINKED CHANNEL INFO:
{context.linked_channel.content}

"""
    elif context.linked_channel and context.linked_channel.status.name == "EMPTY":
        request += """LINKED CHANNEL INFO:
no channel linked

"""
    elif context.linked_channel and context.linked_channel.status.name == "FAILED":
        request += f"""LINKED CHANNEL INFO:
verification failed: {context.linked_channel.error}

"""

    if context.stories and context.stories.status.name == "FOUND":
        request += f"""USER STORIES CONTENT:
{context.stories.content}

"""
    elif context.stories and context.stories.status.name == "EMPTY":
        request += """USER STORIES CONTENT:
no stories posted

"""
    elif context.stories and context.stories.status.name == "FAILED":
        request += f"""USER STORIES CONTENT:
verification failed: {context.stories.error}

"""

    if (
        context.account_age
        and context.account_age.status.name == "FOUND"
        and context.account_age.content
    ):
        # Handle both UserAccountInfo objects and legacy string content
        if hasattr(context.account_age.content, "to_prompt_fragment"):
            content_str = context.account_age.content.to_prompt_fragment()
        else:
            content_str = str(context.account_age.content)
        request += f"""ACCOUNT AGE INFO:
{content_str}

"""
    elif context.account_age and context.account_age.status.name == "EMPTY":
        request += """ACCOUNT AGE INFO:
no photo on the account

"""
    elif context.account_age and context.account_age.status.name == "FAILED":
        request += f"""ACCOUNT AGE INFO:
verification failed: {context.account_age.error}

"""

    if context.reply is not None:
        if context.reply == "[EMPTY]":
            request += """ORIGINAL POST BEING REPLIED TO:
[checked, none found]

"""
        else:
            request += f"""ORIGINAL POST BEING REPLIED TO:
{context.reply}

"""

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

    raise ExtractionFailedError(f"Failed to extract spam score from response: {response}")
