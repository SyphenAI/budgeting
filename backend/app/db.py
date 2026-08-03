from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATA_DIR = Path(os.environ.get("BUDGET_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "budget.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def migrate_sqlite() -> None:
    """Lightweight column adds for existing local DBs."""
    insp = inspect(engine)
    if "users" not in insp.get_table_names():
        return
    with engine.begin() as conn:
        if "users" in insp.get_table_names():
            cols = {c["name"] for c in insp.get_columns("users")}
            if "must_change_password" not in cols:
                conn.execute(
                    text(
                        "ALTER TABLE users ADD COLUMN must_change_password "
                        "BOOLEAN NOT NULL DEFAULT 0"
                    )
                )
        if "sessions" in insp.get_table_names():
            scols = {c["name"] for c in insp.get_columns("sessions")}
            if "last_seen" not in scols:
                # SQLite rejects non-constant defaults on ADD COLUMN
                conn.execute(text("ALTER TABLE sessions ADD COLUMN last_seen DATETIME"))
                conn.execute(
                    text(
                        "UPDATE sessions SET last_seen = created_at "
                        "WHERE last_seen IS NULL"
                    )
                )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
