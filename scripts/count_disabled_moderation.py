import asyncio
import os
from dotenv import load_dotenv
import asyncpg

load_dotenv()

async def count_groups_with_disabled_moderation():
    # Получаем параметры подключения из переменных окружения с теми же значениями по умолчанию
    conn = await asyncpg.connect(
        host=os.getenv("PG_HOST", "localhost"),
        port=int(os.getenv("PG_PORT", "5432")),
        user=os.getenv("PG_USER", "postgres"),
        password=os.getenv("PG_PASSWORD", ""),
        database=os.getenv("PG_DB", "ai_spam_bot")
    )

    try:
        total = await conn.fetchval("SELECT COUNT(*) FROM groups")
        disabled = await conn.fetchval(
            """
            SELECT COUNT(*) FROM groups
            WHERE moderation_enabled = false
            """
        )
        print(f"Всего групп в базе: {total}")
        print(f"Количество групп с отключенной модерацией: {disabled}")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(count_groups_with_disabled_moderation())
