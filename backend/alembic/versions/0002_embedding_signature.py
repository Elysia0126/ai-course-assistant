"""Record which embedding model produced each document's vectors.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.config import get_settings

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("embedding_signature", sa.String(200)))
    # Existing vectors were produced by the configuration that is running this migration.
    settings = get_settings()
    signature = f"{settings.embedding_provider}:{settings.embedding_model}:{settings.embedding_dim}"
    if settings.embedding_provider == "hash":
        signature = f"hash:feature-hash-{settings.embedding_dim}:{settings.embedding_dim}"
    op.execute(
        sa.text("UPDATE documents SET embedding_signature = :sig WHERE status = 'ready'").bindparams(sig=signature)
    )


def downgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.drop_column("embedding_signature")
