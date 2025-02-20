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


class RateLimitExceeded(Exception):
    """Raised when OpenRouter rate limit is exceeded"""

    def __init__(self, reset_time: int):
        self.reset_time = reset_time
        super().__init__(f"Rate limit exceeded, reset at {reset_time}")


class LocationNotSupported(Exception):
    """Raised when user location is not supported by the provider"""

    def __init__(self, provider: str):
        self.provider = provider
        super().__init__(f"Location not supported for provider: {provider}")


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

            logfire.debug("OpenRouter response", result=result)

            if response.status != 200:
                error = result.get("error", {})
                if isinstance(error, dict):
                    if error.get("code") == 429:
                        reset_time = (
                            error.get("metadata", {})
                            .get("headers", {})
                            .get("X-RateLimit-Reset", 0)
                        )
                        logfire.info(
                            "OpenRouter rate limit exceeded",
                            reset_time=reset_time,
                            response=result,
                        )
                        raise RateLimitExceeded(reset_time)

                    # Handle location not supported error
                    metadata = error.get("metadata", {})
                    if metadata.get("raw"):
                        try:
                            raw_error = metadata["raw"]
                            if "User location is not supported" in raw_error:
                                provider = metadata.get("provider_name", "unknown")
                                logfire.info(
                                    "Location not supported",
                                    provider=provider,
                                    response=result,
                                )
                                raise LocationNotSupported(provider)
                        except (KeyError, TypeError):
                            pass

                error_msg = (
                    error.get("message") if isinstance(error, dict) else str(error)
                )
                logfire.exception(
                    "OpenRouter API error", response=result, error=error_msg
                )
                raise RuntimeError(f"OpenRouter API error: {error_msg}")

            if not result.get("choices"):
                logfire.exception(
                    "Invalid OpenRouter API response format",
                    response=result,
                )
                raise RuntimeError(f"Invalid OpenRouter API response format: {result}")

            try:
                return result["choices"][0]["message"]["content"]
            except (KeyError, IndexError) as e:
                logfire.exception(
                    "Failed to extract content from OpenRouter response",
                    response=result,
                    error=str(e),
                )
                raise RuntimeError(
                    f"Failed to extract content from OpenRouter response: {e}. Response: {result}"
                ) from e
