"""Local password rescue code — resets a login without erasing the budget."""

from __future__ import annotations

import re
import secrets
import time

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_ATTEMPTS: list[float] = []


def make_rescue_code() -> str:
    chunks = []
    for _ in range(3):
        chunks.append("".join(secrets.choice(ALPHABET) for _ in range(4)))
    return "-".join(chunks)


def normalize_rescue_code(raw: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", raw or "").upper()


def allow_recover_attempt() -> bool:
    """Very small local rate limit so a kid cannot hammer guesses."""
    now = time.time()
    cutoff = now - 15 * 60
    while _ATTEMPTS and _ATTEMPTS[0] < cutoff:
        _ATTEMPTS.pop(0)
    if len(_ATTEMPTS) >= 8:
        return False
    _ATTEMPTS.append(now)
    return True
