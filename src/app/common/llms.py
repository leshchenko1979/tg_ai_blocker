import logging
import os

import aiohttp
import logfire

# Global variable to track the last successful OpenRouter model
logger = logging.getLogger(__name__)

_last_model = None


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
async def get_openrouter_response(messages, temperature=0.3):
    global _last_model
    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json",
    }

    # Below commented out models are given with X/Y numbers - that is failure to success ratio

    models = [
        # "qwen/qwen3-14b:free", 74/47
        # "google/gemma-3-12b-it:free", Context window 8K - too small
        # "google/gemma-3-27b-it:free", Context window 8K - too small
        # "nvidia/nemotron-nano-9b-v2:free", false positives
        # "deepseek/deepseek-chat-v3.1:free", success rate 0%
        # "openai/gpt-oss-120b:free", success rate 0%
        "openai/gpt-oss-20b:free",
        # "z-ai/glm-4.5-air:free", success rate 57.14%
        # "qwen/qwen3-coder:free", success rate 37.5%
        # "moonshotai/kimi-k2:free", success rate 0%
        # "cognitivecomputations/dolphin-mistral-24b-venice-edition:free", success rate 20%
        # "tencent/hunyuan-a13b-instruct:free", success rate 0%
        "tngtech/deepseek-r1t2-chimera:free",
        # "mistralai/mistral-small-3.2-24b-instruct:free", success rate 50%
        # "deepseek/deepseek-r1-0528:free", success rate 0%
        # "qwen/qwen3-235b-a22b:free", success rate 37.5%
        "qwen/qwen3-30b-a3b:free",
        # "deepseek/deepseek-chat-v3-0324:free", 53/9
        # "google/gemini-2.0-flash-exp:free", 57/25
        "minimax/minimax-m2:free",
    ]
    model_gen = round_robin_with_start(models, _last_model)
    last_exception = None
    async with aiohttp.ClientSession() as session:
        for _ in range(10):
            _last_model = next(model_gen)
            try:
                result = await _request_openrouter(
                    _last_model, messages, headers, session, temperature
                )
                # Проверяем наличие ошибки в ответе
                if err := result.get("error"):
                    logger.warning(
                        "OpenRouter returned error in body: %s (model=%s)",
                        err,
                        _last_model,
                    )
                    raise RuntimeError(f"OpenRouter error: {err}")
                return _extract_content(result, _last_model)
            except Exception as e:
                last_exception = e
    if last_exception:
        raise last_exception
    raise RuntimeError("All OpenRouter models failed to provide a response")


async def _request_openrouter(model, messages, headers, session, temperature=0.3):
    data = {"model": model, "messages": messages, "temperature": temperature}
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
            span.record_exception(e)
            span.set_attribute("error", str(e))
            raise


def _extract_content(result, model):
    try:
        content = result.get("choices", [{}])[0].get("message", {}).get("content")
        if not content:
            logger.error(
                "Invalid OpenRouter response format for model %s: %s",
                model,
                result,
            )
            raise RuntimeError("Invalid OpenRouter response format")
        return content
    except (KeyError, IndexError, TypeError) as e:
        logger.exception(
            "Failed to parse OpenRouter response for model %s: %s",
            model,
            result,
        )
        raise RuntimeError("Failed to parse OpenRouter response") from e
