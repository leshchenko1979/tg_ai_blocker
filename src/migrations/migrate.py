import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import asyncio
from typing import Any, List

import asyncpg

# Load environment variables
from dotenv import load_dotenv

load_dotenv()
from src.app.database import get_pool
from src.app.database.database_schema import create_schema


async def create_database():
    # Connect to default database to create new one
    system_conn = await asyncpg.connect(
        user=os.getenv("PG_USER"),
        password=os.getenv("PG_PASSWORD"),
        host=os.getenv("PG_HOST"),
        port=int(os.getenv("PG_PORT", "5432")),
        database="postgres",  # Connect to default database
    )

    try:
        # Check if database exists
        exists = await system_conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", os.getenv("PG_DB")
        )

        if not exists:
            print(f"Creating database {os.getenv('PG_DB')}...")
            # Create new database
            await system_conn.execute(f"CREATE DATABASE {os.getenv('PG_DB')}")
            print("Database created successfully!")
        else:
            print(f"Database {os.getenv('PG_DB')} already exists.")

    finally:
        await system_conn.close()


async def migrate(conn: Any) -> List[str]:
    """
    Perform database migration operations.

    Args:
        conn (Any): The database connection object.

    Returns:
        List[str]: A list of operations performed during the migration process.
    """
    operations = []
    print("Starting database migration...")

    # Start transaction
    async with conn.transaction():
        print("Creating schema...")
        await create_schema(conn)
        operations.append("Created schema")
        print("✓ Created schema")

    print(f"Migration completed successfully. {len(operations)} operations performed.")
    return operations


async def add_context_columns_migration(conn: Any) -> List[str]:
    """
    Add context columns to existing spam_examples table.
    This migration adds stories_context, reply_context, and account_age_context columns.
    """
    operations = []
    print("Starting context columns migration...")

    async with conn.transaction():
        # Add stories_context column
        await conn.execute(
            "ALTER TABLE spam_examples ADD COLUMN IF NOT EXISTS stories_context TEXT"
        )
        operations.append("Added stories_context column")
        print("✓ Added stories_context column")

        # Add reply_context column
        await conn.execute(
            "ALTER TABLE spam_examples ADD COLUMN IF NOT EXISTS reply_context TEXT"
        )
        operations.append("Added reply_context column")
        print("✓ Added reply_context column")

        # Add account_age_context column
        await conn.execute(
            "ALTER TABLE spam_examples ADD COLUMN IF NOT EXISTS account_age_context TEXT"
        )
        operations.append("Added account_age_context column")
        print("✓ Added account_age_context column")

    print(
        f"Context columns migration completed successfully. {len(operations)} operations performed."
    )
    return operations


async def add_is_active_column_migration(conn: Any) -> List[str]:
    """
    Ensure administrators table has the is_active column.
    Needed for broadcast scripts and cleanup logic.
    """
    operations = []
    print("Starting is_active column migration...")

    async with conn.transaction():
        await conn.execute(
            """
            ALTER TABLE administrators
            ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE
            """
        )
        operations.append("Ensured is_active column exists")
        print("✓ Ensured is_active column exists")

        await conn.execute(
            """
            UPDATE administrators
            SET is_active = TRUE
            WHERE is_active IS NULL
            """
        )
        operations.append("Backfilled is_active for existing rows")
        print("✓ Backfilled is_active for existing rows")

        await conn.execute(
            """
            ALTER TABLE administrators
            ALTER COLUMN is_active SET DEFAULT TRUE
            """
        )
        operations.append("Enforced default TRUE for is_active")
        print("✓ Enforced default TRUE for is_active")

    print(
        f"is_active column migration completed successfully. {len(operations)} operations performed."
    )
    return operations


async def run_context_columns_migration():
    """Run the context columns migration manually."""
    print("Creating database if it doesn't exist...")
    await create_database()
    print("Getting database pool...")
    pool = await get_pool()
    print("Running context columns migration...")
    async with pool.acquire() as conn:
        print("Acquired connection from pool")
        await add_context_columns_migration(conn)


async def run_is_active_column_migration():
    """Run the is_active column migration manually."""
    print("Creating database if it doesn't exist...")
    await create_database()
    print("Getting database pool...")
    pool = await get_pool()
    print("Running is_active column migration...")
    async with pool.acquire() as conn:
        print("Acquired connection from pool")
        await add_is_active_column_migration(conn)


async def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == "--add-context-columns":
            await run_context_columns_migration()
        elif sys.argv[1] == "--add-is-active-column":
            await run_is_active_column_migration()
        else:
            raise ValueError(f"Unknown migration flag {sys.argv[1]!r}")
    else:
        # Run full migration
        print("Creating database if it doesn't exist...")
        await create_database()
        print("Getting database pool...")
        pool = await get_pool()
        print("Migrating database...")
        async with pool.acquire() as conn:
            print("Acquired connection from pool")
            await migrate(conn)


if __name__ == "__main__":
    asyncio.run(main())
