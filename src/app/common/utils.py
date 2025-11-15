import logging
from typing import Any, Dict

import yaml
from aiogram.exceptions import TelegramBadRequest
from aiohttp import ClientError, ClientOSError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# Network errors that should be retried
RETRYABLE_ERRORS = (
    ClientOSError,  # Connection reset by peer, etc.
    ClientError,  # Other aiohttp client errors
    OSError,  # Low-level OS errors
    ConnectionError,  # Generic connection errors
    TimeoutError,  # Timeout errors
)

# Permanent errors that should not be retried
PERMANENT_ERRORS = (TelegramBadRequest,)  # User blocked bot, chat not found, etc.

# Tenacity retry decorator for network operations
retry_on_network_error = retry(
    stop=stop_after_attempt(4),  # 4 attempts total (1 initial + 3 retries)
    wait=wait_exponential(multiplier=0.5, min=0.5, max=10),  # 0.5s to 10s backoff
    retry=retry_if_exception_type(RETRYABLE_ERRORS),
    reraise=True,  # Re-raise the last exception if all retries fail
    before_sleep=lambda retry_state: (
        logger.info(
            f"Retryable error on attempt {retry_state.attempt_number}/{retry_state.attempt_number + 2}: "
            f"{retry_state.outcome.exception() if retry_state.outcome else 'Unknown error'}. Retrying..."
        )
        if retry_state.attempt_number <= 3
        else logger.warning(
            f"All retries failed with error: {retry_state.outcome.exception() if retry_state.outcome else 'Unknown error'}",
            exc_info=True,
        )
    ),
)


def load_config() -> Dict[str, Any]:
    """
    Загрузка конфигурации
    """
    with open("config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    logger.debug("Configuration loaded successfully")
    return config


config = load_config()


def remove_lines_to_fit_len(text: str, max_len: int) -> str:
    """
    Удаляет строки из входного текста, чтобы уместиться в максимальную длину

    Args:
        text (str): Входной текст
        max_len (int): Максимальная длина текста

    Returns:
        str: Обработанный текст
    """
    splitted = text.split("\n")

    while len(text) > max_len - len("...\n") and len(splitted) > 2:
        half = len(splitted) // 2
        text = "\n".join(splitted[:half] + ["..."] + splitted[half + 1 :])
        splitted = splitted[:half] + splitted[half + 1 :]

    if len(text) > max_len:
        text = text[: max_len - len("...")] + "..."

    return text


def sanitize_html(text: str) -> str:
    """
    Escapes special characters for Telegram HTML format.
    See: https://core.telegram.org/bots/api#html-style
    """
    # HTML entities that need to be escaped
    html_entities = {
        "&": "&amp;",  # Must be first
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
    }
    for char, entity in html_entities.items():
        text = text.replace(char, entity)
    return text


def sanitize_llm_html(text: str) -> str:
    """
    Sanitizes LLM-generated HTML content, allowing only safe Telegram HTML tags.
    This is designed for content where we expect HTML formatting from a controlled source.
    """
    import re

    # Allow only these safe HTML tags: <b>, <i>, </b>, </i>
    allowed_tags = ["<b>", "</b>", "<i>", "</i>"]

    # First, temporarily replace allowed tags with placeholders
    placeholders = {}
    for i, tag in enumerate(allowed_tags):
        placeholder = f"__ALLOWED_TAG_{i}__"
        placeholders[placeholder] = tag
        text = text.replace(tag, placeholder)

    # Escape all remaining HTML characters
    text = sanitize_html(text)

    # Restore allowed tags
    for placeholder, tag in placeholders.items():
        text = text.replace(placeholder, tag)

    return text


def clean_alert_text(text: str | None) -> str | None:
    """Очищает текст от обёртки тревоги/уведомления, если она присутствует."""
    if not text:
        return text
    # Проверяем наличие служебных маркеров
    if "⚠️ ТРЕВОГА!" in text or "⚠️ ВТОРЖЕНИЕ!" in text or "Содержание угрозы:" in text:
        try:
            # Находим содержание угрозы
            start_idx = text.find("Содержание угрозы:")
            if start_idx != -1:
                start_idx += len("Содержание угрозы:")
                # Ищем конец содержания
                end_idx = text.find("Вредоносное сообщение уничтожено", start_idx)
                if end_idx == -1:
                    end_idx = text.find("Ссылка на сообщение", start_idx)
                if end_idx == -1:
                    end_idx = text.find("ℹ️ Подробнее", start_idx)
                if end_idx != -1:
                    cleaned = text[start_idx:end_idx].strip()
                else:
                    cleaned = text[start_idx:].strip()
                # Если после очистки остались служебные строки, убираем их
                lines = [
                    line
                    for line in cleaned.splitlines()
                    if line.strip()
                    and not any(
                        marker in line
                        for marker in [
                            "⚠️ ТРЕВОГА!",
                            "⚠️ ВТОРЖЕНИЕ!",
                            "Группа:",
                            "Нарушитель:",
                            "Вредоносное сообщение уничтожено",
                            "ℹ️ Подробнее",
                            "Ссылка на сообщение",
                        ]
                    )
                ]
                return "\n".join(lines).strip()
        except Exception as e:
            logger.error(f"Error cleaning alert text: {e}")
    return text
