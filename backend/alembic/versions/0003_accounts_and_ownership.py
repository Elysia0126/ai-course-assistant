"""User accounts, login sessions, password-reset tokens, rate-limit counters and course ownership.

Existing courses are kept but get no owner (owner_id NULL): they become invisible to every user until an
administrator assigns them with ``python -m app.cli assign-course``. They are never handed to whoever
registers first. On PostgreSQL a NOT VALID check constraint makes the owner mandatory for every new or updated
row while tolerating those legacy rows; ``python -m app.cli validate-ownership`` validates it once all legacy
courses are assigned.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(100)),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.Column("last_login_at", UTCDateTime()),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint("role IN ('user', 'admin')", name="ck_users_role"),
    )

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("remember", sa.Boolean(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("last_seen_at", UTCDateTime(), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.Column("revoked_at", UTCDateTime()),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.Column("used_at", UTCDateTime()),
        sa.UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
    )
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])

    op.create_table(
        "rate_limit_counters",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_rate_limit_counters_expires_at", "rate_limit_counters", ["expires_at"])

    # Batch mode rebuilds the table on SQLite (which can't add a foreign key in place); on PostgreSQL it is a
    # plain ALTER TABLE, so the pgvector/full-text indexes on other tables are untouched.
    with op.batch_alter_table("courses") as batch:
        batch.add_column(sa.Column("owner_id", sa.String(36)))
        batch.create_foreign_key("fk_courses_owner_id_users", "users", ["owner_id"], ["id"], ondelete="RESTRICT")
        batch.create_index("ix_courses_owner_id", ["owner_id"])

    if op.get_bind().dialect.name == "postgresql":
        # NOT VALID: enforced for every new or updated row, while legacy rows without an owner stay readable.
        op.execute(
            "ALTER TABLE courses ADD CONSTRAINT ck_courses_owner_required CHECK (owner_id IS NOT NULL) NOT VALID"
        )


def downgrade() -> None:
    # Destroys accounts and ownership. Courses and everything in them are kept.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE courses DROP CONSTRAINT IF EXISTS ck_courses_owner_required")
    with op.batch_alter_table("courses") as batch:
        batch.drop_index("ix_courses_owner_id")
        batch.drop_constraint("fk_courses_owner_id_users", type_="foreignkey")
        batch.drop_column("owner_id")
    for table in ("rate_limit_counters", "password_reset_tokens", "auth_sessions", "users"):
        op.drop_table(table)
