from dotenv import load_dotenv

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Загружаем переменные окружения до импортов
load_dotenv()

import asyncio
import logging

from src.app.database.postgres_connection import get_pool
from src.app.common.utils import clean_alert_text

logger = logging.getLogger(__name__)


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
