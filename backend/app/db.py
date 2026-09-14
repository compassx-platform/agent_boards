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
    """Idempotent dev migration: add missing columns to the tasks table (SQLite)."""
    if not _is_sqlite:
        return
    from sqlalchemy import inspect, text

    existing = {c["name"] for c in inspect(engine).get_columns("tasks")}
    additions = {
        "harness": "harness VARCHAR(64) DEFAULT 'opencode-native'",
        "compassx_app_id": "compassx_app_id VARCHAR(64)",
        "compassx_app_name": "compassx_app_name VARCHAR(255)",
        "compassx_workspace_id": "compassx_workspace_id VARCHAR(64)",
        "compassx_workspace_name": "compassx_workspace_name VARCHAR(255)",
        "compassx_published": "compassx_published BOOLEAN DEFAULT 0",
        "host_id": "host_id VARCHAR(64)",
        "host_name": "host_name VARCHAR(255)",
        "dev_url": "dev_url TEXT",
        "provisioning_steps": "provisioning_steps TEXT",
        "session_id": "session_id VARCHAR(128)",
        "bypass_verification": "bypass_verification BOOLEAN DEFAULT 1",
        "verification_bypass_outcome": "verification_bypass_outcome VARCHAR(32) DEFAULT 'needs_review'",
    }
    missing = [stmt for name, stmt in additions.items() if name not in existing]
    if missing:
        with engine.begin() as conn:
            for stmt in missing:
                conn.execute(text(f"ALTER TABLE tasks ADD COLUMN {stmt}"))

    # execution_sessions: "archived" flag — a session stops being the task's
    # single active session when archived (never deleted), and a new active
    # session is only created once none is left.
    ses_existing = {c["name"] for c in inspect(engine).get_columns("execution_sessions")}
    if "archived" not in ses_existing:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE execution_sessions ADD COLUMN archived BOOLEAN DEFAULT 0 NOT NULL"))