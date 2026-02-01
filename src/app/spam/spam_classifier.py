"""
Spam classification coordinator.

This module provides the main API for spam classification, coordinating
between prompt building, LLM interaction, and response processing.

Key Functions:
- is_spam(): Main entry point for spam classification orchestration
"""

import logging
from typing import List, Optional, Tuple

from .context_types import SpamClassificationContext
from .llm_client import call_llm_with_spam_classification
from .prompt_builder import build_system_prompt, format_spam_request

logger = logging.getLogger(__name__)


async def is_spam(
    comment: str,
    admin_ids: Optional[List[int]] = None,
    context: Optional[SpamClassificationContext] = None,
) -> Tuple[int, str]:
    """
    Classify a message as spam or legitimate using LLM analysis.

    This is the main entry point for spam classification that orchestrates
    the entire process from prompt building through LLM interaction to response parsing.

    Args:
        comment: The message content to classify
        admin_ids: Optional list of admin IDs for personalized spam examples
        context: Optional contextual information for classification

    Returns:
        Tuple[int, str]:
            - int: Spam score (positive = spam 0-100, negative = legitimate -100-0)
            - str: Explanation of the classification decision

    Raises:
        ClassificationError: If classification fails after all retries
    """
    # Use empty context if none provided
    classification_context = context or SpamClassificationContext()

    # Prepare the classification request (prompt building and message formatting)
    messages = await _prepare_classification_request(
        comment, admin_ids, classification_context
    )

    # Call LLM with retry logic (handles all LLM interaction, retries, and response parsing)
    return await call_llm_with_spam_classification(messages)


async def _prepare_classification_request(
    comment: str,
    admin_ids: Optional[List[int]],
    context: SpamClassificationContext,
) -> List[dict]:
    """
    Prepare the messages for LLM classification request.

    Args:
        comment: The message content to classify
        admin_ids: Optional list of admin IDs for personalized spam examples
        context: Contextual information for classification

    Returns:
        List[dict]: Messages array ready for LLM API
    """
    # Build the system prompt
    system_prompt = await build_system_prompt(
        admin_ids=admin_ids,
        include_linked_channel_guidance=context.include_linked_channel_guidance,
        include_stories_guidance=context.include_stories_guidance,
        include_reply_context_guidance=context.include_reply_guidance,
        include_account_age_guidance=context.include_account_age_guidance,
    )

    # Create messages for LLM
    messages = _create_classification_messages(
        comment,
        context.name,
        context.bio,
        system_prompt,
        context,
    )

    return messages


def _create_classification_messages(
    comment: str,
    user_name: Optional[str],
    user_bio: Optional[str],
    system_prompt: str,
    context: SpamClassificationContext,
) -> List[dict]:
    """
    Create the messages array for LLM classification request.

    Formats the user message by combining the message text with contextual information
    and creates the complete message structure for the LLM API.

    Args:
        comment: The message content to classify
        user_name: User's display name (optional, may be None)
        user_bio: User's profile bio (optional, may be None)
        system_prompt: The system prompt with instructions and examples
        context: Full context for classification including user info and settings

    Returns:
        List[dict]: Message dictionaries ready for LLM API,
        containing system and user messages
    """
    user_request = format_spam_request(comment, context)
    user_message = f"{user_request}\nAnalyze this message and respond with JSON spam classification."

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
