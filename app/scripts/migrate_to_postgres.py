import asyncio
import json
import os
from datetime import datetime

import asyncpg
from dotenv import load_dotenv
from redis import Redis

# Load environment variables
load_dotenv()

from app.common.database.database_schema import (
    create_tables_and_indexes,
    drop_and_create_database,
)

# PostgreSQL connection parameters
PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", "5432"))
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASS = os.getenv("PG_PASSWORD", "")
PG_DB = os.getenv("PG_DB", "ai_spam_bot")

# Redis connection parameters
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
REDIS_DB = int(os.getenv("REDIS_DB", "0"))


async def main():
    # Connect to default database for recreation
    system_conn = await asyncpg.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASS, database="postgres"
    )

    try:
        # Drop and recreate database
        print("Dropping and recreating database...")
        await drop_and_create_database(system_conn, PG_DB)
    finally:
        await system_conn.close()

    # Connect to PostgreSQL
    pg_conn = await asyncpg.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASS, database=PG_DB
    )

    # Connect to Redis
    redis_conn = Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        db=REDIS_DB,
        decode_responses=True,
    )

    try:
        print("Creating tables...")
        await create_tables_and_indexes(pg_conn)

        print("Starting data migration...")
        await migrate_data(pg_conn, redis_conn)

        print("Migration completed successfully!")

    finally:
        await pg_conn.close()
        redis_conn.close()


async def migrate_data(pg_conn, redis_conn):
    """Migrate data from Redis to PostgreSQL"""
    await migrate_users(pg_conn, redis_conn)
    await migrate_groups(pg_conn, redis_conn)
    await migrate_spam_examples(pg_conn, redis_conn)
    await migrate_message_history(pg_conn, redis_conn)


async def migrate_users(pg_conn, redis_conn):
    """Migrate users from Redis to PostgreSQL"""
    print("Migrating users...")
    user_keys = redis_conn.keys("user:*")

    for key in user_keys:
        try:
            user_id = int(key.split(":")[1])
            user_data = redis_conn.hgetall(key)

            if not user_data:
                continue

            await pg_conn.execute(
                """
                INSERT INTO administrators (
                    admin_id, username, credits, delete_spam, created_at, last_active
                ) VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (admin_id) DO UPDATE SET
                    username = $2,
                    credits = $3,
                    delete_spam = $4,
                    last_active = $6
            """,
                user_id,
                user_data.get("username", ""),
                int(user_data.get("credits", 0)),
                bool(int(user_data.get("delete_spam", 1))),
                datetime.fromisoformat(
                    user_data.get("created_at", datetime.now().isoformat())
                ),
                datetime.fromisoformat(
                    user_data.get("last_updated", datetime.now().isoformat())
                ),
            )

            print(f"Migrated user {user_id}")
        except Exception as e:
            print(f"Error migrating user {key}: {e}")


async def migrate_groups(pg_conn, redis_conn):
    """Migrate groups from Redis to PostgreSQL"""
    print("Migrating groups...")
    group_keys = redis_conn.keys("group:*")

    for key in group_keys:
        if ":admins" in key or ":members" in key:
            continue

        try:
            group_id = int(key.split(":")[1])
            group_data = redis_conn.hgetall(key)

            if not group_data:
                continue

            # Migrate group data
            await pg_conn.execute(
                """
                INSERT INTO groups (group_id, moderation_enabled, created_at, last_active)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (group_id) DO UPDATE SET
                    moderation_enabled = $2,
                    last_active = $4
            """,
                group_id,
                bool(int(group_data.get("is_moderation_enabled", 0))),
                datetime.fromisoformat(
                    group_data.get("created_at", datetime.now().isoformat())
                ),
                datetime.fromisoformat(
                    group_data.get("last_updated", datetime.now().isoformat())
                ),
            )

            # Migrate admins
            admin_ids = redis_conn.smembers(f"group:{group_id}:admins")
            if admin_ids:
                await pg_conn.executemany(
                    """
                    INSERT INTO group_administrators (group_id, admin_id)
                    VALUES ($1, $2)
                    ON CONFLICT DO NOTHING
                """,
                    [(group_id, int(admin_id)) for admin_id in admin_ids],
                )

            # Migrate members
            member_ids = redis_conn.smembers(f"group:{group_id}:members")
            if member_ids:
                await pg_conn.executemany(
                    """
                    INSERT INTO approved_members (group_id, member_id)
                    VALUES ($1, $2)
                    ON CONFLICT DO NOTHING
                """,
                    [(group_id, int(member_id)) for member_id in member_ids],
                )

            print(f"Migrated group {group_id}")
        except Exception as e:
            print(f"Error migrating group {key}: {e}")


async def migrate_spam_examples(pg_conn, redis_conn):
    """Migrate spam examples from Redis to PostgreSQL"""
    print("Migrating spam examples...")

    # Migrate common examples
    examples = redis_conn.lrange("spam_examples", 0, -1)
    for example in examples:
        try:
            data = json.loads(example)
            await pg_conn.execute(
                """
                INSERT INTO spam_examples (text, name, bio, score)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT DO NOTHING
            """,
                data["text"],
                data.get("name"),
                data.get("bio"),
                data["score"],
            )
        except Exception as e:
            print(f"Error migrating spam example: {e}")

    # Migrate user-specific examples
    user_example_keys = redis_conn.keys("user_spam_examples:*")
    for key in user_example_keys:
        try:
            admin_id = int(key.split(":")[1])
            examples = redis_conn.lrange(key, 0, -1)

            for example in examples:
                data = json.loads(example)
                await pg_conn.execute(
                    """
                    INSERT INTO spam_examples (admin_id, text, name, bio, score)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT DO NOTHING
                """,
                    admin_id,
                    data["text"],
                    data.get("name"),
                    data.get("bio"),
                    data["score"],
                )
        except Exception as e:
            print(f"Error migrating user spam examples for {key}: {e}")


async def migrate_message_history(pg_conn, redis_conn):
    """Migrate message history from Redis to PostgreSQL"""
    print("Migrating message history...")
    history_keys = redis_conn.keys("message_history:*")

    for key in history_keys:
        try:
            admin_id = int(key.split(":")[1])
            messages = redis_conn.lrange(key, 0, -1)

            for msg in messages:
                data = json.loads(msg)
                await pg_conn.execute(
                    """
                    INSERT INTO message_history (admin_id, role, content, created_at)
                    VALUES ($1, $2, $3, $4)
                """,
                    admin_id,
                    data["role"],
                    data["content"],
                    datetime.fromisoformat(data["timestamp"]),
                )
        except Exception as e:
            print(f"Error migrating message history for {key}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
