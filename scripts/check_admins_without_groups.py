import asyncio
import os
from dotenv import load_dotenv
import asyncpg

load_dotenv()


async def check_admins_without_groups():
    # Получаем параметры подключения из переменных окружения
    conn = await asyncpg.connect(
        host=os.getenv("PG_HOST", "localhost"),
        port=int(os.getenv("PG_PORT", "5432")),
        user=os.getenv("PG_USER", "postgres"),
        password=os.getenv("PG_PASSWORD", ""),
        database=os.getenv("PG_DB", "ai_spam_bot"),
    )

    try:
        # Получаем информацию об админах без групп
        rows = await conn.fetch("""
            SELECT a.admin_id, a.credits
            FROM administrators a
            LEFT JOIN group_administrators ga ON a.admin_id = ga.admin_id
            WHERE ga.group_id IS NULL
            ORDER BY a.credits DESC
        """)

        print(f"\nАдминистраторы без групп ({len(rows)}):")
        print("-" * 50)
        for row in rows:
            print(f"Admin ID: {row['admin_id']}")
            print(f"Звезды: {row['credits']}")
            print("-" * 50)

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(check_admins_without_groups())
