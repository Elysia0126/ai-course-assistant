"""Run an embedded PostgreSQL 16 + pgvector server for local development — no Docker required.

    python scripts/dev_db.py --write-env                     # start, and point backend/.env at it
    python scripts/dev_db.py --database course_assistant_test  # also create a database for tests

The server picks a free port on each start, so --write-env updates DATABASE_URL in backend/.env for you
(only that line is touched). Data lives in backend/data/pgdata.
Requires `pip install pgserver` (Python <= 3.12; included in requirements-dev.txt).
"""

import argparse
import re
import signal
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND_DIR / "data" / "pgdata"
ENV_FILE = BACKEND_DIR / ".env"


def write_database_url(url: str) -> None:
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    lines = [line for line in lines if not line.startswith("DATABASE_URL=")]
    lines.append(f"DATABASE_URL={url}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database", action="append", help="database name(s) to create (default: course_assistant)")
    parser.add_argument("--write-env", action="store_true", help="set DATABASE_URL in backend/.env (first database)")
    args = parser.parse_args()
    databases = args.database or ["course_assistant"]
    if not all(re.fullmatch(r"[a-z_][a-z0-9_]*", name) for name in databases):
        sys.exit("Database names may only contain lowercase letters, digits and underscores.")

    try:
        import pgserver
    except ImportError:
        sys.exit("pgserver is not installed. Run: pip install pgserver  (Python <= 3.12)")

    DATA_DIR.parent.mkdir(parents=True, exist_ok=True)
    server = pgserver.get_server(DATA_DIR, cleanup_mode="stop")
    for name in databases:
        exists = server.psql(f"SELECT 1 FROM pg_database WHERE datname = '{name}';")
        if "1 row" not in exists:
            server.psql(f"CREATE DATABASE {name};")

    urls = [server.get_uri(name).replace("postgresql://", "postgresql+psycopg://", 1) for name in databases]
    print("Embedded PostgreSQL + pgvector is running.")
    for url in urls:
        print(f"DATABASE_URL={url}")
    if args.write_env:
        write_database_url(urls[0])
        print(f"Updated DATABASE_URL in {ENV_FILE}")
    print("Press Ctrl+C to stop.", flush=True)

    stop = False

    def _handle(*_: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)
    while not stop:
        time.sleep(1)


if __name__ == "__main__":
    main()
