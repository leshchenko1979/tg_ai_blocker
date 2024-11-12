import os
from typing import Any, Dict

import yaml

from common.yandex_logging import get_yandex_logger

logger = get_yandex_logger(__name__)


def load_config() -> Dict[str, Any]:
    """
    Загрузка конфигурации
    """
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    logger.trace("Configuration loaded successfully")
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
