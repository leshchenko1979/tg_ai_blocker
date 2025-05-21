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


def round_robin_with_start(models, start_model=None):
    n = len(models)
    if start_model and start_model in models:
        start_idx = models.index(start_model)
    else:
        start_idx = 0
    idx = start_idx
    while True:
        # Try each model twice
        yield models[idx]
        yield models[idx]
        idx = (idx + 1) % n


@logfire.instrument()
async def get_openrouter_response(messages):
    global _last_successful_openrouter_model
    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json",
    }

    models = [
        "qwen/qwen3-14b:free",
        "google/gemma-3-12b-it:free",
        "google/gemma-3-27b-it:free",
        "qwen/qwen3-235b-a22b:free",
        "qwen/qwen3-30b-a3b:free",
        "deepseek/deepseek-chat-v3-0324:free",
        "google/gemini-2.0-flash-exp:free",
    ]
    model_gen = round_robin_with_start(models, _last_successful_openrouter_model)
    last_exception = None
    async with aiohttp.ClientSession() as session:
        for _ in range(10):
            model = next(model_gen)
            try:
                result = await _request_openrouter(model, messages, headers, session)
                # Проверяем наличие ошибки в ответе
                if err := result.get("error"):
                    logfire.warn(
                        "OpenRouter returned error in body", error=err, model=model
                    )
                    raise RuntimeError(f"OpenRouter error: {err}")
                _last_successful_openrouter_model = model
                return _extract_content(result, model)
            except Exception as e:
                last_exception = e
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
                raise_for_status=True,
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
