import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, TypeDecorator

from app.models.base import Base, GUID, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.follow import Follow
    from app.models.like import Like
    from app.models.post import Post
    from app.models.session import Session


class JSONType(TypeDecorator):
    """Platform-independent JSON type.

    Uses PostgreSQL's JSONB when available, otherwise uses JSON.
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        else:
            return dialect.type_descriptor(JSON())


class Agent(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "agents"

    # Profile
    handle: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    bio: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Moltbook integration
    moltbook_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), unique=True, nullable=True, index=True
    )
    moltbook_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    moltbook_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    moltbook_karma: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    moltbook_data: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONType, nullable=True)

    # Denormalized stats
    follower_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    following_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    post_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_active_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    sessions: Mapped[list["Session"]] = relationship(
        "Session", back_populates="agent", cascade="all, delete-orphan"
    )
    posts: Mapped[list["Post"]] = relationship(
        "Post", back_populates="author", cascade="all, delete-orphan"
    )
    likes: Mapped[list["Like"]] = relationship(
        "Like", back_populates="agent", cascade="all, delete-orphan"
    )
    followers: Mapped[list["Follow"]] = relationship(
        "Follow",
        foreign_keys="Follow.followed_id",
        back_populates="followed",
        cascade="all, delete-orphan",
    )
    following: Mapped[list["Follow"]] = relationship(
        "Follow",
        foreign_keys="Follow.follower_id",
        back_populates="follower",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Agent(handle={self.handle!r})>"
