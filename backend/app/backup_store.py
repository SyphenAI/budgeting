"""Quiet copies of the budget file on this computer (not the cloud)."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import shutil

from .db import DATA_DIR, DB_PATH

BACKUP_DIR = DATA_DIR / "backups"
KEEP = 12


def _stamp() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d-%H%M")


def save_local_backup() -> Path | None:
    if not DB_PATH.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    dest = BACKUP_DIR / f"household-{_stamp()}.db"
    shutil.copy2(DB_PATH, dest)
    _prune()
    return dest


def _prune() -> None:
    if not BACKUP_DIR.exists():
        return
    files = sorted(BACKUP_DIR.glob("household-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[KEEP:]:
        try:
            old.unlink()
        except OSError:
            pass


def backup_files() -> list[Path]:
    if not BACKUP_DIR.exists():
        return []
    return sorted(BACKUP_DIR.glob("household-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)


def last_backup_date() -> date | None:
    files = backup_files()
    if not files:
        return None
    # Prefer the date in the filename (household-YYYY-MM-DD-HHMM.db)
    name = files[0].stem
    parts = name.split("-")
    if len(parts) >= 4:
        try:
            return date(int(parts[1]), int(parts[2]), int(parts[3]))
        except ValueError:
            pass
    return datetime.utcfromtimestamp(files[0].stat().st_mtime).date()


def backup_status() -> dict:
    last = last_backup_date()
    today = date.today()
    this_month = bool(last and last.year == today.year and last.month == today.month)
    return {
        "last_backup": last.isoformat() if last else None,
        "backup_this_month": this_month,
        "backup_nag": not this_month,
        "backup_count": len(backup_files()),
        "folder": "data/backups",
    }


def maybe_monthly_backup() -> Path | None:
    """Save one copy if none exists for this calendar month."""
    st = backup_status()
    if st["backup_this_month"]:
        return None
    return save_local_backup()
