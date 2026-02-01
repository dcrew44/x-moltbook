import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages database connections with support for read replicas."""

    def __init__(self):
        self._primary_engine: Optional[AsyncEngine] = None
        self._replica_engines: list[AsyncEngine] = []
        self._primary_session_factory: Optional[async_sessionmaker[AsyncSession]] = None
        self._replica_session_factories: list[async_sessionmaker[AsyncSession]] = []
        self._replica_index = 0

    def _create_primary_engine(self) -> AsyncEngine:
        """Create the primary database engine."""
        settings = get_settings()
        return create_async_engine(
            settings.database_url,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            echo=settings.debug,
        )

    def _create_replica_engines(self) -> list[AsyncEngine]:
        """Create replica database engines."""
        settings = get_settings()
        engines = []
        for url in settings.database_replica_urls:
            engine = create_async_engine(
                url,
                pool_size=settings.database_replica_pool_size,
                max_overflow=settings.database_replica_pool_size,
                echo=settings.debug,
            )
            engines.append(engine)
            logger.info(f"Configured read replica: {url.split('@')[-1] if '@' in url else url}")
        return engines

    def get_primary_engine(self) -> AsyncEngine:
        """Get or create the primary database engine."""
        if self._primary_engine is None:
            self._primary_engine = self._create_primary_engine()
        return self._primary_engine

    def get_replica_engines(self) -> list[AsyncEngine]:
        """Get or create the replica database engines."""
        if not self._replica_engines:
            self._replica_engines = self._create_replica_engines()
        return self._replica_engines

    def get_read_engine(self) -> AsyncEngine:
        """Get an engine for read operations (round-robin replicas, fallback to primary)."""
        replicas = self.get_replica_engines()
        if not replicas:
            return self.get_primary_engine()

        # Round-robin selection
        engine = replicas[self._replica_index % len(replicas)]
        self._replica_index = (self._replica_index + 1) % len(replicas)
        return engine

    def get_primary_session_factory(self) -> async_sessionmaker[AsyncSession]:
        """Get or create the primary session factory."""
        if self._primary_session_factory is None:
            self._primary_session_factory = async_sessionmaker(
                self.get_primary_engine(),
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
            )
        return self._primary_session_factory

    def get_read_session_factory(self) -> async_sessionmaker[AsyncSession]:
        """Get a session factory for read operations."""
        replicas = self.get_replica_engines()
        if not replicas:
            return self.get_primary_session_factory()

        # Create session factories for replicas on demand
        if not self._replica_session_factories:
            self._replica_session_factories = [
                async_sessionmaker(
                    engine,
                    class_=AsyncSession,
                    expire_on_commit=False,
                    autoflush=False,
                )
                for engine in replicas
            ]

        # Round-robin selection
        idx = (self._replica_index - 1) % len(self._replica_session_factories)
        return self._replica_session_factories[idx]


# Global database manager instance
_db_manager: Optional[DatabaseManager] = None


def get_db_manager() -> DatabaseManager:
    """Get the database manager singleton."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


# Backward-compatible functions
def get_engine() -> AsyncEngine:
    """Get or create the database engine (primary)."""
    return get_db_manager().get_primary_engine()


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or create the session factory (primary)."""
    return get_db_manager().get_primary_session_factory()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for FastAPI routes (uses primary for writes)."""
    async with get_db_manager().get_primary_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_read_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for read-only FastAPI routes (uses replicas when available)."""
    async with get_db_manager().get_read_session_factory()() as session:
        try:
            yield session
            # No commit needed for read-only operations
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for use outside of FastAPI routes (uses primary)."""
    async with get_db_manager().get_primary_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_read_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for read-only operations outside of FastAPI routes."""
    async with get_db_manager().get_read_session_factory()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
