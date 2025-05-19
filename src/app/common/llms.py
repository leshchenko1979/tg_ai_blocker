import asyncio
import os
from typing import cast

import aiohttp
import logfire

# Global variable to track the last successful OpenRouter model
_last_successful_openrouter_model = None


async def get_yandex_response(messages):
    from yandex_cloud_ml_sdk import AsyncYCloudML

    folder_id = cast(str, os.getenv("YANDEX_FOLDER_ID"))
    auth = cast(str, os.getenv("YANDEX_GPT_API_KEY"))

    sdk = AsyncYCloudML(folder_id=folder_id, auth=auth)

    model = sdk.models.completions("yandexgpt")
    result = await model.configure(temperature=0.3).run(messages)
    return result.alternatives[0].text


class LLMException(Exception):
    """Raised when OpenRouter returns a transient error"""


class RateLimitExceeded(LLMException):
    """Raised when OpenRouter rate limit is exceeded"""

    def __init__(self, reset_time: str | int, is_upstream_error: bool = False):
        self.reset_time = int(reset_time) if isinstance(reset_time, str) else reset_time
        self.is_upstream_error = is_upstream_error
        super().__init__(f"Rate limit exceeded, reset at {self.reset_time}")


class LocationNotSupported(LLMException):
    """Raised when user location is not supported by the provider"""

    def __init__(self, provider: str):
        self.provider = provider
        super().__init__(f"Location not supported for provider: {provider}")


class InternalServerError(LLMException):
    """Raised when OpenRouter returns an internal server error"""

    def __init__(self):
        super().__init__("OpenRouter internal server error")


@logfire.instrument()
async def get_openrouter_response(messages):
    global _last_successful_openrouter_model
    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json",
    }

    primary_model = "qwen/qwen3-30b-a3b:free"
    fallback_models = [
        "deepseek/deepseek-chat-v3-0324:free",
        "google/gemini-2.0-flash-exp:free",
        # сюда можно добавить другие резервные модели
    ]
    # Use a set to avoid duplicates, and a list to preserve order
    models_to_try = []
    seen = set()
    if (
        _last_successful_openrouter_model
        and _last_successful_openrouter_model not in seen
    ):
        models_to_try.append(_last_successful_openrouter_model)
        seen.add(_last_successful_openrouter_model)
    for m in [primary_model] + fallback_models:
        if m not in seen:
            models_to_try.append(m)
            seen.add(m)

    last_exception = None
    async with aiohttp.ClientSession() as session:
        for model in models_to_try:
            try:
                result = await _request_openrouter(model, messages, headers, session)
                if error := result.get("error"):
                    _handle_api_error(error, model)
                # Update the global variable on success
                _last_successful_openrouter_model = model
                return _extract_content(result, model)
            except RateLimitExceeded as e:
                last_exception = e
                continue  # пробуем следующую модель
            except Exception as e:
                last_exception = e
                logfire.error(
                    "Fallback model failed", error=str(last_exception), model=model
                )
                continue
    if last_exception:
        raise last_exception
    raise RuntimeError("All OpenRouter models failed to provide a response")


async def _request_openrouter(model, messages, headers, session):
    data = {"model": model, "messages": messages, "temperature": 0.3}
    with logfire.span(
        "OpenRouter request/response", model=model, messages=messages
    ) as span:
        try:
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=data,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                result = await response.json()
                span.set_attribute("status", response.status)
                span.set_attribute("result", result)
                return result
        except Exception as e:
            span.set_level("error")
            span.record_exception(e)
            span.set_attribute("error", str(e))
            raise


def _handle_api_error(error, model):
    if error.get("code") == 429:
        _handle_rate_limit_error(error, model)
    if error.get("code") == 500:
        _handle_internal_server_error(error, model)
    if "User location is not supported" in error.get("metadata", {}).get("raw", ""):
        _handle_location_not_supported_error(error, model)
    _handle_generic_api_error(error, model)


def _handle_rate_limit_error(error, model):
    reset_time = (
        error.get("metadata", {}).get("headers", {}).get("X-RateLimit-Reset", 0)
    )
    if isinstance(reset_time, str):
        try:
            reset_time = int(reset_time)
        except (ValueError, TypeError):
            reset_time = 0
            logfire.error(
                "Failed to parse reset_time",
                reset_time_value=reset_time,
            )
    is_upstream_error = any(
        msg in error.get("metadata", {}).get("raw", "").lower()
        for msg in [
            "quota exceeded",
            "resource exhausted",
            "rate-limited upstream",
        ]
    )
    if is_upstream_error:
        reset_time = 0
    logfire.info(
        "Rate limit exceeded",
        reset_time=reset_time,
        is_upstream_error=is_upstream_error,
        model=model,
    )
    raise RateLimitExceeded(reset_time, is_upstream_error)


def _handle_internal_server_error(error, model):
    logfire.exception("Internal server error", error=error, model=model)
    raise InternalServerError()


def _handle_location_not_supported_error(error, model):
    provider = error.get("metadata", {}).get("provider_name", "unknown")
    logfire.info("Location not supported", provider=provider, model=model)
    raise LocationNotSupported(provider)


def _handle_generic_api_error(error, model):
    error_msg = error.get("message", str(error))
    logfire.exception("API error", error=error_msg, model=model)
    raise RuntimeError(f"OpenRouter API error: {error_msg}")


def _extract_content(result, model):
    try:
        content = result.get("choices", [{}])[0].get("message", {}).get("content")
        if not content:
            logfire.error("Invalid response format", response=result, model=model)
            raise RuntimeError("Invalid OpenRouter response format")
        return content
    except (KeyError, IndexError, TypeError) as e:
        logfire.exception(
            "Failed to parse response",
            response=result,
            error=str(e),
            model=model,
        )
        raise RuntimeError("Failed to parse OpenRouter response") from e
