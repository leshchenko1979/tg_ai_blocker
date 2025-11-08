import asyncio
import os
from dotenv import load_dotenv
import asyncpg

load_dotenv()


async def check_admins_credits():
    # Получаем параметры подключения из переменных окружения
    conn = await asyncpg.connect(
        host=os.getenv("PG_HOST", "localhost"),
        port=int(os.getenv("PG_PORT", "5432")),
        user=os.getenv("PG_USER", "postgres"),
        password=os.getenv("PG_PASSWORD", ""),
        database=os.getenv("PG_DB", "ai_spam_bot"),
    )

    try:
        # Получаем информацию о балансе админов
        rows = await conn.fetch("""
            SELECT a.admin_id, a.credits, COUNT(DISTINCT g.group_id) as group_count
            FROM administrators a
            LEFT JOIN group_administrators ga ON a.admin_id = ga.admin_id
            LEFT JOIN groups g ON ga.group_id = g.group_id
            GROUP BY a.admin_id, a.credits
            ORDER BY a.credits DESC
        """)

        print("\nБаланс администраторов:")
        print("-" * 50)
        for row in rows:
            print(f"Admin ID: {row['admin_id']}")
            print(f"Звезды: {row['credits']}")
            print(f"Количество групп: {row['group_count']}")
            print("-" * 50)

        # Получаем статистику транзакций
        transactions = await conn.fetch("""
            SELECT type, COUNT(*) as count, SUM(amount) as total_amount
            FROM transactions
            GROUP BY type
            ORDER BY type
        """)

        print("\nСтатистика транзакций:")
        print("-" * 50)
        for t in transactions:
            print(f"Тип: {t['type']}")
            print(f"Количество: {t['count']}")
            print(f"Общая сумма: {t['total_amount']}")
            print("-" * 50)

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(check_admins_credits())
