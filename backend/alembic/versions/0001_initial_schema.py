"""Initial schema: courses, documents, chunks (pgvector + full-text), chat, quizzes, flashcards.

Revision ID: 0001
Revises:
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.config import get_settings
from app.db.types import EmbeddingVector, UTCDateTime

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    is_pg = op.get_bind().dialect.name == "postgresql"
    if is_pg:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "courses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("code", sa.String(50)),
        sa.Column("term", sa.String(50)),
        sa.Column("description", sa.Text()),
        sa.Column("color", sa.String(20), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("course_id", sa.String(36), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_type", sa.String(10), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("page_count", sa.Integer()),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("processed_at", UTCDateTime()),
        sa.UniqueConstraint("course_id", "sha256", name="uq_documents_course_sha256"),
    )
    op.create_index("ix_documents_course_id", "documents", ["course_id"])
    op.create_index("ix_documents_status", "documents", ["status"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("course_id", sa.String(36), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer()),
        sa.Column("section", sa.String(300)),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("embedding", EmbeddingVector(get_settings().embedding_dim)),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_index("ix_chunks_course_id", "chunks", ["course_id"])
    if is_pg:
        # Keyword side of hybrid search: a stored tsvector kept in sync by Postgres itself.
        op.execute(
            "ALTER TABLE chunks ADD COLUMN content_tsv tsvector GENERATED ALWAYS AS "
            "(to_tsvector('english', coalesce(section, '') || ' ' || content)) STORED"
        )
        op.execute("CREATE INDEX ix_chunks_content_tsv ON chunks USING gin (content_tsv)")
        # Semantic side: approximate nearest neighbour index on cosine distance.
        op.execute("CREATE INDEX ix_chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops)")

    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("course_id", sa.String(36), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_chat_sessions_course_id", "chat_sessions", ["course_id"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sources", _json(), nullable=False),
        sa.Column("meta", _json(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])

    op.create_table(
        "quizzes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("course_id", sa.String(36), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("difficulty", sa.String(20), nullable=False),
        sa.Column("topic", sa.String(200)),
        sa.Column("document_ids", _json(), nullable=False),
        sa.Column("generator", sa.String(80), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_quizzes_course_id", "quizzes", ["course_id"])

    op.create_table(
        "quiz_questions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("quiz_id", sa.String(36), sa.ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("question_type", sa.String(20), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("options", _json(), nullable=False),
        sa.Column("correct_answer", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("source", _json()),
    )
    op.create_index("ix_quiz_questions_quiz_id", "quiz_questions", ["quiz_id"])

    op.create_table(
        "quiz_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("quiz_id", sa.String(36), sa.ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("answers", _json(), nullable=False),
        sa.Column("results", _json(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("correct_count", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_quiz_attempts_quiz_id", "quiz_attempts", ["quiz_id"])

    op.create_table(
        "flashcard_decks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("course_id", sa.String(36), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("topic", sa.String(200)),
        sa.Column("document_ids", _json(), nullable=False),
        sa.Column("generator", sa.String(80), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_flashcard_decks_course_id", "flashcard_decks", ["course_id"])

    op.create_table(
        "flashcards",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("deck_id", sa.String(36), sa.ForeignKey("flashcard_decks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("front", sa.Text(), nullable=False),
        sa.Column("back", sa.Text(), nullable=False),
        sa.Column("source", _json()),
        sa.Column("ease_factor", sa.Float(), nullable=False),
        sa.Column("interval_days", sa.Float(), nullable=False),
        sa.Column("repetitions", sa.Integer(), nullable=False),
        sa.Column("lapses", sa.Integer(), nullable=False),
        sa.Column("review_count", sa.Integer(), nullable=False),
        sa.Column("due_at", UTCDateTime(), nullable=False),
        sa.Column("last_reviewed_at", UTCDateTime()),
    )
    op.create_index("ix_flashcards_deck_id", "flashcards", ["deck_id"])
    op.create_index("ix_flashcards_due_at", "flashcards", ["due_at"])


def downgrade() -> None:
    for table in (
        "flashcards",
        "flashcard_decks",
        "quiz_attempts",
        "quiz_questions",
        "quizzes",
        "chat_messages",
        "chat_sessions",
        "chunks",
        "documents",
        "courses",
    ):
        op.drop_table(table)
