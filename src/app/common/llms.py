import asyncio
import logging
import os
import random
import ssl
import time
from typing import Any, Dict, List, Optional, Union

import aiohttp
import certifi
import logfire

# Constants
MAX_RETRY_ATTEMPTS = 10
DEFAULT_TEMPERATURE = 0.3
REQUEST_TIMEOUT_SECONDS = 15
FALLBACK_RESET_SECONDS = 60
MILLISECONDS_MULTIPLIER = 1000
DEFAULT_OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"

# Global SSL context for connection reuse
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

# Global variable to track the currently active OpenRouter model for round-robin
logger = logging.getLogger(__name__)

# Available OpenRouter models - actively maintained free models
MODELS = [
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "upstage/solar-pro-3:free",
    "arcee-ai/trinity-large-preview:free",
]

# Historical models (removed for various reasons):
# - Context window too small: google/gemma-3-12b-it:free
# - API errors (404/removed by provider): google/gemma-3-27b-it:free, minimax/minimax-m2:free, qwen/qwen3-30b-a3b:free
# - Poor performance/false positives: nvidia/nemotron-nano-9b-v2:free, arcee-ai/trinity-mini:free
# - Low success rate (0-40%): deepseek/deepseek-chat-v3.1:free, openai/gpt-oss-120b:free, moonshotai/kimi-k2:free,
#   tencent/hunyuan-a13b-instruct:free, deepseek/deepseek-r1-0528:free, cognitivecomputations/dolphin-mistral-24b-venice-edition:free
# - Rate limiting issues: openai/gpt-oss-20b:free
# - Trial/free period ended: xiaomi/mimo-v2-flash:free, kwaipilot/kat-coder-pro:free (Jan 12, 2026)
# - Mixed results (37-77% success): qwen/qwen3-14b:free, qwen/qwen3-coder:free, qwen/qwen3-235b-a22b:free,
#   deepseek/deepseek-chat-v3-0324:free, google/gemini-2.0-flash-exp:free, tngtech/deepseek-r1t2-chimera:free,
#   mistralai/devstral-2512:free, z-ai/glm-4.5-air:free, mistralai/mistral-small-3.2-24b-instruct:free


# Initialize with a random model from the available list
_current_model = random.choice(MODELS)
logger.debug("🎯 INITIAL MODEL SET: %s", _current_model)


class LLMException(Exception):
    """Base exception for OpenRouter API errors that may be transient."""


class RateLimitExceeded(LLMException):
    """Raised when OpenRouter or upstream provider rate limit is exceeded."""

    def __init__(self, reset_time: Union[str, int], is_upstream_error: bool = False):
        """Initialize rate limit exception.

        Args:
            reset_time: Time when rate limit resets (Unix timestamp in milliseconds)
            is_upstream_error: True if this is an upstream provider rate limit
        """
        self.reset_time = int(reset_time) if isinstance(reset_time, str) else reset_time
        self.is_upstream_error = is_upstream_error
        super().__init__(f"Rate limit exceeded, reset at {self.reset_time}")


class LocationNotSupported(LLMException):
    """Raised when user location is not supported by the provider."""

    def __init__(self, provider: str):
        """Initialize location not supported exception.

        Args:
            provider: The provider that doesn't support the location
        """
        self.provider = provider
        super().__init__(f"Location not supported for provider: {provider}")


class InternalServerError(LLMException):
    """Raised when OpenRouter returns an internal server error."""


class ModelNotFound(LLMException):
    """Raised when a model is not found or no longer available."""

    def __init__(self, model: str):
        """Initialize model not found exception.

        Args:
            model: The model identifier that was not found
        """
        self.model = model
        super().__init__(f"Model not found or unavailable: {model}")


# ===== Error Handling Functions =====


async def _handle_rate_limit_exception(
    exception: RateLimitExceeded, current_model: str
) -> None:
    """Handle rate limit exceptions by waiting or switching models.

    For upstream provider rate limits, logs and returns immediately.
    For OpenRouter rate limits, waits until the reset time if available.

    Args:
        exception: The RateLimitExceeded exception with reset time info
        current_model: The model that hit the rate limit
    """
    if exception.is_upstream_error:
        # For upstream provider rate limits, immediately try next model
        logger.info(
            "Upstream provider rate limit hit for model %s, trying next model",
            current_model,
        )
        return

    # For OpenRouter rate limits, wait until reset time
    if exception.reset_time:
        reset_time_seconds = int(exception.reset_time) / MILLISECONDS_MULTIPLIER
        wait_time = reset_time_seconds - time.time()
        if wait_time > 0:
            reset_time_str = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(reset_time_seconds)
            )
            logger.info(
                "OpenRouter rate limit hit for model %s, waiting %.2f seconds until %s",
                current_model,
                wait_time,
                reset_time_str,
            )
            await asyncio.sleep(wait_time)
            return

    # Reset time not available or already passed, continue to next model
    logger.warning(
        "Rate limit hit for model %s but reset time unavailable, trying next model",
        current_model,
    )


def _extract_rate_limit_reset_time(
    response: Optional[aiohttp.ClientResponse] = None,
    error_metadata: Optional[Dict[str, Any]] = None,
) -> int:
    """Extract rate limit reset time from response headers or error metadata.

    Args:
        response: Optional aiohttp response object to check headers
        error_metadata: Optional error metadata from response body

    Returns:
        Reset time as Unix timestamp in milliseconds
    """
    reset_time_str = None

    # Try to get from error metadata first (for body-based errors)
    if error_metadata:
        headers_data = error_metadata.get("headers", {})
        reset_time_str = headers_data.get("X-RateLimit-Reset")

    # Fall back to response headers if available
    if not reset_time_str and response and "X-RateLimit-Reset" in response.headers:
        reset_time_str = response.headers["X-RateLimit-Reset"]

    # Convert to int if we have a string, otherwise use fallback
    if reset_time_str:
        try:
            return int(reset_time_str)
        except (ValueError, TypeError):
            logger.warning(
                "Invalid reset time format: %s, using fallback",
                reset_time_str,
            )

    # Use current time + fallback seconds as final fallback
    fallback_time = int(
        (time.time() + FALLBACK_RESET_SECONDS) * MILLISECONDS_MULTIPLIER
    )
    logger.warning(
        "Rate limit hit but reset time not available, using fallback: %s",
        fallback_time,
    )
    return fallback_time


def _handle_http_errors(
    response: aiohttp.ClientResponse, result: Optional[Dict[str, Any]], model: str
) -> None:
    """Handle HTTP error responses from OpenRouter API.

    Args:
        response: The aiohttp response object
        result: Parsed JSON response body (may be None if parsing failed)
        model: The model that was requested

    Raises:
        RateLimitExceeded: For 429 status codes
        ModelNotFound: For 404 status codes
        aiohttp.ClientResponseError: For other HTTP errors
    """
    if response.status == 429:
        # Rate limit exceeded - extract reset time
        error_metadata = None
        if result and "error" in result:
            error_metadata = result["error"].get("metadata", {})

        reset_time = _extract_rate_limit_reset_time(response, error_metadata)
        raise RateLimitExceeded(reset_time, is_upstream_error=False)

    elif response.status == 404:
        # Model not found
        raise ModelNotFound(model)

    elif not response.ok:
        # Other HTTP errors - re-raise as ClientResponseError
        response.raise_for_status()


def _process_response_errors(result: Dict[str, Any], model: str) -> None:
    """Process and raise appropriate exceptions for errors found in OpenRouter response body.

    Args:
        result: The parsed JSON response from the API
        model: The model that was requested

    Raises:
        RateLimitExceeded: For 429 errors in response body
        ModelNotFound: For 404 errors in response body
        RuntimeError: For other API errors
    """
    if err := result.get("error"):
        error_code = err.get("code")
        if error_code == 429:
            # Rate limit error in response body
            reset_time = _extract_rate_limit_reset_time(
                error_metadata=err.get("metadata", {})
            )
            logger.warning(
                "OpenRouter returned 429 error in body: %s (model=%s)",
                err,
                model,
            )
            raise RateLimitExceeded(reset_time, is_upstream_error=False)
        elif error_code == 404:
            # Model not found error in response body
            logger.warning(
                "OpenRouter returned 404 error in body: %s (model=%s)",
                err,
                model,
            )
            raise ModelNotFound(model)
        else:
            logger.warning(
                "OpenRouter returned error in body: %s (model=%s)",
                err,
                model,
            )
            raise RuntimeError(f"OpenRouter error: {err}")


# ===== Public API Functions =====


def round_robin_with_start(models: List[str], start_model: Optional[str] = None):
    """Create a round-robin generator for model selection starting from a specific model.

    Each model is yielded twice before moving to the next one to provide
    better load distribution and retry capability.

    Args:
        models: List of model identifiers to cycle through
        start_model: Model to start the round-robin from (optional)

    Yields:
        Model identifiers in round-robin fashion
    """
    n = len(models)
    if start_model and start_model in models:
        start_idx = models.index(start_model)
    else:
        start_idx = 0
    idx = start_idx
    while True:
        # Try each model twice for better retry capability
        yield models[idx]
        yield models[idx]
        idx = (idx + 1) % n
        logger.debug("Round-robin switched to model: %s", models[idx])


# ===== Main API Function =====


@logfire.instrument()
async def get_openrouter_response(
    messages: List[Dict[str, Any]],
    temperature: float = DEFAULT_TEMPERATURE,
    response_format: Optional[Dict[str, Any]] = None,
) -> str:
    """Get a response from OpenRouter API with automatic model rotation and error handling.

    This function attempts to get a response from available OpenRouter models,
    automatically rotating through models on failures and handling rate limits
    appropriately.

    Args:
        messages: List of message dictionaries for the chat completion
        temperature: Sampling temperature (0.0 to 1.0)
        response_format: Optional response format specification

    Returns:
        The content of the response message

    Raises:
        RuntimeError: If all models fail to provide a response
        LLMException: For various OpenRouter-specific errors
    """
    global _current_model
    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json",
    }

    most_recent_exception = None
    num_models = len(MODELS)

    # Find starting index for current model
    try:
        start_idx = MODELS.index(_current_model)
    except ValueError:
        start_idx = 0

    # Use global SSL context for connection reuse
    connector = aiohttp.TCPConnector(ssl=_SSL_CONTEXT)

    async with aiohttp.ClientSession(connector=connector) as session:
        # Try each model once, but allow retries for rate limits
        for model_idx in range(num_models):
            current_model_idx = (start_idx + model_idx) % num_models
            current_model = MODELS[current_model_idx]
            _current_model = current_model

            try:
                result = await _request_openrouter(
                    current_model,
                    messages,
                    headers,
                    session,
                    temperature,
                    response_format,
                )
                # Check for errors in response body
                _process_response_errors(result, current_model)

                return _extract_content(result, current_model)

            except RateLimitExceeded as e:
                await _handle_rate_limit_exception(e, current_model)
                if not e.is_upstream_error and e.reset_time:
                    # For OpenRouter rate limits, we already waited in _handle_rate_limit_exception
                    # Retry the same model after waiting
                    model_idx -= 1  # Retry same model index
                most_recent_exception = e
                continue

            except (ModelNotFound, TimeoutError) as e:
                # Skip to next model immediately for unavailable models or timeouts
                error_msg = (
                    f"Model {current_model} not found or unavailable"
                    if isinstance(e, ModelNotFound)
                    else f"Timeout occurred with model {current_model}"
                )
                logger.warning("%s, trying next model", error_msg)
                most_recent_exception = e
                continue

            except Exception as e:
                most_recent_exception = e
                logger.warning(
                    "Unexpected error with model %s: %s", current_model, str(e)
                )
                continue

    if most_recent_exception:
        raise most_recent_exception
    raise RuntimeError("All OpenRouter models failed to provide a response")


async def _request_openrouter(
    model: str,
    messages: List[Dict[str, Any]],
    headers: Dict[str, str],
    session: aiohttp.ClientSession,
    temperature: float = DEFAULT_TEMPERATURE,
    response_format: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Make a single request to the OpenRouter API.

    Args:
        model: The model identifier to use
        messages: List of message dictionaries for the chat completion
        headers: HTTP headers including authorization
        session: The aiohttp client session to use
        temperature: Sampling temperature for the model
        response_format: Optional response format specification

    Returns:
        Parsed JSON response from the API

    Raises:
        RateLimitExceeded: When rate limit is hit
        ModelNotFound: When the requested model is not available
        aiohttp.ClientResponseError: For other HTTP errors
        Exception: For JSON parsing or other errors
    """
    api_base = os.getenv("OPENROUTER_API_BASE", DEFAULT_OPENROUTER_API_BASE)
    data = {"model": model, "messages": messages, "temperature": temperature}
    if response_format:
        data["response_format"] = response_format

    with logfire.span(
        "OpenRouter request/response", model=model, messages=messages
    ) as span:
        try:
            async with session.post(
                f"{api_base.rstrip('/')}/chat/completions",
                headers=headers,
                json=data,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
            ) as response:
                # Try to parse JSON response
                try:
                    result = await response.json()
                except Exception as parse_error:
                    # If JSON parsing fails, still try to handle HTTP errors
                    # but then re-raise the parsing error
                    _handle_http_errors(response, None, model)
                    # If we get here, HTTP was OK but JSON parsing failed
                    raise parse_error

                span.set_attribute("status", response.status)
                span.set_attribute("result", result)

                # Handle HTTP errors now that we have the parsed result
                _handle_http_errors(response, result, model)

                # If we get here, response was successful and JSON parsed correctly
                return result

        except Exception as e:
            span.record_exception(e)
            span.set_attribute("error", str(e))
            raise


def _extract_content(result: Dict[str, Any], model: str) -> str:
    """Extract the content string from an OpenRouter API response.

    Args:
        result: The parsed JSON response from the API
        model: The model that generated the response

    Returns:
        The content string from the response

    Raises:
        RuntimeError: If the response format is invalid or missing content
    """
    try:
        content = result.get("choices", [{}])[0].get("message", {}).get("content")
        if not content:
            logger.warning(
                "Invalid OpenRouter response format for model %s: %s",
                model,
                result,
            )
            raise RuntimeError("Invalid OpenRouter response format")
        return content
    except (KeyError, IndexError, TypeError) as e:
        logger.warning(
            "Failed to parse OpenRouter response for model %s: %s",
            model,
            result,
            exc_info=True,
        )
        raise RuntimeError("Failed to parse OpenRouter response") from e
