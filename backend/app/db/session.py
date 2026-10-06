from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import BACKEND_DIR


def build_engine(database_url: str) -> Engine:
    kwargs: dict[str, Any] = {"pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(database_url, **kwargs)

    if engine.dialect.name == "sqlite":
        # SQLite ignores ON DELETE CASCADE unless foreign keys are switched on per connection.
        @event.listens_for(engine, "connect")
        def _enable_sqlite_fks(dbapi_connection: Any, _: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
    finally:
        session.close()


def run_migrations(database_url: str) -> None:
    """Upgrade the database schema to the latest Alembic revision."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(BACKEND_DIR) / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(BACKEND_DIR) / "alembic"))
    # ConfigParser treats % as interpolation syntax.
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    # Keep the application's logging configuration when migrating at startup.
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")
