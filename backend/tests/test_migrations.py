import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, make_url, text
from sqlalchemy.exc import IntegrityError

from app.core.config import BACKEND_DIR
from app.db.base import Base

PG_URL = (
    os.environ.get("TEST_DATABASE_URL", "") if os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql") else ""
)


def _config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    cfg.attributes["configure_logger"] = False
    return cfg


def test_migrations_upgrade_downgrade_and_match_models(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'migrate.db').as_posix()}"
    cfg = _config(url)
    command.upgrade(cfg, "head")

    engine = create_engine(url)
    tables = set(inspect(engine).get_table_names())
    assert set(Base.metadata.tables) <= tables
    for table in Base.metadata.sorted_tables:
        migrated = {c["name"] for c in inspect(engine).get_columns(table.name)}
        assert {c.name for c in table.columns} <= migrated, table.name

    command.downgrade(cfg, "base")
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    engine.dispose()


@contextmanager
def _scratch_postgres_database() -> Iterator[str]:
    """A throw-away database on the test server: destructive migration tests never touch a shared one."""
    server = make_url(PG_URL)
    name = f"aica_migrations_{uuid.uuid4().hex[:10]}"
    admin = create_engine(server, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield server.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def _seed_pre_account_data(url: str) -> None:
    """Rows as a deployment from before accounts existed (schema 0002) would have them."""
    engine = create_engine(url)
    now = "2026-10-01 12:00:00+00:00"
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO courses (id, name, code, color, created_at, updated_at) "
                "VALUES ('legacy-course', 'Old course', 'OLD 1', 'indigo', :now, :now)"
            ),
            {"now": now},
        )
        conn.execute(
            text(
                "INSERT INTO documents (id, course_id, filename, file_type, mime_type, size_bytes, sha256, "
                "storage_path, status, chunk_count, created_at, embedding_signature) VALUES ('legacy-doc', "
                "'legacy-course', 'notes.md', 'md', 'text/markdown', 10, 'abc', '/tmp/x.md', 'ready', 1, :now, 'x')"
            ),
            {"now": now},
        )
        conn.execute(
            text(
                "INSERT INTO chunks (id, document_id, course_id, chunk_index, content, char_count, created_at) "
                "VALUES ('legacy-chunk', 'legacy-doc', 'legacy-course', 0, 'Gradient descent basics', 23, :now)"
            ),
            {"now": now},
        )
        conn.execute(
            text(
                "INSERT INTO chat_sessions (id, course_id, title, created_at, updated_at) "
                "VALUES ('legacy-chat', 'legacy-course', 'Old chat', :now, :now)"
            ),
            {"now": now},
        )
    engine.dispose()


def _legacy_upgrade_round_trip(url: str) -> None:
    cfg = _config(url)
    command.upgrade(cfg, "0002")
    _seed_pre_account_data(url)

    command.upgrade(cfg, "head")
    engine = create_engine(url)
    with engine.connect() as conn:
        # Nothing was lost, and nothing was handed to anybody.
        assert conn.execute(text("SELECT owner_id, name FROM courses")).all() == [(None, "Old course")]
        assert conn.execute(text("SELECT count(*) FROM documents")).scalar() == 1
        assert conn.execute(text("SELECT count(*) FROM chunks")).scalar() == 1
        assert conn.execute(text("SELECT count(*) FROM chat_sessions")).scalar() == 1
        assert conn.execute(text("SELECT count(*) FROM users")).scalar() == 0
    columns = {c["name"]: c for c in inspect(engine).get_columns("courses")}
    assert columns["owner_id"]["nullable"] is True  # migration state, see 0003's docstring
    assert "ix_courses_owner_id" in {ix["name"] for ix in inspect(engine).get_indexes("courses")}

    if engine.dialect.name == "postgresql":
        with engine.connect() as conn:
            indexes = set(conn.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'chunks'")).scalars())
            assert {"ix_chunks_embedding_hnsw", "ix_chunks_content_tsv"} <= indexes  # untouched by 0003
            validated = conn.execute(
                text("SELECT convalidated FROM pg_constraint WHERE conname = 'ck_courses_owner_required'")
            ).scalar()
            assert validated is False  # NOT VALID: legacy rows tolerated...
        with pytest.raises(IntegrityError), engine.begin() as conn:  # ...but new rows need an owner
            conn.execute(
                text(
                    "INSERT INTO courses (id, name, color, created_at, updated_at) "
                    "VALUES ('new', 'New', 'indigo', now(), now())"
                )
            )

    command.downgrade(cfg, "0002")
    assert "users" not in inspect(engine).get_table_names()
    assert "owner_id" not in {c["name"] for c in inspect(engine).get_columns("courses")}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM courses")).scalar() == 1

    command.upgrade(cfg, "head")  # and forward again
    command.downgrade(cfg, "base")
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    engine.dispose()


def test_existing_data_survives_the_accounts_migration_on_sqlite(tmp_path: Path) -> None:
    _legacy_upgrade_round_trip(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")


@pytest.mark.skipif(not PG_URL, reason="needs TEST_DATABASE_URL pointing at PostgreSQL + pgvector")
def test_existing_data_survives_the_accounts_migration_on_postgres() -> None:
    with _scratch_postgres_database() as url:
        _legacy_upgrade_round_trip(url)
