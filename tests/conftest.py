import pytest

# Mark async tests with session scope
from pytest_asyncio import is_async_test

def pytest_collection_modifyitems(items):
    pytest_asyncio_tests = (item for item in items if is_async_test(item))
    session_scope_marker = pytest.mark.asyncio(loop_scope="session")
    for async_test in pytest_asyncio_tests:
        async_test.add_marker(session_scope_marker, append=False)

# Load environment variables
from dotenv import load_dotenv

load_dotenv()

# Other imports
import os
from datetime import datetime

import asyncpg

from common.database import User, postgres_connection
from common.database.database_schema import (
    drop_and_create_database,
    truncate_all_tables,
)

# Mute mp for tests
from common.mp import mute_mp_for_tests

mute_mp_for_tests()

# PostgreSQL test database settings
TEST_PG_DB = "ai_spam_bot_test"
PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", "5432"))
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASS = os.getenv("PG_PASSWORD", "")


def validate_postgres_env_vars():
    """Validate required PostgreSQL environment variables"""
    required_vars = ["PG_HOST", "PG_USER", "PG_PASSWORD"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        raise ValueError(
            f"Missing required PostgreSQL environment variables: {', '.join(missing_vars)}"
        )


async def create_test_database():
    """Create test database if it doesn't exist"""
    system_conn = await asyncpg.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASS, database="postgres"
    )

    try:
        # Check if database exists
        exists = await system_conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", TEST_PG_DB
        )

        if not exists:
            await drop_and_create_database(system_conn, TEST_PG_DB)

    finally:
        await system_conn.close()


@pytest.fixture(scope="session")
async def test_pool():
    """Create a test database pool that can be cleaned between tests"""
    validate_postgres_env_vars()

    # Ensure test database exists
    await create_test_database()

    # Create pool for test database
    pool = await asyncpg.create_pool(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASS,
        database=TEST_PG_DB,
        min_size=1,
        max_size=5,
    )

    print("PostgreSQL pool created")

    try:
        yield pool
    finally:
        await pool.close()
        print("PostgreSQL pool closed")


@pytest.fixture(scope="session")
def patched_db_conn(test_pool):
    """Fixture to patch the global database pool for tests"""
    postgres_connection._pool = test_pool
    print("Database pool patched")
    yield
    postgres_connection._pool = None


@pytest.fixture(scope="function")
async def clean_db(patched_db_conn, test_pool):
    """Ensure a clean database state before each test"""
    async with test_pool.acquire() as conn:
        await truncate_all_tables(conn)

    print("DB cleaned")
    yield test_pool


@pytest.fixture
def sample_user():
    return User(
        admin_id=123456,
        username="testuser",
        credits=50,
        delete_spam=True,
        created_at=datetime.now(),
        last_active=datetime.now(),
    )
