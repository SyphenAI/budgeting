"""Download the official Household Money zip and replace program files.

Never touches the data folder, passwords, or local secrets.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

REPO_VERSION_URL = "https://raw.githubusercontent.com/SyphenAI/budgeting/main/VERSION"
REPO_ZIP_URL = "https://github.com/SyphenAI/budgeting/archive/refs/heads/main.zip"
USER_AGENT = "HouseholdMoney-Updater/1.0"

EXCLUDE_DIRS = {".git", ".venv", "venv", "data", "private", "__pycache__", ".idea", ".vscode"}
EXCLUDE_FILES = {"github_pat.txt", ".env", "budget.db"}


def running_in_docker() -> bool:
    return Path("/.dockerenv").exists() or os.environ.get("BUDGET_IN_DOCKER") == "1"


def install_root() -> Path:
    """Folder that should receive new program files.

    In Docker, compose mounts the Windows project folder at /app so writes
    land on the computer (not only inside a throwaway container).
    """
    env = (os.environ.get("HOST_APP_DIR") or "").strip()
    if env:
        p = Path(env)
        if p.is_dir():
            return p
    return Path(__file__).resolve().parents[2]


def read_local_version(root: Path | None = None) -> str:
    path = (root or install_root()) / "VERSION"
    if not path.exists():
        return "unknown"
    return path.read_text(encoding="utf-8").strip() or "unknown"


def parse_version(text: str) -> tuple[int, ...]:
    nums = [int(x) for x in re.findall(r"\d+", text or "")]
    return tuple(nums) if nums else (0,)


def is_newer(latest: str, current: str) -> bool:
    if not latest or latest == "unknown" or current == "unknown":
        return False
    return parse_version(latest) > parse_version(current)


def _http_get(url: str, timeout: int = 30) -> bytes:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_latest_version() -> str:
    raw = _http_get(REPO_VERSION_URL, timeout=15).decode("utf-8", errors="replace")
    ver = raw.strip().splitlines()[0].strip() if raw.strip() else ""
    if not ver:
        raise RuntimeError("The update check came back empty.")
    return ver


def _should_skip_dir(name: str) -> bool:
    return name in EXCLUDE_DIRS or name.endswith(".egg-info")


def _should_skip_file(name: str) -> bool:
    if name in EXCLUDE_FILES:
        return True
    if name.endswith(".db"):
        return True
    if name.endswith(".pyc"):
        return True
    return False


def _copy_tree(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        name = item.name
        target = dst / name
        if item.is_dir():
            if _should_skip_dir(name):
                continue
            _copy_tree(item, target)
        else:
            if _should_skip_file(name):
                continue
            shutil.copy2(item, target)


def _find_extracted_app(extract_dir: Path) -> Path:
    for child in extract_dir.iterdir():
        if not child.is_dir():
            continue
        if (child / "backend" / "app" / "main.py").exists():
            return child
        if (child / "start.bat").exists() and (child / "backend").is_dir():
            return child
    raise RuntimeError("The download did not look like Household Money.")


def apply_update(root: Path | None = None) -> str:
    """Replace program files. Returns the version string after copy."""
    dest = root or install_root()
    tmp = Path(tempfile.mkdtemp(prefix="household-money-upd-"))
    zip_path = tmp / "app.zip"
    extract_dir = tmp / "unpack"
    try:
        zip_path.write_bytes(_http_get(REPO_ZIP_URL, timeout=90))
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)
        src = _find_extracted_app(extract_dir)
        _copy_tree(src, dest)

        req = dest / "backend" / "requirements.txt"
        if req.exists():
            try:
                import subprocess

                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "-r", str(req), "-q"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                # Packages are already in the image / venv; file update still counts.
                pass

        return read_local_version(dest)
    except URLError as exc:
        raise RuntimeError(
            "Could not download the update. Check that this computer is online, then try again."
        ) from exc
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def schedule_restart(delay_sec: float = 1.5) -> None:
    """Exit so Docker (or the start window) can bring the app back with new code."""

    def _die() -> None:
        time.sleep(delay_sec)
        os._exit(0)

    threading.Thread(target=_die, daemon=True).start()
