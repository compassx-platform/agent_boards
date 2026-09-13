import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

_is_sqlite = settings.database_url.startswith("sqlite")
engine = create_engine(
    settings.database_url,
    connect_args={**({"check_same_thread": False, "timeout": 30} if _is_sqlite else {})},
)


if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_columns() -> None:
    """Idempotent dev migration: add columns that don't exist yet (SQLite)."""
    if not _is_sqlite:
        return
    from sqlalchemy import inspect, text

    cols = {c["name"] for c in inspect(engine).get_columns("tasks")}
    if "harness" not in cols:
        with engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE tasks ADD COLUMN harness VARCHAR(64) DEFAULT 'opencode-native'")
            )