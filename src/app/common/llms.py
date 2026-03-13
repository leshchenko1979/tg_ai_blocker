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

# SSL context with verification disabled (for direct IP gateway workaround)
_SSL_CONTEXT_INSECURE = ssl.create_default_context()
_SSL_CONTEXT_INSECURE.check_hostname = False
_SSL_CONTEXT_INSECURE.verify_mode = ssl.CERT_NONE

logger = logging.getLogger(__name__)

# Available models - actively maintained free models
MODELS = [
    "nvidia/nemotron-3-nano-30b-a3b:free",
    # "meta-llama/llama-3.3-70b-instruct:free",
    # "upstage/solar-pro-3:free", Times out every time
    "arcee-ai/trinity-large-preview:free",
    "stepfun/step-3.5-flash:free",
    #    "qwen/qwen3-next-80b-a3b-instruct:free", "Payment required"
]

# Current model for round-robin (initialized randomly)
_current_model = random.choice(MODELS)
logger.debug("Initial model set: %s", _current_model)


class LLMException(Exception):
    """Base exception for LLM API errors that may be transient."""


class RateLimitExceeded(LLMException):
    """Raised when provider rate limit is exceeded."""

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
    """Raised when provider returns an internal server error."""


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
    For provider rate limits, waits until the reset time if available.

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

    # For provider rate limits, wait until reset time
    if exception.reset_time:
        reset_time_seconds = int(exception.reset_time) / MILLISECONDS_MULTIPLIER
        wait_time = reset_time_seconds - time.time()
        if wait_time > 0:
            reset_time_str = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(reset_time_seconds)
            )
            logger.info(
                "Provider rate limit hit for model %s, waiting %.2f seconds until %s",
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
    """Handle HTTP error responses from LLM API.

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
    """Process and raise appropriate exceptions for errors found in API response body.

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
                "Provider returned 429 error in body: %s (model=%s)",
                err,
                model,
            )
            raise RateLimitExceeded(reset_time, is_upstream_error=False)
        elif error_code == 404:
            # Model not found error in response body
            logger.warning(
                "Provider returned 404 error in body: %s (model=%s)",
                err,
                model,
            )
            raise ModelNotFound(model)
        else:
            logger.warning(
                "Provider returned error in body: %s (model=%s)",
                err,
                model,
            )
            raise RuntimeError(f"Provider error: {err}")


# ===== Main API Functions =====


@logfire.no_auto_trace
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
        LLMException: For various provider-specific errors
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
                api_base = os.getenv("OPENROUTER_API_BASE", DEFAULT_OPENROUTER_API_BASE)
                result = await _request_chat_completions(
                    api_base,
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
    raise RuntimeError("All models failed to provide a response")


@logfire.no_auto_trace
@logfire.instrument(extract_args=True, record_return=True)
async def get_llm_response_with_fallback(
    messages: List[Dict[str, Any]],
    temperature: float = DEFAULT_TEMPERATURE,
    response_format: Optional[Dict[str, Any]] = None,
) -> str:
    """Get a response from LLM with automatic fallback from custom gateway to OpenRouter.

    This function first attempts to get a response from custom gateway (single try).
    If that fails due to connectivity or other issues, it automatically falls back
    to OpenRouter with full retry logic (model rotation, rate limit handling).

    Args:
        messages: List of message dictionaries for the chat completion
        temperature: Sampling temperature (0.0 to 1.0)
        response_format: Optional response format specification

    Returns:
        The content of the response message

    Raises:
        RuntimeError: If both custom gateway and OpenRouter fail
    """
    # Try custom gateway first
    try:
        return await get_primary_gateway_response(
            messages, temperature, response_format
        )
    except Exception as e:
        logger.warning(f"custom gateway failed: {type(e).__name__}: {e}")
        logger.info("Falling back to OpenRouter")

        # Try OpenRouter as fallback (with full retry logic)
        try:
            return await get_openrouter_response(messages, temperature, response_format)
        except Exception as fallback_error:
            logger.error(
                f"OpenRouter fallback also failed: {type(fallback_error).__name__}: {fallback_error}"
            )
            # Re-raise the original Cloudflare error as the primary failure
            raise RuntimeError(
                f"Both custom gateway and OpenRouter failed. custom gateway error: {e}"
            ) from e


@logfire.no_auto_trace
@logfire.instrument(extract_args=True, record_return=True)
async def get_primary_gateway_response(
    messages: List[Dict[str, Any]],
    temperature: float = DEFAULT_TEMPERATURE,
    response_format: Optional[Dict[str, Any]] = None,
) -> str:
    """Get a response from custom gateway API.

    This function makes a request to custom gateway using the configured
    model and authentication. Unlike OpenRouter, custom gateway uses a single model
    through dynamic routing.

    Args:
        messages: List of message dictionaries for the chat completion
        temperature: Sampling temperature (0.0 to 1.0)
        response_format: Optional response format specification

    Returns:
        The content of the response message

    Raises:
        RuntimeError: If the request fails
        LLMException: For various Cloudflare-specific errors
    """
    headers = {
        "Authorization": f"Bearer {os.getenv('CUSTOM_GATEWAY_API_KEY')}",
        "Content-Type": "application/json",
    }
    if host := os.getenv("AI_GATEWAY_HOST"):
        headers["Host"] = host

    # Get model from environment variable
    model = os.getenv("CUSTOM_GATEWAY_MODEL")
    if not model:
        raise ValueError("CUSTOM_GATEWAY_MODEL environment variable is required")

    # Use SSL context: disable verification when AI_GATEWAY_SSL_VERIFY is false/0
    ssl_verify = os.getenv("AI_GATEWAY_SSL_VERIFY", "true").lower() not in (
        "false",
        "0",
        "no",
    )
    ssl_context = _SSL_CONTEXT if ssl_verify else _SSL_CONTEXT_INSECURE
    connector = aiohttp.TCPConnector(ssl=ssl_context)

    api_base = os.getenv("API_BASE")
    if not api_base:
        raise ValueError("API_BASE environment variable is required")

    async with aiohttp.ClientSession(connector=connector) as session:
        try:
            result = await _request_chat_completions(
                api_base,
                model,
                messages,
                headers,
                session,
                temperature,
                response_format,
            )
            # Check for errors in response body
            _process_response_errors(result, model)

            return _extract_content(result, model)

        except Exception as e:
            logger.warning("custom gateway API request failed: %s", str(e))
            raise


async def _request_chat_completions(
    api_base: str,
    model: str,
    messages: List[Dict[str, Any]],
    headers: Dict[str, str],
    session: aiohttp.ClientSession,
    temperature: float = DEFAULT_TEMPERATURE,
    response_format: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Make a single POST request to a chat completions endpoint.

    Args:
        api_base: Base URL for the API (e.g. https://openrouter.ai/api/v1)
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
    data: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if response_format:
        data["response_format"] = response_format

    async with session.post(
        f"{api_base.rstrip('/')}/chat/completions",
        headers=headers,
        json=data,
        timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
    ) as response:
        try:
            result = await response.json()
        except Exception as parse_error:
            _handle_http_errors(response, None, model)
            raise parse_error

        _handle_http_errors(response, result, model)
        return result


def _extract_content(result: Dict[str, Any], model: str) -> str:
    """Extract the content string from an LLM API response.

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
                "Invalid API response format for model %s: %s",
                model,
                result,
            )
            raise RuntimeError("Invalid API response format")
        return content
    except (KeyError, IndexError, TypeError) as e:
        logger.warning(
            "Failed to parse API response for model %s: %s",
            model,
            result,
            exc_info=True,
        )
        raise RuntimeError("Failed to parse API response") from e
