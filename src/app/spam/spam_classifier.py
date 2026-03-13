"""Spam classification: prompt building, LLM calls, response parsing."""

import logging
from typing import List, Optional, Tuple

import logfire

from ..database import get_admin
from ..i18n import normalize_lang
from ..types import SpamClassificationContext
from .llm_client import call_llm_with_spam_classification
from .prompt_builder import build_system_prompt, format_spam_request

logger = logging.getLogger(__name__)


@logfire.no_auto_trace
@logfire.instrument(extract_args=True, record_return=True)
async def is_spam(
    comment: str,
    admin_ids: Optional[List[int]] = None,
    context: Optional[SpamClassificationContext] = None,
) -> Tuple[int, int, str]:
    """Classify message as spam or legitimate. Returns (score, confidence, reason)."""
    classification_context = context or SpamClassificationContext()

    lang = "en"
    if admin_ids:
        admin = await get_admin(admin_ids[0])
        if admin and admin.language_code:
            lang = normalize_lang(admin.language_code)

    messages = await _prepare_classification_request(
        comment, admin_ids, classification_context, lang
    )
    return await call_llm_with_spam_classification(messages)


async def _prepare_classification_request(
    comment: str,
    admin_ids: Optional[List[int]],
    context: SpamClassificationContext,
    lang: str = "en",
) -> List[dict]:
    system_prompt = await build_system_prompt(
        admin_ids=admin_ids,
        context=context,
        lang=lang,
    )
    user_request = format_spam_request(comment, context)
    user_message = f"{user_request}\nAnalyze this message and respond with JSON spam classification."
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
