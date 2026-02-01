import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB

from app.models.base import Base, GUID, TimestampMixin, UUIDMixin


class JSONType(TypeDecorator):
    """Platform-independent JSON type."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        else:
            return dialect.type_descriptor(JSON())


class IdempotencyKey(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_path: Mapped[str] = mapped_column(String(500), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<IdempotencyKey(key={self.key!r})>"
