"""
Test configuration and fixtures.

KNOWN ISSUE: SQLite Teardown Errors
===================================
When running tests, you may see errors like:
    ERROR at teardown of test_create_reply
    sqlite3.IntegrityError: CHECK constraint failed: chk_reply

These errors occur during test teardown (not during actual test execution) and are
caused by SQLite's behavior when dropping tables that have CHECK constraints.

The Post model has CHECK constraints (chk_reply, chk_repost, chk_quote) that SQLite
evaluates even during DROP TABLE operations. This is a SQLite quirk that doesn't
affect PostgreSQL in production.

These errors do NOT indicate test failures - all actual test assertions pass.
The tests use in-memory SQLite for speed, while production uses PostgreSQL.

TODO: Fix SQLite teardown errors
--------------------------------
Options to resolve this:
1. Disable CHECK constraints in SQLite before dropping tables:
   cursor.execute("PRAGMA ignore_check_constraints=ON")
2. Drop tables in reverse dependency order
3. Use a separate test database schema without CHECK constraints
4. Switch to testcontainers with PostgreSQL for more accurate testing

See: https://www.sqlite.org/pragma.html#pragma_ignore_check_constraints
"""

import os
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Set test environment variables before importing app modules
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["MOLTBOOK_APP_KEY"] = "test-key"
os.environ["RATE_LIMIT_ENABLED"] = "false"  # Disable rate limiting in tests
os.environ["ELASTICSEARCH_ENABLED"] = "false"  # Disable Elasticsearch in tests

from app.core.database import get_db
from app.main import app
from app.models import Base


@pytest.fixture(autouse=True)
def reset_app_state():
    """Reset global app state before each test."""
    import app.core.redis as redis_module
    import app.core.database as db_module

    # Reset Redis singletons
    redis_module.redis_client = None
    redis_module._redis_manager = None

    # Reset database manager singleton
    db_module._db_manager = None

    yield

    # Cleanup after test
    redis_module.redis_client = None
    redis_module._redis_manager = None
    db_module._db_manager = None
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    """Create test database engine."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )

    # Enable foreign keys for SQLite
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # TODO: Fix SQLite CHECK constraint errors during teardown
    # SQLite evaluates CHECK constraints even during DROP TABLE, causing errors like:
    #   sqlite3.IntegrityError: CHECK constraint failed: chk_reply
    # This doesn't affect test results, only teardown. Possible fixes:
    # - Add PRAGMA ignore_check_constraints=ON before drop_all
    # - Use PostgreSQL testcontainers for more accurate testing
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create test database session."""
    async_session_factory = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session_factory() as session:
        yield session


@pytest.fixture
def mock_redis():
    """Create mock Redis client."""
    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(return_value=None)
    redis_mock.set = AsyncMock(return_value=True)
    redis_mock.delete = AsyncMock(return_value=1)
    redis_mock.exists = AsyncMock(return_value=0)
    redis_mock.zadd = AsyncMock(return_value=1)
    redis_mock.zrange = AsyncMock(return_value=[])
    redis_mock.zrevrange = AsyncMock(return_value=[])
    redis_mock.zrem = AsyncMock(return_value=0)
    redis_mock.pipeline = MagicMock(return_value=redis_mock)
    redis_mock.execute = AsyncMock(return_value=[])
    redis_mock.expire = AsyncMock(return_value=True)
    redis_mock.incr = AsyncMock(return_value=1)
    redis_mock.zremrangebyscore = AsyncMock(return_value=0)
    redis_mock.zcard = AsyncMock(return_value=1)
    redis_mock.zremrangebyrank = AsyncMock(return_value=0)
    # Session caching methods
    redis_mock.sadd = AsyncMock(return_value=1)
    redis_mock.srem = AsyncMock(return_value=1)
    redis_mock.smembers = AsyncMock(return_value=set())
    return redis_mock
