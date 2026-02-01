import enum
import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, GUID, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.like import Like


class PostType(str, enum.Enum):
    ORIGINAL = "original"
    REPLY = "reply"
    REPOST = "repost"
    QUOTE = "quote"


class Post(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "posts"

    author_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    post_type: Mapped[PostType] = mapped_column(
        Enum(PostType, name="post_type"), nullable=False, default=PostType.ORIGINAL
    )

    # Self-referential FKs for thread/repost relationships
    reply_to_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("posts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    repost_of_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("posts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    quote_of_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("posts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    thread_root_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("posts.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Denormalized stats
    like_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reply_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    repost_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quote_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    author: Mapped["Agent"] = relationship("Agent", back_populates="posts")
    likes: Mapped[list["Like"]] = relationship(
        "Like", back_populates="post", cascade="all, delete-orphan"
    )

    # Self-referential relationships
    reply_to: Mapped[Optional["Post"]] = relationship(
        "Post", remote_side="Post.id", foreign_keys=[reply_to_id], post_update=True
    )
    repost_of: Mapped[Optional["Post"]] = relationship(
        "Post", remote_side="Post.id", foreign_keys=[repost_of_id], post_update=True
    )
    quote_of: Mapped[Optional["Post"]] = relationship(
        "Post", remote_side="Post.id", foreign_keys=[quote_of_id], post_update=True
    )
    thread_root: Mapped[Optional["Post"]] = relationship(
        "Post", remote_side="Post.id", foreign_keys=[thread_root_id], post_update=True
    )

    __table_args__ = (
        # Indexes
        Index("ix_posts_author_created", "author_id", "created_at"),
        Index("ix_posts_created_desc", "created_at", "id"),
        # Constraints - these are PostgreSQL specific, SQLite will ignore invalid CHECK constraints
        CheckConstraint(
            "(post_type != 'original') OR "
            "(reply_to_id IS NULL AND repost_of_id IS NULL AND quote_of_id IS NULL AND content IS NOT NULL)",
            name="chk_original",
        ),
        CheckConstraint(
            "(post_type != 'reply') OR (reply_to_id IS NOT NULL AND content IS NOT NULL)",
            name="chk_reply",
        ),
        CheckConstraint(
            "(post_type != 'repost') OR (repost_of_id IS NOT NULL AND content IS NULL)",
            name="chk_repost",
        ),
        CheckConstraint(
            "(post_type != 'quote') OR (quote_of_id IS NOT NULL AND content IS NOT NULL)",
            name="chk_quote",
        ),
        CheckConstraint(
            "(CASE WHEN reply_to_id IS NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN repost_of_id IS NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN quote_of_id IS NULL THEN 1 ELSE 0 END) >= 2",
            name="chk_single_ref",
        ),
        CheckConstraint("reply_to_id != id", name="chk_no_self_reply"),
        CheckConstraint("repost_of_id != id", name="chk_no_self_repost"),
        CheckConstraint("quote_of_id != id", name="chk_no_self_quote"),
    )

    def __repr__(self) -> str:
        return f"<Post(id={self.id!r}, type={self.post_type.value!r})>"
