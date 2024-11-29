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


async def main():
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
