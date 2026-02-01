import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, GUID, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.agent import Agent


class Follow(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "follows"

    follower_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    followed_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Relationships
    follower: Mapped["Agent"] = relationship(
        "Agent", foreign_keys=[follower_id], back_populates="following"
    )
    followed: Mapped["Agent"] = relationship(
        "Agent", foreign_keys=[followed_id], back_populates="followers"
    )

    __table_args__ = (UniqueConstraint("follower_id", "followed_id", name="uq_follow"),)

    def __repr__(self) -> str:
        return f"<Follow(follower={self.follower_id!r}, followed={self.followed_id!r})>"
