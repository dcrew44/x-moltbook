import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, GUID, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.post import Post


class Like(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "likes"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    post_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Relationships
    agent: Mapped["Agent"] = relationship("Agent", back_populates="likes")
    post: Mapped["Post"] = relationship("Post", back_populates="likes")

    __table_args__ = (UniqueConstraint("agent_id", "post_id", name="uq_like"),)

    def __repr__(self) -> str:
        return f"<Like(agent={self.agent_id!r}, post={self.post_id!r})>"
