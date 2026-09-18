"""Local login retry limit — slows password guessing on the home network."""

from __future__ import annotations

import time

WINDOW_SEC = 15 * 60
MAX_FAILS_PER_USER = 8
MAX_FAILS_GLOBAL = 30

_FAILS: dict[str, list[float]] = {}
_GLOBAL_KEY = "*"


def _prune(key: str, now: float | None = None) -> list[float]:
    now = now if now is not None else time.time()
    cutoff = now - WINDOW_SEC
    bucket = [t for t in _FAILS.get(key, []) if t > cutoff]
    if bucket:
        _FAILS[key] = bucket
    else:
        _FAILS.pop(key, None)
    return bucket


def _norm_user(username: str) -> str:
    return (username or "").strip().lower() or "_"


def allow_login_attempt(username: str) -> bool:
    """False when this username (or the whole app) has too many recent failures."""
    now = time.time()
    if len(_prune(_GLOBAL_KEY, now)) >= MAX_FAILS_GLOBAL:
        return False
    if len(_prune(_norm_user(username), now)) >= MAX_FAILS_PER_USER:
        return False
    return True


def record_login_failure(username: str) -> None:
    now = time.time()
    user_key = _norm_user(username)
    user_bucket = _prune(user_key, now)
    user_bucket.append(now)
    _FAILS[user_key] = user_bucket
    global_bucket = _prune(_GLOBAL_KEY, now)
    global_bucket.append(now)
    _FAILS[_GLOBAL_KEY] = global_bucket


def clear_login_failures(username: str) -> None:
    _FAILS.pop(_norm_user(username), None)


def reset_login_limits_for_tests() -> None:
    _FAILS.clear()
