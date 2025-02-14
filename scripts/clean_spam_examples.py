from dotenv import load_dotenv

# Загружаем переменные окружения до импортов
load_dotenv()

import asyncio
import logging
import os
from typing import Optional

import asyncpg
from src.app.database.postgres_connection import get_pool

logger = logging.getLogger(__name__)


def clean_alert_text(text: Optional[str]) -> Optional[str]:
    """Очищает текст от обертки тревоги"""
    if not text or "⚠️ ТРЕВОГА!" not in text:
        return text

    try:
        # Находим содержание угрозы
        start_idx = text.find("Содержание угрозы:") + len("Содержание угрозы:")
        end_idx = text.find("Вредоносное сообщение уничтожено")
        if start_idx > 0 and end_idx > 0:
            return text[start_idx:end_idx].strip()
    except Exception as e:
        logger.error(f"Error cleaning alert text: {e}")

    return text


async def clean_spam_examples():
    """Очищает все примеры спама от обертки тревоги"""
    pool = await get_pool()

    async with pool.acquire() as conn:
        # Получаем все примеры
        rows = await conn.fetch("SELECT id, text FROM spam_examples")

        cleaned = 0
        for row in rows:
            original_text = row['text']
            cleaned_text = clean_alert_text(original_text)

            if cleaned_text != original_text:
                # Обновляем текст в базе
                await conn.execute(
                    "UPDATE spam_examples SET text = $1 WHERE id = $2",
                    cleaned_text,
                    row['id']
                )
                cleaned += 1
                logger.info(f"Cleaned example {row['id']}")

        logger.info(f"Cleaned {cleaned} examples out of {len(rows)} total")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(clean_spam_examples())
