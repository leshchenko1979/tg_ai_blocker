"""
LLM client for spam classification with retry logic and error handling.

This module provides the low-level interface to Cloudflare AI Gateway for spam classification,
handling HTTP requests, retries, rate limiting, and response parsing.

Key Features:
- Automatic retry logic for transient errors (rate limits, location restrictions)
- Proper handling of different error types (upstream vs gateway errors)
- Response parsing supporting both JSON and legacy text formats
- Comprehensive logging and metrics collection

Main Functions:
- call_llm_with_spam_classification(): Call LLM with retry logic for spam classification
- parse_classification_response(): Parse LLM responses into (score, reason) tuples

Error Handling:
- RateLimitExceeded: Handled with appropriate wait times
- LocationNotSupported: Treated as transient error with retry
- Other exceptions: Logged and retried up to MAX_RETRIES times
- ClassificationError: Raised when all retries are exhausted
"""

import asyncio
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import logfire

from ..common.llms import (
    LocationNotSupported,
    RateLimitExceeded,
    get_llm_response_with_fallback,
)

logger = logging.getLogger(__name__)

# Constants
MAX_RETRIES = 3
SPAM_CLASSIFICATION_SCHEMA: Dict[str, Any] = {
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

# Legacy format parsing patterns
LEGACY_RESPONSE_PATTERN = re.compile(r"<[^>]+>(.*?)<[^>]+>", re.IGNORECASE | re.DOTALL)
LEGACY_END_TAG_PATTERN = re.compile(r"^(.*)<[^>]+>", re.IGNORECASE | re.DOTALL)

# Response parsing constants
RESPONSE_SPAM_YES = "да"
RESPONSE_SPAM_NO = "нет"


# Create metrics once at module level
spam_score_gauge = logfire.metric_gauge("spam_score")
attempts_histogram = logfire.metric_histogram("attempts")


class ClassificationError(Exception):
    """
    Base exception for spam classification failures.

    Raised when the LLM classification process fails after all retry attempts.
    This includes network errors, parsing failures, and other unrecoverable issues.
    """

    pass


class ExtractionFailedError(ClassificationError):
    """
    Exception raised when LLM response parsing fails.

    This occurs when the response cannot be parsed in either JSON format
    or the legacy text format, indicating malformed or unexpected response structure.
    """

    pass


async def call_llm_with_spam_classification(
    messages: List[Dict[str, str]],
) -> Tuple[int, int, str]:
    """
    Call LLM with retry logic for transient errors.

    Args:
        messages: Messages array for LLM API

    Returns:
        Tuple[int, int, str]: (score, confidence, reason) where score is -100 to 100, confidence is 0-100, reason is explanation

    Raises:
        ClassificationError: If all retries fail
    """

    last_response = None
    last_error = None
    transient_errors = 0

    for attempt in range(1, MAX_RETRIES + 1):
        with logfire.span(f"Getting spam classifier response, attempt #{attempt}"):
            try:
                response = await get_llm_response_with_fallback(
                    messages,
                    temperature=0.0,
                    response_format=SPAM_CLASSIFICATION_SCHEMA,
                )
                last_response = response
                logger.info(f"Spam classifier response: {response}")
                score, confidence, reason = parse_classification_response(response)
                spam_score_gauge.set(score)
                attempts_histogram.record(attempt)
                return score, confidence, reason

            except (RateLimitExceeded, LocationNotSupported) as e:
                error_type = (
                    "rate limit" if isinstance(e, RateLimitExceeded) else "location"
                )
                logger.warning(f"{error_type.title()} error on attempt {attempt}: {e}")
                if isinstance(e, RateLimitExceeded):
                    await _handle_rate_limit_error(e)
                # Both are transient - continue to next attempt
                continue
            except Exception as e:
                last_error = e
                transient_errors += 1
                logger.warning(
                    f"Unexpected error on attempt {attempt} (error {transient_errors}/{MAX_RETRIES}): {e}"
                )
                # Continue to next attempt for unexpected errors too

    # All retries exhausted
    error_details = {
        "max_retries": MAX_RETRIES,
        "total_attempts": attempt,
        "transient_errors": transient_errors,
        "last_response": last_response,
        "last_error_type": type(last_error).__name__ if last_error else None,
        "last_error_message": str(last_error) if last_error else None,
    }

    logger.error(
        f"Spam classification failed after {MAX_RETRIES} attempts", extra=error_details
    )

    error_message = f"Classification failed after {MAX_RETRIES} attempts"
    if last_error:
        error_message += f": {type(last_error).__name__}: {last_error}"

    raise ClassificationError(error_message) from last_error


async def _handle_rate_limit_error(error: RateLimitExceeded) -> None:
    """
    Handle rate limit errors with appropriate wait times.

    For upstream provider errors, retry immediately.
    For Cloudflare AI Gateway errors, wait until the reset time.
    """
    if error.is_upstream_error:
        # For upstream provider errors, continue immediately
        logger.info("Upstream provider rate limit hit, retrying immediately")
        return

    # For Cloudflare AI Gateway errors, wait until reset_time
    reset_time_seconds = int(error.reset_time) / 1000
    current_time = time.time()
    wait_time = reset_time_seconds - current_time

    if wait_time > 0:
        reset_time_str = time.strftime(
            "%Y-%m-%d %H:%M:%S", time.gmtime(reset_time_seconds)
        )
        logger.info(
            f"Cloudflare AI Gateway rate limit hit, waiting {wait_time:.2f} seconds until {reset_time_str}"
        )
        await asyncio.sleep(wait_time)


def _parse_json_response(response: str) -> Optional[Tuple[int, int, str]]:
    """
    Try to parse response as JSON format.

    Args:
        response: Raw response string from the LLM

    Returns:
        Optional[Tuple[int, int, str]]: (score, confidence, reason) if parsing succeeds, None otherwise
    """
    try:
        data = json.loads(response)
        if not isinstance(data, dict):
            return None

        is_spam = data.get("is_spam", False)
        confidence = data.get("confidence", 0)
        reason = data.get("reason", "No reason provided")

        score = confidence if is_spam else -confidence
        return score, confidence, reason
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _parse_legacy_response(response: str) -> Optional[Tuple[int, int, str]]:
    """
    Try to parse response as legacy text format.

    Args:
        response: Raw response string from the LLM

    Returns:
        Optional[Tuple[int, int, str]]: (score, confidence, reason) if parsing succeeds, None otherwise
    """
    # Extract content from tags
    match = LEGACY_RESPONSE_PATTERN.search(response)
    if match:
        answer = match[1].strip()
    else:
        # If there's only a closing tag, take everything before it
        match_end = LEGACY_END_TAG_PATTERN.search(response)
        answer = match_end[1].strip() if match_end else response.strip()

    parts = answer.lower().split()
    if len(parts) >= 2:
        spam_indicator = parts[0]
        confidence_str = parts[1].replace("%", "").strip()

        try:
            confidence = int(confidence_str)
        except ValueError:
            return None

        if spam_indicator == RESPONSE_SPAM_YES:
            score = confidence
            reason = f"Классифицировано как спам с уверенностью {score}%"
            return score, confidence, reason
        elif spam_indicator == RESPONSE_SPAM_NO:
            score = -confidence
            reason = f"Классифицировано как не спам с уверенностью {confidence}%"
            return score, confidence, reason

    return None


def parse_classification_response(response: str) -> Tuple[int, int, str]:
    """
    Parse the LLM response to extract spam score, confidence, and reasoning.

    Supports both JSON format responses and legacy text format for backward compatibility.

    Args:
        response: Raw response string from the LLM

    Returns:
        Tuple[int, int, str]: (score, confidence, reason) where score is -100 to 100, confidence is 0-100, reason is explanation text

    Raises:
        ExtractionFailedError: If response cannot be parsed in any supported format
    """
    # First try to parse as JSON
    json_result = _parse_json_response(response)
    if json_result is not None:
        return json_result

    # Fallback to legacy text format parsing
    legacy_result = _parse_legacy_response(response)
    if legacy_result is not None:
        return legacy_result

    raise ExtractionFailedError(
        f"Failed to parse classification response in any supported format: {response}"
    )
