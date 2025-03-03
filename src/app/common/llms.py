import contextlib
import os
from typing import cast

import aiohttp
import logfire


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

    def __init__(self, reset_time: int, is_upstream_error: bool = False):
        self.reset_time = reset_time
        self.is_upstream_error = is_upstream_error
        super().__init__(f"Rate limit exceeded, reset at {reset_time}")


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
    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json",
    }

    model = "google/gemini-2.0-flash-exp:free"

    data = {"model": model, "messages": messages, "temperature": 0.3}

    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=data,
        ) as response:
            result = await response.json()

            logfire.debug("OpenRouter response", status=response.status, result=result)

            try:
                return result["choices"][0]["message"]["content"]

            except (KeyError, IndexError) as e:
                error = result.get("error", {})
                if error.get("code") == 429:
                    reset_time = (
                        error.get("metadata", {})
                        .get("headers", {})
                        .get("X-RateLimit-Reset", 0)
                    )
                    # Проверяем, является ли это ошибкой от upstream-провайдера
                    metadata = error.get("metadata", {})
                    is_upstream_error = False
                    if metadata.get("raw"):
                        raw_error = metadata["raw"]
                        if (
                            "quota exceeded" in raw_error.lower()
                            or "resource exhausted" in raw_error.lower()
                        ):
                            is_upstream_error = True
                            reset_time = 0  # Для ошибок upstream-провайдера сбрасываем reset_time

                    logfire.info(
                        "OpenRouter rate limit exceeded",
                        reset_time=reset_time,
                        is_upstream_error=is_upstream_error,
                        response=result,
                    )
                    raise RateLimitExceeded(reset_time, is_upstream_error) from e

                if error.get("code") == 500:
                    logfire.exception(
                        "OpenRouter internal server error", result=result, error=error
                    )
                    raise InternalServerError() from e

                # Handle location not supported error
                metadata = error.get("metadata", {})
                if metadata.get("raw"):
                    with contextlib.suppress(KeyError, TypeError):
                        raw_error = metadata["raw"]
                        if "User location is not supported" in raw_error:
                            provider = metadata.get("provider_name", "unknown")
                            logfire.info(
                                "Location not supported",
                                provider=provider,
                                response=result,
                            )
                            raise LocationNotSupported(provider) from e
                error_msg = (
                    error.get("message") if isinstance(error, dict) else str(error)
                )
                logfire.exception(
                    "OpenRouter API error", response=result, error=error_msg
                )
                raise RuntimeError(f"OpenRouter API error: {error_msg}") from e
