from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.core.config import BACKEND_DIR
from app.db.base import Base


def _config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
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
