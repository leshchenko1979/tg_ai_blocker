import logging
import re
from typing import Any, Dict

import yaml

logger = logging.getLogger(__name__)


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


def sanitize_markdown(text: str) -> str:
    """
    Sanitizes text for Telegram Markdown (v1) format.

    В Markdown v1 (parse_mode="markdown") символы (* _ ` [) не экранируются, если используются парами для форматирования.
    Например:
    - *bold text* — не экранируется
    - _italic_ — не экранируется
    - some_variable_name — экранируется
    - [link](url) — не экранируется
    - `code` — не экранируется
    """
    # Сначала заменяем маркеры списка
    lines = text.split("\n")
    for i in range(len(lines)):
        if lines[i].strip().startswith("*   "):
            lines[i] = lines[i].replace("*   ", "•   ", 1)
    text = "\n".join(lines)

    # Спецслучай: если строка состоит только из формат-символов, экранируем все
    if text.strip() and all(c in "*_`[" for c in text.strip()):
        return "".join("\\" + c if c in "*_`[" else c for c in text)

    # Найти все валидные пары форматирования
    valid_formats = [
        (r"\*([^*\n]+)\*", "*"),
        (r"(?<![\w])_([^_\n]+)_(?![\w])", "_"),
        (r"`([^`\n]+)`", "`"),
        (r"\[([^\]]+)\]\([^)]+\)", "["),
    ]
    protected = set()
    for pattern, _ in valid_formats:
        for match in re.finditer(pattern, text):
            for i in range(match.start(), match.end()):
                protected.add(i)

    # Экранируем звездочки вне валидных пар
    result = []
    for i, char in enumerate(text):
        if i in protected:
            result.append(char)
        elif char == "*":
            result.append("\\*")
        else:
            result.append(char)
    partially_escaped = "".join(result)

    # Экранируем подчеркивания между букв/цифр вне валидных пар
    def escape_underscores(s, protected):
        chars = list(s)
        result = []
        i = 0
        while i < len(chars):
            if chars[i] == "_" and i not in protected:
                prev_char = chars[i - 1] if i > 0 else ""
                next_char = chars[i + 1] if i + 1 < len(chars) else ""
                if prev_char.isalnum() and next_char.isalnum():
                    result.append("\\_")
                    i += 1
                    continue
                elif (i == 0 and next_char.isalnum()) or (
                    i > 0 and not prev_char.isalnum() and next_char.isalnum()
                ):
                    result.append("\\_")
                    i += 1
                    continue
            result.append(chars[i])
            i += 1
        return "".join(result)

    return escape_underscores(partially_escaped, protected)


def sanitize_markdown_v2(text: str) -> str:
    """
    Escapes all special characters for Telegram MarkdownV2.
    See: https://core.telegram.org/bots/api#markdownv2-style
    """
    # List of all special characters in MarkdownV2
    special_chars = r"_ * [ ] ( ) ~ ` > # + - = | { } . !"
    for char in special_chars.split():
        text = text.replace(char, f"\\{char}")
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
