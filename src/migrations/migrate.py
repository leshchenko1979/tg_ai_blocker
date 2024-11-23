import asyncio
from typing import Any, List

# Load environment variables
from dotenv import load_dotenv

load_dotenv()
from ..app.database import create_procedures, get_pool


async def migrate(conn: Any) -> List[str]:
    """
    Создает таблицы для реферальной системы
    Возвращает список выполненных операций
    """
    operations = []
    print("Starting database migration...")

    # Start transaction
    async with conn.transaction():
        print("Dropping existing stored procedures...")
        # Drop existing stored procedures first
        await conn.execute(
            """
            DO $$
            DECLARE
                proc record;
            BEGIN
                FOR proc IN (SELECT proname, oidvectortypes(proargtypes) as args
                            FROM pg_proc
                            WHERE pronamespace = 'public'::regnamespace)
                LOOP
                    EXECUTE 'DROP PROCEDURE IF EXISTS ' || proc.proname || '(' || proc.args || ') CASCADE';
                END LOOP;
            END $$;
            """
        )
        operations.append("Dropped existing stored procedures")
        print("✓ Dropped existing stored procedures")

        print("Creating referral_links table...")
        # Создаем таблицу для реферальных связей
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS referral_links (
                id SERIAL PRIMARY KEY,
                referral_id BIGINT REFERENCES administrators(admin_id) ON DELETE CASCADE,
                referrer_id BIGINT REFERENCES administrators(admin_id) ON DELETE CASCADE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE(referral_id)
            );
        """
        )
        operations.append("Created table referral_links")
        print("✓ Created referral_links table")

        print("Creating indexes...")
        # Создаем индексы
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_referral_links_referrer
            ON referral_links(referrer_id);

            CREATE INDEX IF NOT EXISTS idx_referral_links_created
            ON referral_links(created_at);
        """
        )
        operations.append("Created referral indexes")
        print("✓ Created indexes")

        print("Creating procedures...")
        await create_procedures(conn)
        operations.append("Created procedures")
        print("✓ Created procedures")

    print(f"Migration completed successfully. {len(operations)} operations performed.")
    return operations


async def main():
    print("Getting database pool...")
    pool = await get_pool()
    print("Migrating database...")
    async with pool.acquire() as conn:
        print("Acquired connection from pool")
        await migrate(conn)


if __name__ == "__main__":
    asyncio.run(main())
