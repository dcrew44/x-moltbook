import asyncio
import os
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Set test database URL before importing app modules
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["MOLTBOOK_APP_KEY"] = "test-key"

from app.core.database import get_db
from app.main import app
from app.models import Base


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


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


@pytest_asyncio.fixture(scope="function")
async def client(db_session):
    """Create test client with database override."""
    from httpx import ASGITransport, AsyncClient

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


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
