import os
from datetime import datetime

import pytest
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from redis.asyncio import Redis

from common.database import Group, User

# Use a separate test database
TEST_REDIS_DB = 15


def validate_redis_env_vars():
    """Validate required Redis environment variables"""
    required_vars = ["REDIS_HOST", "REDIS_PASSWORD"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]

    if missing_vars:
        raise ValueError(
            f"Missing required Redis environment variables: {', '.join(missing_vars)}"
        )


@pytest.fixture(scope="session")
async def test_redis():
    """Create a test Redis connection that can be cleaned between tests"""
    # Validate environment variables before attempting connection
    validate_redis_env_vars()

    host = os.getenv("REDIS_HOST")
    password = os.getenv("REDIS_PASSWORD")

    redis_client = Redis(
        host=host,
        password=password,
        db=TEST_REDIS_DB,
        decode_responses=True,
        socket_timeout=10,  # Increased timeout
        socket_connect_timeout=10,  # Increased connection timeout
    )

    await redis_client.config_set("maxmemory", "10mb")  # Increased memory limit
    await redis_client.config_set(
        "maxmemory-policy", "allkeys-lru"
    )  # Least Recently Used eviction policy

    print("Redis connected")

    try:
        yield redis_client

    finally:
        await redis_client.aclose()

    print("Redis disconnected")


@pytest.fixture(scope="function")
def patched_redis_conn(monkeypatch, test_redis):
    """Fixture to patch the global Redis connection for tests"""

    monkeypatch.setattr("common.database.user_operations.redis", test_redis)
    monkeypatch.setattr("common.database.group_operations.redis", test_redis)
    monkeypatch.setattr("common.database.redis", test_redis)
    monkeypatch.setattr("common.database.redis_connection.redis", test_redis)

    print("Redis patched")

    yield


@pytest.fixture(scope="function")
async def clean_redis(patched_redis_conn, test_redis):
    """Ensure a clean Redis state before each test"""
    await test_redis.flushdb()
    print("DB flushed")
    yield test_redis


@pytest.fixture(scope="session")
def event_loop():
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def sample_group():
    return Group(
        group_id=987654,
        group_name="Test Group",
        member_ids=[123456, 789012],
        admin_ids=[123456, 789012],
        is_moderation_enabled=False,
    )


@pytest.fixture
def sample_user():
    return User(
        user_id=123456,
        username="testuser",
        credits=50,
        is_active=True,
        delete_spam=True,
        created_at=datetime.now(),
        last_updated=datetime.now(),
    )
