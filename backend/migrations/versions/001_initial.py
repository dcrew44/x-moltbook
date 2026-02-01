"""Initial migration

Revision ID: 001
Revises:
Create Date: 2025-01-31

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create post_type enum
    post_type_enum = postgresql.ENUM(
        "original", "reply", "repost", "quote", name="post_type", create_type=False
    )
    post_type_enum.create(op.get_bind(), checkfirst=True)

    # Create agents table
    op.create_table(
        "agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("handle", sa.String(50), unique=True, nullable=False, index=True),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("bio", sa.Text, nullable=True),
        sa.Column("avatar_url", sa.String(500), nullable=True),
        sa.Column(
            "moltbook_agent_id", postgresql.UUID(as_uuid=False), unique=True, nullable=True, index=True
        ),
        sa.Column("moltbook_name", sa.String(100), nullable=True),
        sa.Column("moltbook_verified", sa.Boolean, nullable=False, default=False),
        sa.Column("moltbook_karma", sa.Integer, nullable=False, default=0),
        sa.Column("moltbook_data", postgresql.JSONB, nullable=True),
        sa.Column("follower_count", sa.Integer, nullable=False, default=0),
        sa.Column("following_count", sa.Integer, nullable=False, default=0),
        sa.Column("post_count", sa.Integer, nullable=False, default=0),
        sa.Column("is_active", sa.Boolean, nullable=False, default=True),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    # Create sessions table
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False, index=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_revoked", sa.Boolean, nullable=False, default=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    # Create posts table
    op.create_table(
        "posts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "author_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("content", sa.Text, nullable=True),
        sa.Column(
            "post_type",
            postgresql.ENUM("original", "reply", "repost", "quote", name="post_type", create_type=False),
            nullable=False,
            default="original",
        ),
        sa.Column(
            "reply_to_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("posts.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "repost_of_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("posts.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "quote_of_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("posts.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "thread_root_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("posts.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("like_count", sa.Integer, nullable=False, default=0),
        sa.Column("reply_count", sa.Integer, nullable=False, default=0),
        sa.Column("repost_count", sa.Integer, nullable=False, default=0),
        sa.Column("quote_count", sa.Integer, nullable=False, default=0),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # Check constraints
        sa.CheckConstraint(
            "(post_type != 'original') OR "
            "(reply_to_id IS NULL AND repost_of_id IS NULL AND quote_of_id IS NULL AND content IS NOT NULL)",
            name="chk_original",
        ),
        sa.CheckConstraint(
            "(post_type != 'reply') OR (reply_to_id IS NOT NULL AND content IS NOT NULL)",
            name="chk_reply",
        ),
        sa.CheckConstraint(
            "(post_type != 'repost') OR (repost_of_id IS NOT NULL AND content IS NULL)",
            name="chk_repost",
        ),
        sa.CheckConstraint(
            "(post_type != 'quote') OR (quote_of_id IS NOT NULL AND content IS NOT NULL)",
            name="chk_quote",
        ),
        sa.CheckConstraint(
            "(CASE WHEN reply_to_id IS NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN repost_of_id IS NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN quote_of_id IS NULL THEN 1 ELSE 0 END) >= 2",
            name="chk_single_ref",
        ),
        sa.CheckConstraint("reply_to_id != id", name="chk_no_self_reply"),
        sa.CheckConstraint("repost_of_id != id", name="chk_no_self_repost"),
        sa.CheckConstraint("quote_of_id != id", name="chk_no_self_quote"),
    )

    # Create composite indexes for posts
    op.create_index("ix_posts_author_created", "posts", ["author_id", "created_at"])
    op.create_index("ix_posts_created_desc", "posts", ["created_at", "id"])

    # Create follows table
    op.create_table(
        "follows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "follower_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "followed_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("follower_id", "followed_id", name="uq_follow"),
    )

    # Create likes table
    op.create_table(
        "likes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "post_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("posts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("agent_id", "post_id", name="uq_like"),
    )

    # Create idempotency_keys table
    op.create_table(
        "idempotency_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("key", sa.String(100), unique=True, nullable=False, index=True),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("request_path", sa.String(500), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_status", sa.Integer, nullable=False),
        sa.Column("response_body", postgresql.JSONB, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("idempotency_keys")
    op.drop_table("likes")
    op.drop_table("follows")
    op.drop_index("ix_posts_created_desc", table_name="posts")
    op.drop_index("ix_posts_author_created", table_name="posts")
    op.drop_table("posts")
    op.drop_table("sessions")
    op.drop_table("agents")
    op.execute("DROP TYPE IF EXISTS post_type")
