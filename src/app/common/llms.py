import os

import aiohttp
import logfire


async def get_yandex_response(messages):
    from yandex_cloud_ml_sdk import AsyncYCloudML

    sdk = AsyncYCloudML(
        folder_id=os.getenv("YANDEX_FOLDER_ID"), auth=os.getenv("YANDEX_GPT_API_KEY")
    )

    model = sdk.models.completions("yandexgpt")
    result = await model.configure(temperature=0.3).run(messages)
    return result.alternatives[0].text


async def get_openrouter_response(messages):
    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json",
    }

    model = "qwen/qwen-vl-plus:free"

    data = {"model": model, "messages": messages, "temperature": 0.3}

    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=data,
        ) as response:
            result = await response.json()

            if response.status != 200:
                error = result.get("error", "Unknown error")
                logfire.exception("OpenRouter API error", response=result, error=error)
                raise RuntimeError(f"OpenRouter API error: {error}")

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
