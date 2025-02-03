import logging
import os
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    """Get or create PostgreSQL connection pool"""
    global _pool
    if _pool is None:
        try:
            _pool = await asyncpg.create_pool(
                host=os.getenv("PG_HOST", "localhost"),
                port=int(os.getenv("PG_PORT", "5432")),
                user=os.getenv("PG_USER", "postgres"),
                password=os.getenv("PG_PASSWORD", ""),
                database=os.getenv("PG_DB", "ai_spam_bot"),
                min_size=1,
                max_size=10,
            )
        except Exception as e:
            logger.error(f"Failed to create database pool: {e}")
            raise
    return _pool


def get_pool_sync() -> asyncpg.Pool:
    """Get the current database pool (synchronous version for testing)"""
    return _pool


async def close_pool():
    """Close the PostgreSQL connection pool"""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
