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
            f"Retryable error on attempt {retry_state.attempt_number}/4: "
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


def sanitize_html(text: str | None) -> str:
    """
    Escapes special characters for Telegram HTML format.
    See: https://core.telegram.org/bots/api#html-style
    """
    if text is None:
        return ""

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


def get_system_config():
    """Get system configuration from config.yaml"""
    config = load_config()
    return config.get("system", {})


# System constants loaded from config
_system_config = None


def get_project_channel_url():
    """Get project channel URL"""
    global _system_config
    if _system_config is None:
        _system_config = get_system_config()
    return _system_config.get("project_channel", "https://t.me/ai_antispam")


def get_spam_guide_url():
    """Get spam guide URL"""
    global _system_config
    if _system_config is None:
        _system_config = get_system_config()
    return _system_config.get("spam_guide_url", "https://t.me/ai_antispam/7")


def get_setup_guide_url():
    """Get setup guide URL"""
    global _system_config
    if _system_config is None:
        _system_config = get_system_config()
    return _system_config.get("setup_guide_url", "https://t.me/ai_antispam/14")


def get_affiliate_url():
    """Get affiliate program URL"""
    global _system_config
    if _system_config is None:
        _system_config = get_system_config()
    return _system_config.get(
        "affiliate_url", "https://telegram.org/tour/affiliate-programs/"
    )


def get_webhook_timeout():
    """Get webhook timeout"""
    global _system_config
    if _system_config is None:
        _system_config = get_system_config()
    return _system_config.get("webhook_timeout", 55)


def get_dotted_path(json: dict, path: str, raise_on_missing: bool = False):
    """
    Получает значение из JSON по заданному пути.

    Можно указывать *, чтобы произвести поиск по всем элементам словаря.

    Например, для json = {"message": {"chat": {"title": "title", "username": "username"}}}
    get_dotted_path(json, "message.chat.title") вернет "title"
    get_dotted_path(json, "*.*.title") вернет "title"
    get_dotted_path(json, "non-existent.path") поднимет исключение KeyError
    """
    current_path = path
    current_json = json
    while True:
        if "." not in current_path:
            if current_path in current_json:
                return current_json[current_path]
            elif raise_on_missing:
                raise KeyError(f"Key {path} not found in {json}")
            else:
                return None
        next_step, rest = current_path.split(".", 1)
        if next_step == "*":
            for value in current_json.values():
                if isinstance(value, dict):
                    result = get_dotted_path(value, rest, False)
                    if result is not None:
                        return result
            if raise_on_missing:
                raise KeyError(f"Key {path} not found in {json}")
            else:
                return None
        if next_step in current_json:
            current_json = current_json[next_step]
            current_path = rest
        elif raise_on_missing:
            raise KeyError(f"Key {next_step} not found in {json}")
        else:
            return None
