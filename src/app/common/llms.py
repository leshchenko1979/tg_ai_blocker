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

            # Handle API errors
            if error := result.get("error"):
                if error.get("code") == 429:
                    reset_time = (
                        error.get("metadata", {})
                        .get("headers", {})
                        .get("X-RateLimit-Reset", 0)
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
                        for msg in ["quota exceeded", "resource exhausted"]
                    )
                    if is_upstream_error:
                        reset_time = 0

                    logfire.info(
                        "Rate limit exceeded",
                        reset_time=reset_time,
                        is_upstream_error=is_upstream_error,
                    )
                    raise RateLimitExceeded(reset_time, is_upstream_error)

                if error.get("code") == 500:
                    logfire.exception("Internal server error", error=error)
                    raise InternalServerError()

                if "User location is not supported" in error.get("metadata", {}).get(
                    "raw", ""
                ):
                    provider = error.get("metadata", {}).get("provider_name", "unknown")
                    logfire.info("Location not supported", provider=provider)
                    raise LocationNotSupported(provider)

                error_msg = error.get("message", str(error))
                logfire.exception("API error", error=error_msg)
                raise RuntimeError(f"OpenRouter API error: {error_msg}")

            # Extract content from successful response
            try:
                content = (
                    result.get("choices", [{}])[0].get("message", {}).get("content")
                )
                if not content:
                    logfire.error("Invalid response format", response=result)
                    raise RuntimeError("Invalid OpenRouter response format")
                return content
            except (KeyError, IndexError, TypeError) as e:
                logfire.exception(
                    "Failed to parse response", response=result, error=str(e)
                )
                raise RuntimeError("Failed to parse OpenRouter response") from e
