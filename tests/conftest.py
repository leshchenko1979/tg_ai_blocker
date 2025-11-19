import pytest
from pytest_asyncio import is_async_test


def pytest_collection_modifyitems(items: list[pytest.Item]):
    for test in items:
        if is_async_test(test):
            # Mark async tests with session scope
            test.add_marker(pytest.mark.asyncio(loop_scope="session"), append=False)


# Load environment variables
from dotenv import load_dotenv

load_dotenv()

# Other imports
import os
from datetime import datetime

# Mute Yandex logging
from app.logging_setup import mute_logging_for_tests

mute_logging_for_tests()

# Mute mp for tests
from app.common.mp import mute_mp_for_tests

mute_mp_for_tests()

import asyncpg
import aiosqlite
import re

from app.database import (
    Administrator,
    create_schema,
    drop_and_create_database,
    postgres_connection,
)

# Test database settings - use SQLite for fast local testing
USE_SQLITE = os.getenv("USE_SQLITE_TESTS", "true").lower() == "true"

if USE_SQLITE:
    # SQLite settings for fast local testing
    SQLITE_DB_PATH = ":memory:"  # In-memory database
else:
    # PostgreSQL test database settings (legacy)
    TEST_PG_DB = "ai_spam_bot_test"
    PG_HOST = os.getenv("PG_HOST", "localhost")
    PG_PORT = int(os.getenv("PG_PORT", "5432"))
    PG_USER = os.getenv("PG_USER", "postgres")
    PG_PASS = os.getenv("PG_PASSWORD", "")


class _DummyTransactionContext:
    """Dummy transaction context manager for SQLite compatibility"""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass  # SQLite handles commits automatically in our execute method


class SQLiteConnectionAdapter:
    """Adapter to make aiosqlite connection compatible with asyncpg interface"""

    # Singleton dummy transaction context to avoid creating multiple instances
    _dummy_transaction = _DummyTransactionContext()

    def __init__(self, sqlite_conn):
        self._conn = sqlite_conn

    async def __aenter__(self):
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        pass  # Connection is managed by the pool

    def _transform_query_and_params(self, query, args):
        """Transform PostgreSQL query syntax to SQLite-compatible syntax and adjust parameters"""
        original_query = query
        original_args = args

        # Convert PostgreSQL NOW() to SQLite CURRENT_TIMESTAMP first
        query = query.replace("NOW()", "CURRENT_TIMESTAMP")

        # Handle INTERVAL syntax (convert PostgreSQL INTERVAL to SQLite datetime modifiers)
        # Generic pattern for any number of days
        query = re.sub(
            r"CURRENT_TIMESTAMP\s*-\s*INTERVAL\s*'(\d+)\s+days?'",
            r"datetime('now', '-\1 days')",
            query,
            flags=re.IGNORECASE,
        )

        # Convert PostgreSQL SERIAL to SQLite AUTOINCREMENT
        query = query.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")

        # Handle PostgreSQL ANY() function for array operations
        query, args = self._convert_any_function_to_sqlite(query, args)

        # Handle complex NULL comparison patterns (expand parameters)
        query, args = self._expand_null_comparison_patterns(query, args)

        # Handle ON CONFLICT syntax (PostgreSQL UPSERT)
        if "ON CONFLICT" in query.upper():
            query = self._convert_on_conflict_to_sqlite(query)

        # Convert PostgreSQL $1, $2, etc. to SQLite ? placeholders
        query = re.sub(r"\$\d+", "?", query)

        return query, args

    def _convert_any_function_to_sqlite(self, query, args):
        """Convert PostgreSQL ANY() function calls to SQLite-compatible syntax"""
        # Handle ANY(array) operations - convert to IN clauses
        any_pattern = r"(\w+)\s*=\s*ANY\s*\(\$\d+\)"
        match = re.search(any_pattern, query, re.IGNORECASE)
        if match:
            column_name = match.group(1)
            # Replace ANY($N) with IN (?, ?, ...) and expand the array parameter
            param_index = (
                int(re.search(r"ANY\s*\(\$(\d+)\)", query, re.IGNORECASE).group(1)) - 1
            )
            if param_index < len(args) and isinstance(args[param_index], list):
                array_values = args[param_index]
                placeholders = ", ".join(["?"] * len(array_values))
                query = re.sub(
                    any_pattern,
                    f"{column_name} IN ({placeholders})",
                    query,
                    flags=re.IGNORECASE,
                )

                # Expand the array parameter into separate parameters
                new_args = list(args)
                new_args[param_index : param_index + 1] = array_values
                args = tuple(new_args)
        return query, args

    def _expand_null_comparison_patterns(self, query, args):
        """Expand PostgreSQL NULL comparison patterns that reuse parameters"""
        # Handle patterns like: (name = $2 OR (name IS NULL AND $2 IS NULL))
        # This needs to be expanded to use separate parameters for each occurrence

        # Find all parameter usages in NULL comparison patterns
        null_pattern = r"\(\s*(\w+)\s*=\s*\$(\d+)\s+OR\s*\(\s*\1\s+IS\s+NULL\s+AND\s*\$(\d+)\s+IS\s+NULL\s*\)\s*\)"
        matches = list(re.finditer(null_pattern, query, re.IGNORECASE))

        if not matches:
            return query, args

        # Process matches in reverse order to maintain parameter indices
        args_list = list(args)
        offset = 0

        for match in reversed(matches):
            col_name = match.group(1)
            param1 = int(match.group(2)) - 1  # Convert to 0-based
            param2 = int(match.group(3)) - 1  # Convert to 0-based

            # If both parameters reference the same position, we need to duplicate the value
            if param1 == param2 and param1 < len(args_list):
                value = args_list[param1]
                # Insert duplicate value after the original
                args_list.insert(param1 + 1, value)
                offset += 1

        return query, tuple(args_list)

    async def execute(self, query, *args):
        """Execute a query (INSERT, UPDATE, DELETE)"""
        query, args = self._transform_query_and_params(query, args)
        cursor = await self._conn.execute(query, args)
        await self._conn.commit()
        # Return affected row count in PostgreSQL format (e.g., "DELETE 5")
        if cursor.rowcount is not None:
            return f"{query.split()[0].upper()} {cursor.rowcount}"
        return None

    def _convert_on_conflict_to_sqlite(self, query):
        """Convert PostgreSQL ON CONFLICT syntax to SQLite INSERT OR REPLACE"""
        # Replace INSERT with INSERT OR REPLACE
        query = re.sub(r"\bINSERT\b", "INSERT OR REPLACE", query, flags=re.IGNORECASE)

        # Remove the entire ON CONFLICT clause
        # Match from ON CONFLICT to the end of the statement or a semicolon
        on_conflict_pattern = r"\s+ON\s+CONFLICT.*?($|;)"
        query = re.sub(
            on_conflict_pattern, r"\1", query, flags=re.IGNORECASE | re.DOTALL
        )

        return query

    async def executemany(self, query, args_list):
        """Execute many queries"""
        for args in args_list:
            # Transform query and params for each execution
            transformed_query, transformed_args = self._transform_query_and_params(
                query, args
            )
            await self._conn.execute(transformed_query, transformed_args)
            await self._conn.commit()

    async def fetchrow(self, query, *args):
        """Fetch a single row"""
        query, args = self._transform_query_and_params(query, args)
        cursor = await self._conn.execute(query, args)
        row = await cursor.fetchone()
        await cursor.close()
        return row

    async def fetchval(self, query, *args):
        """Fetch a single value"""
        row = await self.fetchrow(query, *args)
        return row[0] if row else None

    async def fetch(self, query, *args):
        """Fetch all rows"""
        query, args = self._transform_query_and_params(query, args)
        cursor = await self._conn.execute(query, args)
        rows = await cursor.fetchall()
        await cursor.close()
        return rows

    def transaction(self):
        """Return a transaction context manager (for PostgreSQL compatibility)"""
        # For SQLite, we don't need explicit transactions in the same way
        # since autocommit is handled in execute()
        return self._dummy_transaction

    async def close(self):
        """Close the connection"""
        await self._conn.close()


class SQLitePoolAdapter:
    """Adapter to make aiosqlite 'pool' compatible with asyncpg interface"""

    def __init__(self, sqlite_conn):
        self._conn = SQLiteConnectionAdapter(sqlite_conn)

    def acquire(self):
        """Return the connection (synchronous for asyncpg compatibility)"""
        return self._conn

    async def release(self, conn):
        """No-op for single connection"""
        pass

    async def close(self):
        """Close the underlying connection"""
        await self._conn.close()


async def create_sqlite_schema(conn):
    """Create SQLite-compatible schema"""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS administrators (
            admin_id INTEGER PRIMARY KEY,
            username TEXT,
            credits INTEGER DEFAULT 0 CHECK (credits >= 0),
            delete_spam BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            group_id INTEGER PRIMARY KEY,
            title TEXT,
            moderation_enabled BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS group_administrators (
            group_id INTEGER,
            admin_id INTEGER,
            PRIMARY KEY (group_id, admin_id),
            FOREIGN KEY (group_id) REFERENCES groups(group_id),
            FOREIGN KEY (admin_id) REFERENCES administrators(admin_id)
        );
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS approved_members (
            group_id INTEGER,
            member_id INTEGER,
            approved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (group_id, member_id),
            FOREIGN KEY (group_id) REFERENCES groups(group_id)
        );
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS message_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (admin_id) REFERENCES administrators(admin_id)
        );
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS spam_examples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            text TEXT NOT NULL,
            name TEXT,
            bio TEXT,
            score INTEGER NOT NULL,
            linked_channel_fragment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (admin_id) REFERENCES administrators(admin_id)
        );
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            amount INTEGER NOT NULL,
            type TEXT,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (admin_id) REFERENCES administrators(admin_id)
        );
    """)


async def truncate_sqlite_tables(conn):
    """Truncate all tables in SQLite"""
    # Disable foreign keys temporarily
    await conn.execute("PRAGMA foreign_keys = OFF")

    # Delete in reverse dependency order (child tables first)
    tables = [
        "transactions",
        "spam_examples",
        "message_history",
        "approved_members",
        "group_administrators",
        "groups",
        "administrators",
    ]

    for table in tables:
        await conn.execute(f"DELETE FROM {table}")

    # Re-enable foreign keys
    await conn.execute("PRAGMA foreign_keys = ON")

    await conn._conn.commit()


def validate_postgres_env_vars():
    """Validate required PostgreSQL environment variables"""
    if not USE_SQLITE:
        required_vars = ["PG_HOST", "PG_USER", "PG_PASSWORD"]
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        if missing_vars:
            raise ValueError(
                f"Missing required PostgreSQL environment variables: {', '.join(missing_vars)}"
            )


async def create_test_database():
    """Create test database if it doesn't exist"""
    if USE_SQLITE:
        print("Using SQLite for testing - no database creation needed")
        return

    system_conn = await asyncpg.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASS, database="postgres"
    )

    try:
        # Check if test database exists
        exists = await system_conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", TEST_PG_DB
        )

        if not exists:
            print(f"Creating test database: {TEST_PG_DB}")
            await drop_and_create_database(system_conn, TEST_PG_DB)
        else:
            print(f"Test database {TEST_PG_DB} already exists, skipping creation")
    finally:
        await system_conn.close()

    # Only create schema if database was newly created or schema doesn't exist
    test_db_conn = await asyncpg.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASS, database=TEST_PG_DB
    )

    try:
        # Check if schema exists by checking for a known table
        schema_exists = await test_db_conn.fetchval(
            "SELECT 1 FROM information_schema.tables WHERE table_name = 'administrators'"
        )

        if not schema_exists:
            print("Creating database schema...")
            await create_schema(test_db_conn)
        else:
            print("Database schema already exists, skipping creation")
    finally:
        await test_db_conn.close()


@pytest.fixture(scope="session")
async def test_pool():
    """Create a test database pool that can be cleaned between tests"""
    if USE_SQLITE:
        # Register datetime adapters to avoid deprecation warnings (Python 3.12+)
        import sqlite3
        sqlite3.register_adapter(datetime, lambda dt: dt.isoformat())
        sqlite3.register_converter("TIMESTAMP", lambda ts: datetime.fromisoformat(ts.decode()))

        # Create SQLite in-memory database
        sqlite_conn = await aiosqlite.connect(SQLITE_DB_PATH)
        sqlite_conn.row_factory = aiosqlite.Row  # Enable dict-like access to rows

        # Enable foreign keys
        await sqlite_conn.execute("PRAGMA foreign_keys = ON")

        # Create schema
        sqlite_adapter = SQLiteConnectionAdapter(sqlite_conn)
        await create_sqlite_schema(sqlite_adapter)

        # Create pool adapter
        pool = SQLitePoolAdapter(sqlite_conn)

        print("SQLite in-memory database created")

        try:
            yield pool
        finally:
            await pool.close()
            print("SQLite database closed")
    else:
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
async def patched_get_pool(clean_db):
    """Patch get_pool to return a pool that gives our test connection"""
    from app.database import postgres_connection

    class TestPool:
        def __init__(self, pool_obj):
            self.pool_obj = pool_obj

        async def acquire(self):
            return await self.pool_obj.acquire()

        async def release(self, conn):
            await self.pool_obj.release(conn)

    original_get_pool = postgres_connection.get_pool
    test_pool = TestPool(clean_db)

    async def mock_get_pool():
        return test_pool

    # Patch the get_pool function
    postgres_connection.get_pool = mock_get_pool

    yield

    # Restore original function
    postgres_connection.get_pool = original_get_pool


@pytest.fixture(scope="function")
async def clean_db(patched_db_conn, test_pool):
    """Ensure a clean database state before each test"""
    if USE_SQLITE:
        # For SQLite, truncate all tables since transactions don't work the same way
        conn = test_pool.acquire()

        try:
            await truncate_sqlite_tables(conn)
            print("SQLite tables truncated")
            # Yield the pool object, not a dict, for compatibility with existing tests
            yield test_pool
        finally:
            await test_pool.release(conn)
    else:
        # PostgreSQL: Use transaction rollback
        conn = await test_pool.acquire()

        try:
            # Ensure that database name is TEST_PG_DB
            db_name = await conn.fetchval("SELECT current_database()")
            assert db_name == TEST_PG_DB

            # Start a transaction that will be rolled back after the test
            await conn.execute("BEGIN")

            print("DB transaction started")

            # Yield the pool object for compatibility with existing tests
            yield test_pool

        finally:
            # Rollback the transaction and release the connection
            try:
                await conn.execute("ROLLBACK")
                print("DB transaction rolled back")
            except Exception as e:
                print(f"Error rolling back transaction: {e}")
            finally:
                await test_pool.release(conn)


@pytest.fixture
def sample_user():
    return Administrator(
        admin_id=123456,
        username="testuser",
        credits=50,
        delete_spam=True,
        created_at=datetime.now(),
        last_active=datetime.now(),
    )
