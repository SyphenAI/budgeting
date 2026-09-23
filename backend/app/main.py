from __future__ import annotations

import csv
import io
import re
import secrets
from calendar import monthrange
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import shutil
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask
from fastapi.staticfiles import StaticFiles
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .db import Base, engine, get_db, migrate_sqlite
from .models import (
    BudgetItem,
    CardRecurringMark,
    CardTransaction,
    Debt,
    Goal,
    GoalSave,
    Household,
    Investment,
    ItemName,
    JobPay,
    SessionToken,
    User,
)
from .paystub import monthly_equivalent, next_pay_dates, parse_paystub_pdf
from .planning import (
    compare_strategies,
    demographic_planning_notes,
    goal_metrics,
    simulate_debt_paydown,
)
from .schemas import (
    BudgetItemCreate,
    BudgetItemOut,
    BudgetItemUpdate,
    CalendarDay,
    CalendarResponse,
    CardApplyRequest,
    DebtCreate,
    DebtOut,
    DebtPlanRequest,
    DebtPlanSummary,
    DebtUpdate,
    GoalCreate,
    GoalSaveCreate,
    GoalOut,
    GoalUpdate,
    HouseholdOut,
    HouseholdUpdate,
    InvestmentCreate,
    InvestmentOut,
    InvestmentUpdate,
    ItemNameCreate,
    ItemNameOut,
    JobPayCreate,
    JobPayOut,
    LoginRequest,
    LoginResponse,
    MemberCreate,
    MemberOut,
    MetricsResponse,
    PasswordChangeRequest,
    RescueResetRequest,
    PayStubApplyRequest,
    SubscriptionCreate,
    ImportCommitRequest,
    ImportCommitResponse,
    SnapshotOut,
    StatementParseResponse,
    StatementRow,
    UpcomingResponse,
)
from .bank_import import BANK_PRESETS, parse_bank_csv
from .bank_pdf import parse_statement_pdf
from .categorize import (
    IMPORT_CATEGORIES,
    is_credit_card_category,
    looks_like_subscription,
    suggest_card_name,
    suggest_category,
)
from .seed import ensure_subscription_names, seed_if_empty
from .subscriptions import summarize_subscriptions
from .card_statement import analyze_card_spend, find_recurring_charges, parse_card_pdf
from .categorize import suggest_category
from .recurring import (
    RECURRING,
    REPEAT_TYPES,
    _add_months,
    delete_series,
    ensure_recurring_through,
    next_after,
    series_key,
    update_series,
)
from .backup_store import backup_status, maybe_monthly_backup, save_local_backup
from .rescue import allow_recover_attempt, make_rescue_code, normalize_rescue_code
from .auth_limits import allow_login_attempt, clear_login_failures, record_login_failure
from .updater import (
    apply_update,
    fetch_latest_version,
    is_newer,
    read_local_version,
    running_in_docker,
    schedule_restart,
)

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Local shared-PC safety: expire sessions after idle (minutes)
DEFAULT_IDLE_MINUTES = 30
MIN_IDLE_MINUTES = 10
MAX_IDLE_MINUTES = 120

# Viewer may look (GET) and do these non-GET calls. Everything else is blocked.
VIEWER_SAFE_WRITE_PATHS = {
    "/api/logout",
    "/api/me/password",
    "/api/debts/plan",
}
VIEWER_BLOCKED_GET_PATHS = {
    "/api/backup",  # full database download
}
VIEWER_WRITE_DETAIL = (
    "This login can look only. Ask an adult to change bills or settings."
)
LOGIN_RETRY_DETAIL = "Too many wrong passwords. Wait 15 minutes, then try again."

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
BRAND = ROOT / "brand"

app = FastAPI(title="Household Money", version=read_local_version())


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    migrate_sqlite()
    db = next(get_db())
    try:
        seed_if_empty(db)
        ensure_subscription_names(db)
        maybe_monthly_backup()
    finally:
        db.close()


def current_user(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Login required")
    token = authorization.split(" ", 1)[1].strip()
    row = db.get(SessionToken, token)
    if not row:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    now = datetime.utcnow()
    last = getattr(row, "last_seen", None) or row.created_at or now
    idle_minutes = _idle_minutes(db)
    idle_seconds = (now - last).total_seconds()
    if idle_seconds > idle_minutes * 60:
        db.delete(row)
        db.commit()
        raise HTTPException(
            status_code=401,
            detail=f"Signed out after {idle_minutes} minutes with no tapping",
        )

    row.last_seen = now
    db.commit()

    user = db.get(User, row.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    _enforce_viewer_readonly(request, user)
    return user


def _enforce_viewer_readonly(request: Request, user: User) -> None:
    if (user.role or "").strip().lower() != "viewer":
        return
    path = (request.url.path or "/").rstrip("/") or "/"
    method = (request.method or "GET").upper()
    if path in VIEWER_BLOCKED_GET_PATHS:
        raise HTTPException(status_code=403, detail=VIEWER_WRITE_DETAIL)
    if method not in ("GET", "HEAD", "OPTIONS") and path not in VIEWER_SAFE_WRITE_PATHS:
        raise HTTPException(status_code=403, detail=VIEWER_WRITE_DETAIL)


def _session_token_from_header(authorization: Optional[str]) -> Optional[str]:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    return token or None


def _revoke_other_sessions(db: Session, user_id: int, keep_token: Optional[str]) -> None:
    q = db.query(SessionToken).filter(SessionToken.user_id == user_id)
    if keep_token:
        q = q.filter(SessionToken.token != keep_token)
    q.delete(synchronize_session=False)


def get_household(db: Session) -> Household:
    hh = db.query(Household).first()
    if not hh:
        raise HTTPException(status_code=500, detail="No household configured")
    return hh


def _idle_minutes(db: Session) -> int:
    hh = db.query(Household).first()
    raw = getattr(hh, "idle_minutes", None) if hh else None
    try:
        mins = int(raw if raw is not None else DEFAULT_IDLE_MINUTES)
    except (TypeError, ValueError):
        mins = DEFAULT_IDLE_MINUTES
    return max(MIN_IDLE_MINUTES, min(MAX_IDLE_MINUTES, mins or DEFAULT_IDLE_MINUTES))


def _household_out(hh: Household) -> HouseholdOut:
    return HouseholdOut(
        id=hh.id,
        name=hh.name,
        starting_balance=hh.starting_balance,
        safety_threshold=float(getattr(hh, "safety_threshold", 0) or 0),
        onboarding_done=bool(getattr(hh, "onboarding_done", False)),
        currency=hh.currency or "USD",
        primary_age=getattr(hh, "primary_age", None),
        partner_age=getattr(hh, "partner_age", None),
        state=getattr(hh, "state", "") or "",
        idle_minutes=_clamp_idle(getattr(hh, "idle_minutes", DEFAULT_IDLE_MINUTES)),
        has_recovery_key=bool(getattr(hh, "recovery_key_hash", "") or ""),
    )


def _clamp_idle(raw) -> int:
    try:
        mins = int(raw if raw is not None else DEFAULT_IDLE_MINUTES)
    except (TypeError, ValueError):
        mins = DEFAULT_IDLE_MINUTES
    return max(MIN_IDLE_MINUTES, min(MAX_IDLE_MINUTES, mins or DEFAULT_IDLE_MINUTES))


# ── Auth ──────────────────────────────────────────────────────────

@app.post("/api/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    username = body.username.strip()
    if not allow_login_attempt(username):
        raise HTTPException(status_code=429, detail=LOGIN_RETRY_DETAIL)
    user = db.query(User).filter(User.username == username.lower()).first()
    # usernames stored lowercase-ish; also try exact
    if not user:
        user = db.query(User).filter(User.username == username).first()
    if not user or not pwd.verify(body.password, user.password_hash):
        record_login_failure(username)
        raise HTTPException(status_code=401, detail="Wrong username or password")
    clear_login_failures(username)
    token = secrets.token_hex(32)
    now = datetime.utcnow()
    db.add(SessionToken(token=token, user_id=user.id, created_at=now, last_seen=now))
    db.commit()
    return LoginResponse(
        token=token,
        display_name=user.display_name or user.username,
        username=user.username,
        role=user.role,
        must_change_password=bool(getattr(user, "must_change_password", False)),
        idle_minutes=_idle_minutes(db),
    )


@app.post("/api/logout")
def logout(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        row = db.get(SessionToken, token)
        if row:
            db.delete(row)
            db.commit()
    return {"ok": True}


@app.get("/api/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "must_change_password": bool(getattr(user, "must_change_password", False)),
        "idle_minutes": _idle_minutes(db),
    }


@app.post("/api/me/password")
def change_password(
    body: PasswordChangeRequest,
    authorization: Optional[str] = Header(default=None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Change own password. Clears first-login must_change_password flag."""
    if not pwd.verify(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is wrong")
    new_pw = body.new_password.strip()
    if len(new_pw) < 4:
        raise HTTPException(status_code=400, detail="New password must be at least 4 characters")
    if new_pw == body.current_password:
        raise HTTPException(status_code=400, detail="Pick a new password different from the current one")
    # Discourage leaving the default install password
    if user.username == "admin" and new_pw.lower() == "admin":
        raise HTTPException(status_code=400, detail="Please choose something other than admin")

    user.password_hash = pwd.hash(new_pw)
    user.must_change_password = False
    hh = get_household(db)
    rescue_code = None
    if not (getattr(hh, "recovery_key_hash", "") or ""):
        rescue_code = make_rescue_code()
        hh.recovery_key_hash = pwd.hash(normalize_rescue_code(rescue_code))
    keep = _session_token_from_header(authorization)
    _revoke_other_sessions(db, user.id, keep)
    db.commit()
    return {
        "ok": True,
        "must_change_password": False,
        "rescue_code": rescue_code,
        "rescue_code_new": bool(rescue_code),
        "other_sessions_signed_out": True,
        "message": "Password updated. Other devices were signed out.",
    }


@app.post("/api/recover")
def recover_password(body: RescueResetRequest, db: Session = Depends(get_db)):
    """Reset a login with the rescue code. Does not erase bills or balances."""
    if not allow_recover_attempt():
        raise HTTPException(
            status_code=429,
            detail="Too many tries. Wait 15 minutes, then try again.",
        )
    hh = db.query(Household).first()
    stored = (getattr(hh, "recovery_key_hash", "") or "") if hh else ""
    if not stored:
        raise HTTPException(
            status_code=400,
            detail="No rescue code is set yet. Sign in, open Household, and make a rescue code.",
        )
    typed = normalize_rescue_code(body.rescue_code)
    if not typed or not pwd.verify(typed, stored):
        raise HTTPException(
            status_code=400,
            detail="That rescue code did not match. Check the letters and try again.",
        )
    new_pw = body.new_password.strip()
    if len(new_pw) < 4:
        raise HTTPException(status_code=400, detail="New password must be at least 4 characters")
    user = None
    if body.username and body.username.strip():
        uname = body.username.strip().lower()
        user = db.query(User).filter(User.username == uname).first()
        if not user:
            user = db.query(User).filter(User.username == body.username.strip()).first()
    if not user:
        user = (
            db.query(User)
            .filter(User.role.in_(("owner", "admin")))
            .order_by(User.id)
            .first()
        )
    if not user:
        raise HTTPException(status_code=400, detail="No owner login found to reset.")
    user.password_hash = pwd.hash(new_pw)
    user.must_change_password = False
    # Drop old sessions so the old password cannot stay signed in
    db.query(SessionToken).filter(SessionToken.user_id == user.id).delete()
    db.commit()
    return {
        "ok": True,
        "username": user.username,
        "message": f"Password reset for {user.username}. Your budget was not changed. Sign in with the new password.",
    }


@app.post("/api/household/rescue-code")
def make_new_rescue_code(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Create a new rescue code. The old one stops working. Shown once."""
    if user.role not in ("owner", "admin", "partner"):
        raise HTTPException(
            status_code=403,
            detail="Ask the person who set up this app to make a rescue code.",
        )
    hh = get_household(db)
    code = make_rescue_code()
    hh.recovery_key_hash = pwd.hash(normalize_rescue_code(code))
    db.commit()
    return {
        "ok": True,
        "rescue_code": code,
        "message": "Write this code down and keep it off this screen. It can reset a password without erasing the budget.",
    }


# ── Household ─────────────────────────────────────────────────────

@app.get("/api/household", response_model=HouseholdOut)
def household_get(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _household_out(get_household(db))


@app.patch("/api/household", response_model=HouseholdOut)
def household_update(
    body: HouseholdUpdate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    hh = get_household(db)
    if body.name is not None:
        hh.name = body.name
    if body.starting_balance is not None:
        hh.starting_balance = body.starting_balance
    if body.safety_threshold is not None:
        # 0 disables warnings; never store negative
        hh.safety_threshold = max(float(body.safety_threshold), 0.0)
    if body.onboarding_done is not None:
        hh.onboarding_done = bool(body.onboarding_done)
    if body.primary_age is not None:
        # 0 clears; otherwise clamp to a sensible adult/child range
        age = int(body.primary_age)
        hh.primary_age = None if age <= 0 else max(1, min(age, 120))
    if body.partner_age is not None:
        age = int(body.partner_age)
        hh.partner_age = None if age <= 0 else max(1, min(age, 120))
    if body.state is not None:
        st = (body.state or "").strip().upper()[:2]
        hh.state = st if st.isalpha() and len(st) == 2 else ""
    if body.idle_minutes is not None:
        hh.idle_minutes = _clamp_idle(body.idle_minutes)
    db.commit()
    db.refresh(hh)
    return _household_out(hh)


# ── Names dropdown ────────────────────────────────────────────────

@app.get("/api/names", response_model=list[ItemNameOut])
def list_names(user: User = Depends(current_user), db: Session = Depends(get_db)):
    hh = get_household(db)
    return (
        db.query(ItemName)
        .filter(ItemName.household_id == hh.id)
        .order_by(ItemName.name)
        .all()
    )


@app.post("/api/names", response_model=ItemNameOut)
def create_name(
    body: ItemNameCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    hh = get_household(db)
    name = body.name.strip()
    existing = (
        db.query(ItemName)
        .filter(ItemName.household_id == hh.id, ItemName.name == name)
        .first()
    )
    if existing:
        return existing
    row = ItemName(household_id=hh.id, name=name, kind=body.kind, is_default=False)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ── Budget items ──────────────────────────────────────────────────

@app.get("/api/items", response_model=list[BudgetItemOut])
def list_items(
    year: Optional[int] = None,
    month: Optional[int] = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    hh = get_household(db)
    q = db.query(BudgetItem).filter(BudgetItem.household_id == hh.id)
    if year and month:
        start = date(year, month, 1)
        end = date(year, month, monthrange(year, month)[1])
        q = q.filter(BudgetItem.due_date >= start, BudgetItem.due_date <= end)
    return q.order_by(BudgetItem.due_date, BudgetItem.id).all()


def _repeat_dates(start: date, frequency: str, months_ahead: int = 3) -> list[date]:
    """
    Build calendar dates for a recurring item.
    monthly = same day-of-month; biweekly = every 14 days; weekly = every 7 days.
    """
    if frequency in (None, "", "once") or not start:
        return [start]
    end = start + timedelta(days=max(months_ahead, 1) * 31)
    dates: list[date] = [start]
    if frequency == "monthly":
        y, m, day = start.year, start.month, start.day
        for _ in range(months_ahead):
            m += 1
            if m > 12:
                m = 1
                y += 1
            last = monthrange(y, m)[1]
            dates.append(date(y, m, min(day, last)))
        return dates
    if frequency == "yearly":
        y, m, day = start.year, start.month, start.day
        for n in range(1, 3):
            yy = y + n
            last = monthrange(yy, m)[1]
            dates.append(date(yy, m, min(day, last)))
        return dates
    step = 14 if frequency == "biweekly" else 7 if frequency == "weekly" else 0
    if step <= 0:
        return [start]
    cur = start + timedelta(days=step)
    while cur <= end:
        dates.append(cur)
        cur += timedelta(days=step)
    return dates


@app.post("/api/items", response_model=BudgetItemOut)
def create_item(
    body: BudgetItemCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    hh = get_household(db)
    is_income = body.is_income if body.item_type != "paycheck" else True
    name = body.name.strip()
    if body.item_type == "paycheck":
        is_income = True
    if body.item_type == "balance":
        # Absolute bank balance snapshot — not income/expense
        is_income = False
        name = name or "Bank balance"
    if body.item_type in ("bill", "estimate", "actual") and body.is_income is False:
        is_income = False

    sub_flag = body.is_subscription
    if sub_flag is None and looks_like_subscription(name, body.category or ""):
        sub_flag = True

    # Bank balance is always a one-time snapshot
    freq = "once" if body.item_type == "balance" else (body.frequency or "once")
    schedule = (
        [body.due_date]
        if body.item_type == "balance" or freq == "once"
        else _repeat_dates(body.due_date, freq, months_ahead=12)
    )

    first: BudgetItem | None = None
    for i, due in enumerate(schedule):
        item = BudgetItem(
            household_id=hh.id,
            name=name,
            item_type=body.item_type,
            amount=float(body.amount),
            is_income=is_income,
            due_date=due,
            frequency=freq,
            notes=body.notes or "",
            is_paid=bool(body.is_paid) if i == 0 else False,
            category=body.category or "",
            is_subscription=sub_flag,
        )
        db.add(item)
        if first is None:
            first = item

    if body.retain_name and name:
        exists = (
            db.query(ItemName)
            .filter(ItemName.household_id == hh.id, ItemName.name == name)
            .first()
        )
        if not exists:
            kind = (
                "income"
                if is_income or body.item_type == "paycheck"
                else (
                    "estimate"
                    if body.item_type == "estimate"
                    else ("general" if body.item_type == "balance" else "bill")
                )
            )
            db.add(
                ItemName(
                    household_id=hh.id,
                    name=name,
                    kind=kind,
                    is_default=False,
                )
            )

    db.commit()
    assert first is not None
    db.refresh(first)
    return first


_BILL_NAME_HINTS: list[tuple[str, str, str]] = [
    (r"pennymac", "Mortgage (PennyMac)", "bill"),
    (r"kmf", "Car payment (KMF)", "bill"),
    (r"sumter electric", "Electric (Sumter)", "bill"),
    (r"grovelan", "Water (Groveland)", "bill"),
    (r"verizon", "Verizon Wireless", "bill"),
    (r"state farm", "State Farm insurance", "bill"),
    (r"farm bureau", "Farm Bureau insurance", "bill"),
    (r"sunstrong", "Sunstrong", "bill"),
    (r"fid bkg|moneyline|fidelity", "Fidelity savings", "estimate"),
]


def _friendly_bill_name(raw: str) -> tuple[str, str]:
    text = (raw or "").strip()
    low = text.lower()
    for pat, name, kind in _BILL_NAME_HINTS:
        if re.search(pat, low):
            return name, kind
    # Strip bank junk from the original
    cleaned = re.split(r"\s+(?:PPD ID:|Web ID:|Tel ID:|Transaction#)", text, maxsplit=1)[0]
    cleaned = re.sub(r"\s+", " ", cleaned).strip()[:120] or "Monthly bill"
    return cleaned, "bill"


def _next_monthly_due(from_day: date, today: date | None = None) -> date:
    today = today or date.today()
    due = date(today.year, today.month, min(from_day.day, monthrange(today.year, today.month)[1]))
    if due < today:
        nxt = _add_months(due, 1, from_day.day)
        return nxt or due
    return due


@app.post("/api/items/{item_id}/to-monthly-bill")
def item_to_monthly_bill(
    item_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Turn a one-time bank line into a repeating monthly bill on the calendar."""
    hh = get_household(db)
    item = (
        db.query(BudgetItem)
        .filter(BudgetItem.id == item_id, BudgetItem.household_id == hh.id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if item.item_type == "balance":
        raise HTTPException(status_code=400, detail="Bank balance is not a bill.")
    name, kind = _friendly_bill_name(item.name)
    existing = (
        db.query(BudgetItem)
        .filter(
            BudgetItem.household_id == hh.id,
            BudgetItem.name == name,
            BudgetItem.frequency == "monthly",
            BudgetItem.item_type.in_(("bill", "estimate")),
        )
        .first()
    )
    if existing:
        return {
            "ok": True,
            "created": False,
            "item_id": existing.id,
            "message": f"{name} is already a monthly {existing.item_type} on the calendar.",
        }
    due = _next_monthly_due(item.due_date)
    schedule = _repeat_dates(due, "monthly", months_ahead=12)
    first = None
    for i, d in enumerate(schedule):
        row = BudgetItem(
            household_id=hh.id,
            name=name,
            item_type=kind,
            amount=float(item.amount),
            is_income=False,
            due_date=d,
            frequency="monthly",
            notes=f"From bank statement ({item.due_date.isoformat()} {float(item.amount):.2f})",
            category=item.category or "",
        )
        db.add(row)
        if first is None:
            first = row
    exists_name = (
        db.query(ItemName).filter(ItemName.household_id == hh.id, ItemName.name == name).first()
    )
    if not exists_name:
        db.add(ItemName(household_id=hh.id, name=name, kind=kind, is_default=False))
    db.commit()
    assert first is not None
    db.refresh(first)
    return {
        "ok": True,
        "created": True,
        "item_id": first.id,
        "due_date": due.isoformat(),
        "message": f"Added {name} ({float(item.amount):.2f}) as a monthly {kind} starting {due.isoformat()}.",
    }


@app.get("/api/recurring")
def list_recurring_series(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """One row per repeating bill/pay — for the Recurring tab."""
    hh = get_household(db)
    today = date.today()
    ensure_recurring_through(db, hh.id, today.year, today.month, extra_months=2)
    rows = (
        db.query(BudgetItem)
        .filter(
            BudgetItem.household_id == hh.id,
            BudgetItem.frequency.in_(RECURRING),
            BudgetItem.item_type.in_(REPEAT_TYPES),
        )
        .order_by(BudgetItem.due_date, BudgetItem.id)
        .all()
    )
    groups: dict[tuple, list[BudgetItem]] = {}
    for it in rows:
        groups.setdefault(series_key(it), []).append(it)
    out = []
    for _key, bunch in groups.items():
        bunch = sorted(bunch, key=lambda i: (i.due_date, i.id))
        this_month = [
            i
            for i in bunch
            if i.due_date.year == today.year and i.due_date.month == today.month
        ]
        upcoming = [i for i in bunch if i.due_date >= today]
        this_it = this_month[0] if this_month else None
        next_it = upcoming[0] if upcoming else bunch[-1]
        later = [i for i in bunch if this_it is None or i.due_date > this_it.due_date]
        typical = float((later[-1] if later else next_it).amount)
        out.append(
            {
                "id": (this_it or next_it).id,
                "this_month_id": this_it.id if this_it else None,
                "next_id": next_it.id,
                "name": next_it.name,
                "item_type": next_it.item_type,
                "frequency": next_it.frequency,
                "category": next_it.category or "",
                "is_income": bool(next_it.is_income),
                "due_day": next_it.due_date.day,
                "this_month_date": this_it.due_date.isoformat() if this_it else None,
                "this_month_amount": float(this_it.amount) if this_it else None,
                "this_month_paid": bool(this_it.is_paid) if this_it else False,
                "next_date": next_it.due_date.isoformat(),
                "typical_amount": typical,
                "count": len(bunch),
            }
        )
    out.sort(key=lambda r: ((r["due_day"] or 99), r["name"].lower()))
    return {"items": out, "today": today.isoformat()}


@app.patch("/api/items/{item_id}", response_model=BudgetItemOut)
def update_item(
    item_id: int,
    body: BudgetItemUpdate,
    scope: str = Query(default="this"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    hh = get_household(db)
    item = (
        db.query(BudgetItem)
        .filter(BudgetItem.id == item_id, BudgetItem.household_id == hh.id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    data = body.model_dump(exclude_unset=True)
    return update_series(db, hh.id, item, data, scope=scope)


@app.delete("/api/items/{item_id}")
def delete_item(
    item_id: int,
    scope: str = Query(default="this"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    hh = get_household(db)
    item = (
        db.query(BudgetItem)
        .filter(BudgetItem.id == item_id, BudgetItem.household_id == hh.id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return delete_series(db, hh.id, item, scope=scope)


@app.post("/api/items/{item_id}/toggle-paid", response_model=BudgetItemOut)
def toggle_paid(
    item_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Mark a bill/estimate paid or unpaid (affects actual running balance when paid)."""
    hh = get_household(db)
    item = (
        db.query(BudgetItem)
        .filter(BudgetItem.id == item_id, BudgetItem.household_id == hh.id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    item.is_paid = not bool(item.is_paid)
    # Paid bills that were estimates can stay as bill; actual path counts paid bills
    db.commit()
    db.refresh(item)
    return item


@app.post("/api/items/copy-month")
def copy_month(
    from_year: int = Query(...),
    from_month: int = Query(...),
    to_year: int = Query(...),
    to_month: int = Query(...),
    only_recurring: bool = Query(default=True),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """
    Copy last month's bills/estimates/paychecks into another month.
    only_recurring=True copies frequency weekly/biweekly/monthly (not once).
    Skips exact duplicates already in the target month.
    """
    hh = get_household(db)
    if not (1 <= from_month <= 12 and 1 <= to_month <= 12):
        raise HTTPException(status_code=400, detail="Invalid month")

    src_start = date(from_year, from_month, 1)
    src_end = date(from_year, from_month, monthrange(from_year, from_month)[1])
    tgt_start = date(to_year, to_month, 1)
    tgt_last = monthrange(to_year, to_month)[1]

    src_items = (
        db.query(BudgetItem)
        .filter(
            BudgetItem.household_id == hh.id,
            BudgetItem.due_date >= src_start,
            BudgetItem.due_date <= src_end,
            BudgetItem.item_type.in_(("bill", "estimate", "paycheck")),
        )
        .all()
    )
    if only_recurring:
        src_items = [i for i in src_items if i.frequency in ("weekly", "biweekly", "monthly", "yearly")]

    existing = (
        db.query(BudgetItem)
        .filter(
            BudgetItem.household_id == hh.id,
            BudgetItem.due_date >= tgt_start,
            BudgetItem.due_date <= date(to_year, to_month, tgt_last),
        )
        .all()
    )
    existing_keys = {
        (i.name, i.item_type, float(i.amount), i.due_date.day) for i in existing
    }

    created = 0
    for src in src_items:
        day = min(src.due_date.day, tgt_last)
        new_date = date(to_year, to_month, day)
        key = (src.name, src.item_type, float(src.amount), day)
        if key in existing_keys:
            continue
        db.add(
            BudgetItem(
                household_id=hh.id,
                name=src.name,
                item_type=src.item_type,
                amount=float(src.amount),
                is_income=bool(src.is_income),
                due_date=new_date,
                frequency=src.frequency,
                notes=(src.notes or "") + " · copied from prior month",
                is_paid=False,
                category=src.category or "",
            )
        )
        existing_keys.add(key)
        created += 1
    db.commit()
    return {
        "ok": True,
        "created": created,
        "message": f"Copied {created} recurring item(s) into {to_year}-{to_month:02d}.",
    }


@app.get("/api/onboarding")
def onboarding_status(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    hh = get_household(db)
    item_count = db.query(BudgetItem).filter(BudgetItem.household_id == hh.id).count()
    has_income = (
        db.query(BudgetItem)
        .filter(
            BudgetItem.household_id == hh.id,
            BudgetItem.is_income == True,  # noqa: E712
        )
        .first()
        is not None
    )
    has_housing = (
        db.query(BudgetItem)
        .filter(
            BudgetItem.household_id == hh.id,
            BudgetItem.is_income == False,  # noqa: E712
        )
        .first()
        is not None
    )
    steps = [
        {
            "id": "rename",
            "label": "Name your household",
            "done": bool(hh.name and hh.name.strip() and hh.name != "My Household"),
            "hint": "Tap Rename on Home (or Household settings).",
        },
        {
            "id": "safety",
            "label": "Set a safety amount",
            "done": float(getattr(hh, "safety_threshold", 0) or 0) > 0,
            "hint": "Household settings — warn when balance is low (example $300).",
        },
        {
            "id": "income",
            "label": "Add income (paycheck)",
            "done": has_income,
            "hint": "Money in/out, or import a statement / pay stub.",
        },
        {
            "id": "bills",
            "label": "Add at least one bill or expense",
            "done": has_housing,
            "hint": "Start with rent/housing or a regular bill.",
        },
        {
            "id": "profile",
            "label": "Age & state (taxes / benefits context)",
            "done": bool(
                getattr(hh, "primary_age", None)
                and (getattr(hh, "state", None) or "").strip()
            ),
            "hint": "Household settings — age and US state help later debt & benefits tips (not tax advice).",
        },
    ]
    done_count = sum(1 for s in steps if s["done"])
    return {
        "onboarding_done": bool(getattr(hh, "onboarding_done", False)),
        "item_count": item_count,
        "steps": steps,
        "complete": done_count == len(steps),
        "done_count": done_count,
        "total": len(steps),
        "primary_age": getattr(hh, "primary_age", None),
        "partner_age": getattr(hh, "partner_age", None),
        "state": getattr(hh, "state", "") or "",
    }


@app.get("/api/runtime")
def runtime_info(user: User = Depends(current_user), db: Session = Depends(get_db)):
    hh = get_household(db)
    st = backup_status()
    return {
        "in_docker": running_in_docker(),
        "idle_minutes": _idle_minutes(db),
        "has_recovery_key": bool(getattr(hh, "recovery_key_hash", "") or ""),
        **st,
    }


@app.get("/api/backup/status")
def backup_status_api(user: User = Depends(current_user)):
    return backup_status()


@app.post("/api/backup/local")
def backup_local_now(user: User = Depends(current_user)):
    path = save_local_backup()
    if not path:
        raise HTTPException(status_code=404, detail="Nothing to save yet.")
    st = backup_status()
    return {
        "ok": True,
        "file": path.name,
        "message": f"Saved a copy on this computer ({path.name}). Your live budget was not changed.",
        **st,
    }


@app.get("/api/backup")
def backup_download(user: User = Depends(current_user)):
    """Download the local SQLite database (budget data)."""
    from .db import DB_PATH

    if not DB_PATH.exists():
        raise HTTPException(status_code=404, detail="No database file yet")
    # Snapshot to avoid locked-file issues; delete temp after send
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    tmp = DB_PATH.parent / f"budget-backup-{stamp}.db"
    shutil.copy2(DB_PATH, tmp)

    def _cleanup() -> None:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass

    return FileResponse(
        path=str(tmp),
        filename=f"household-money-backup-{stamp}.db",
        media_type="application/octet-stream",
        background=BackgroundTask(_cleanup),
    )


@app.post("/api/restore")
async def restore_backup(
    file: UploadFile = File(...),
    user: User = Depends(current_user),
):
    """Replace local database with an uploaded .db backup. Use carefully."""
    from .db import DB_PATH, engine

    raw = await file.read()
    if len(raw) < 100 or raw[:15] != b"SQLite format 3":
        # SQLite header is "SQLite format 3\000"
        if not raw.startswith(b"SQLite format 3"):
            raise HTTPException(status_code=400, detail="File does not look like a budget backup (.db)")

    # Close pools and replace file
    engine.dispose()
    backup_old = DB_PATH.parent / f"budget-before-restore-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.db"
    if DB_PATH.exists():
        shutil.copy2(DB_PATH, backup_old)
    DB_PATH.write_bytes(raw)
    return {
        "ok": True,
        "message": "Backup restored. Sign out and sign in again (or restart the app).",
        "prior_copy": str(backup_old.name) if backup_old.exists() else None,
    }


# ── Calendar + metrics + upcoming ────────────────────────────────

def _signed_amount(item: BudgetItem) -> float:
    """Signed cash effect. balance type is handled separately (absolute set)."""
    if item.item_type == "balance":
        return 0.0
    return float(item.amount) if item.is_income else -float(item.amount)


def _apply_day_balances(
    day_items: list[BudgetItem],
    running_est: float,
    running_actual: float,
) -> tuple[float, float, float, float, bool]:
    """
    Estimate track: all planned + confirmed items; bank balance SETs both tracks.
    Actual track: only paycheck + actual after optional bank-balance anchor SET.
    """
    # Bank balance entries first — absolute set from that day forward
    anchors = [i for i in day_items if i.item_type == "balance"]
    anchored = False
    if anchors:
        # Latest / last entered wins if multiple same day
        running_est = float(anchors[-1].amount)
        running_actual = float(anchors[-1].amount)
        anchored = True

    delta_est = 0.0
    delta_actual = 0.0
    for i in day_items:
        if i.item_type == "balance":
            continue
        signed = _signed_amount(i)
        # Estimate / plan path: everything counts
        delta_est += signed
        # Actual path: only confirmed money movement
        if i.item_type in ("actual", "paycheck"):
            delta_actual += signed
        elif i.item_type == "bill" and i.is_paid:
            # Paid bill counts as confirmed outflow
            delta_actual += signed

    running_est += delta_est
    running_actual += delta_actual
    return running_est, running_actual, delta_est, delta_actual, anchored


@app.get("/api/calendar", response_model=CalendarResponse)
def calendar(
    year: int = Query(default=None),
    month: int = Query(default=None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    today = date.today()
    year = year or today.year
    month = month or today.month
    hh = get_household(db)
    ensure_recurring_through(db, hh.id, year, month, extra_months=2)

    start = date(year, month, 1)
    last = monthrange(year, month)[1]
    end = date(year, month, last)

    # Include any balance anchors before this month so actual track continues correctly
    prior_anchor = (
        db.query(BudgetItem)
        .filter(
            BudgetItem.household_id == hh.id,
            BudgetItem.item_type == "balance",
            BudgetItem.due_date < start,
        )
        .order_by(BudgetItem.due_date.desc(), BudgetItem.id.desc())
        .first()
    )

    # Rebuild actual path from last anchor (or household starting balance)
    if prior_anchor:
        running_actual = float(prior_anchor.amount)
        # Apply paycheck/actual/paid bills between anchor and month start
        mid_items = (
            db.query(BudgetItem)
            .filter(
                BudgetItem.household_id == hh.id,
                BudgetItem.due_date > prior_anchor.due_date,
                BudgetItem.due_date < start,
            )
            .order_by(BudgetItem.due_date, BudgetItem.id)
            .all()
        )
        for i in mid_items:
            if i.item_type == "balance":
                running_actual = float(i.amount)
            elif i.item_type in ("actual", "paycheck") or (
                i.item_type == "bill" and i.is_paid
            ):
                running_actual += _signed_amount(i)
        running_est = running_actual  # plan restarts from last known cash if anchored
        # Still layer planned items after anchor until month start onto est
        for i in mid_items:
            if i.item_type in ("bill", "estimate") and not (
                i.item_type == "bill" and i.is_paid
            ):
                running_est += _signed_amount(i)
    else:
        running_est = float(hh.starting_balance)
        running_actual = float(hh.starting_balance)

    items = (
        db.query(BudgetItem)
        .filter(
            BudgetItem.household_id == hh.id,
            BudgetItem.due_date >= start,
            BudgetItem.due_date <= end,
        )
        .order_by(BudgetItem.due_date, BudgetItem.id)
        .all()
    )
    by_day: dict[date, list[BudgetItem]] = {}
    for it in items:
        by_day.setdefault(it.due_date, []).append(it)

    threshold = float(getattr(hh, "safety_threshold", 0) or 0)
    days: list[CalendarDay] = []
    warn_est_count = 0
    warn_act_count = 0
    for day_n in range(1, last + 1):
        d = date(year, month, day_n)
        day_items = by_day.get(d, [])
        running_est, running_actual, delta_est, delta_actual, anchored = _apply_day_balances(
            day_items, running_est, running_actual
        )
        warn_est = threshold > 0 and running_est <= threshold
        warn_act = threshold > 0 and running_actual <= threshold
        if warn_est:
            warn_est_count += 1
        if warn_act:
            warn_act_count += 1
        days.append(
            CalendarDay(
                date=d,
                items=[BudgetItemOut.model_validate(i) for i in day_items],
                running_balance_est=round(running_est, 2),
                day_delta_est=round(delta_est, 2),
                running_balance_actual=round(running_actual, 2),
                day_delta_actual=round(delta_actual, 2),
                balance_anchored=anchored,
                warn_est=warn_est,
                warn_actual=warn_act,
                running_balance=round(running_est, 2),
                day_delta=round(delta_est, 2),
            )
        )

    return CalendarResponse(
        year=year,
        month=month,
        starting_balance=float(hh.starting_balance),
        ending_balance=round(running_est, 2),
        ending_balance_est=round(running_est, 2),
        ending_balance_actual=round(running_actual, 2),
        safety_threshold=threshold,
        warn_days_est=warn_est_count,
        warn_days_actual=warn_act_count,
        days=days,
    )


@app.get("/api/metrics", response_model=MetricsResponse)
def metrics(
    year: int = Query(default=None),
    month: int = Query(default=None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    today = date.today()
    year = year or today.year
    month = month or today.month
    hh = get_household(db)
    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])
    items = (
        db.query(BudgetItem)
        .filter(
            BudgetItem.household_id == hh.id,
            BudgetItem.due_date >= start,
            BudgetItem.due_date <= end,
        )
        .all()
    )

    income = sum(i.amount for i in items if i.is_income)
    expenses = sum(
        i.amount for i in items if not i.is_income and i.item_type != "balance"
    )
    estimates = sum(i.amount for i in items if i.item_type == "estimate")
    bills = sum(i.amount for i in items if i.item_type == "bill")
    actuals = sum(i.amount for i in items if i.item_type == "actual")
    paid = sum(
        i.amount
        for i in items
        if not i.is_income
        and i.item_type != "balance"
        and ((i.item_type == "bill" and i.is_paid) or i.item_type == "actual")
    )
    still_due = sum(
        i.amount
        for i in items
        if not i.is_income
        and (
            (i.item_type == "bill" and not i.is_paid) or i.item_type == "estimate"
        )
    )

    by_category: dict[str, float] = {}
    by_type: dict[str, float] = {}
    for i in items:
        if i.is_income or i.item_type == "balance":
            continue
        cat = i.category or i.name or "Other"
        by_category[cat] = by_category.get(cat, 0) + float(i.amount)
        by_type[i.item_type] = by_type.get(i.item_type, 0) + float(i.amount)

    return MetricsResponse(
        month_income=round(income, 2),
        month_expenses=round(expenses, 2),
        month_estimates=round(estimates, 2),
        month_bills=round(bills, 2),
        month_actuals=round(actuals, 2),
        month_paid=round(paid, 2),
        month_still_due=round(still_due, 2),
        net=round(income - expenses, 2),
        by_category={k: round(v, 2) for k, v in sorted(by_category.items(), key=lambda x: -x[1])},
        by_type={k: round(v, 2) for k, v in by_type.items()},
    )


@app.get("/api/subscriptions")
def list_subscriptions(user: User = Depends(current_user), db: Session = Depends(get_db)):
    hh = get_household(db)
    return summarize_subscriptions(db, hh.id)


@app.post("/api/subscriptions")
def create_subscription(
    body: SubscriptionCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Add a repeating streaming / Apple / software bill."""
    hh = get_household(db)
    name = body.name.strip()[:120]
    freq = body.frequency if body.frequency in ("monthly", "yearly", "weekly") else "monthly"
    ahead = 2 if freq == "yearly" else 12
    schedule = _repeat_dates(body.due_date, freq, months_ahead=ahead)
    first: BudgetItem | None = None
    for i, due in enumerate(schedule):
        item = BudgetItem(
            household_id=hh.id,
            name=name,
            item_type="bill",
            amount=float(body.amount),
            is_income=False,
            due_date=due,
            frequency=freq,
            notes=body.notes or "Subscription",
            category="Subscriptions",
            is_subscription=True,
        )
        db.add(item)
        if first is None:
            first = item
    exists = (
        db.query(ItemName)
        .filter(ItemName.household_id == hh.id, ItemName.name == name)
        .first()
    )
    if not exists:
        db.add(ItemName(household_id=hh.id, name=name, kind="bill", is_default=False))
    db.commit()
    assert first is not None
    db.refresh(first)
    return {
        "ok": True,
        "item_id": first.id,
        "created_dates": len(schedule),
        "message": f"Added {name} as a {freq} subscription.",
    }


@app.post("/api/subscriptions/ignore")
def ignore_subscription(
    name: str = Query(..., min_length=1),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Stop treating this name as a subscription (Apple.com/bill that is not a sub)."""
    hh = get_household(db)
    key = name.strip().lower()
    rows = (
        db.query(BudgetItem)
        .filter(BudgetItem.household_id == hh.id, BudgetItem.is_income.is_(False))
        .all()
    )
    updated = 0
    for row in rows:
        if (row.name or "").strip().lower() == key:
            row.is_subscription = False
            updated += 1
    db.commit()
    return {"ok": True, "updated": updated}


@app.get("/api/upcoming", response_model=UpcomingResponse)
def upcoming(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    hh = get_household(db)
    today = date.today()
    items = (
        db.query(BudgetItem)
        .filter(
            BudgetItem.household_id == hh.id,
            BudgetItem.due_date >= today,
            BudgetItem.is_paid == False,  # noqa: E712
            BudgetItem.item_type.in_(("bill", "estimate", "paycheck")),
        )
        .order_by(BudgetItem.due_date, BudgetItem.id)
        .limit(50)
        .all()
    )
    return UpcomingResponse(items=items)


# ── Goals ─────────────────────────────────────────────────────────

def _goal_out(g: Goal, db: Session | None = None) -> GoalOut:
    m = goal_metrics(g.target_amount, g.current_amount, g.target_date, g.monthly_contribution)
    saves = []
    saved_this_month = 0.0
    if db is not None:
        rows = (
            db.query(GoalSave)
            .filter(GoalSave.goal_id == g.id)
            .order_by(GoalSave.saved_on.desc(), GoalSave.id.desc())
            .limit(36)
            .all()
        )
        today = date.today()
        for s in rows:
            saves.append(
                {
                    "id": s.id,
                    "saved_on": s.saved_on,
                    "amount": float(s.amount),
                    "note": s.note or "",
                }
            )
            if s.saved_on.year == today.year and s.saved_on.month == today.month:
                saved_this_month += float(s.amount)
    return GoalOut(
        id=g.id,
        name=g.name,
        target_amount=g.target_amount,
        current_amount=g.current_amount,
        target_date=g.target_date,
        monthly_contribution=g.monthly_contribution,
        notes=g.notes or "",
        remaining=m["remaining"],
        percent=m["percent"],
        months_to_target=m["months_to_target"],
        suggested_monthly=m["suggested_monthly"],
        eta_date=m["eta_date"],
        on_track=m["on_track"],
        saved_this_month=round(saved_this_month, 2),
        saves=saves,
    )


@app.get("/api/goals", response_model=list[GoalOut])
def list_goals(user: User = Depends(current_user), db: Session = Depends(get_db)):
    hh = get_household(db)
    rows = db.query(Goal).filter(Goal.household_id == hh.id).order_by(Goal.id).all()
    return [_goal_out(g, db) for g in rows]


@app.post("/api/goals", response_model=GoalOut)
def create_goal(
    body: GoalCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    hh = get_household(db)
    g = Goal(
        household_id=hh.id,
        name=body.name.strip(),
        target_amount=float(body.target_amount),
        current_amount=float(body.current_amount or 0),
        target_date=body.target_date,
        monthly_contribution=float(body.monthly_contribution or 0),
        notes=body.notes or "",
    )
    db.add(g)
    db.flush()
    if float(g.monthly_contribution or 0) <= 0 and g.target_date:
        m = goal_metrics(g.target_amount, g.current_amount, g.target_date, 0)
        if m.get("suggested_monthly"):
            g.monthly_contribution = float(m["suggested_monthly"])
    db.commit()
    db.refresh(g)
    return _goal_out(g, db)


@app.patch("/api/goals/{goal_id}", response_model=GoalOut)
def update_goal(
    goal_id: int,
    body: GoalUpdate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    hh = get_household(db)
    g = db.query(Goal).filter(Goal.id == goal_id, Goal.household_id == hh.id).first()
    if not g:
        raise HTTPException(status_code=404, detail="Goal not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(g, k, v)
    db.commit()
    db.refresh(g)
    return _goal_out(g, db)


@app.post("/api/goals/{goal_id}/saves")
def log_goal_save(
    goal_id: int,
    body: GoalSaveCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Log 'I saved this much this month' and add it to the goal total."""
    hh = get_household(db)
    g = db.query(Goal).filter(Goal.id == goal_id, Goal.household_id == hh.id).first()
    if not g:
        raise HTTPException(status_code=404, detail="Goal not found")
    today = date.today()
    year = body.year or today.year
    month = body.month or today.month
    saved_on = date(year, month, 1)
    amt = round(float(body.amount), 2)
    db.add(
        GoalSave(
            household_id=hh.id,
            goal_id=g.id,
            saved_on=saved_on,
            amount=amt,
            note=(body.note or "")[:200],
        )
    )
    g.current_amount = round(float(g.current_amount or 0) + amt, 2)
    db.commit()
    db.refresh(g)
    return _goal_out(g, db)


@app.delete("/api/goals/{goal_id}")
def delete_goal(
    goal_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    hh = get_household(db)
    g = db.query(Goal).filter(Goal.id == goal_id, Goal.household_id == hh.id).first()
    if not g:
        raise HTTPException(status_code=404, detail="Goal not found")
    db.delete(g)
    db.commit()
    return {"ok": True}


def _plan_date(year: int, month: int) -> date:
    today = date.today()
    last = monthrange(year, month)[1]
    if today.year == year and today.month == month:
        return today
    return date(year, month, 1)


def _item_in_month(
    db: Session, household_id: int, name: str, year: int, month: int
) -> BudgetItem | None:
    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])
    return (
        db.query(BudgetItem)
        .filter(
            BudgetItem.household_id == household_id,
            BudgetItem.name == name,
            BudgetItem.due_date >= start,
            BudgetItem.due_date <= end,
        )
        .first()
    )


@app.post("/api/goals/{goal_id}/to-calendar")
def goal_to_calendar(
    goal_id: int,
    year: int = Query(default=None),
    month: int = Query(default=None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Put this month's goal savings on the calendar as an estimate."""
    today = date.today()
    year = year or today.year
    month = month or today.month
    hh = get_household(db)
    g = db.query(Goal).filter(Goal.id == goal_id, Goal.household_id == hh.id).first()
    if not g:
        raise HTTPException(status_code=404, detail="Goal not found")
    amount = float(g.monthly_contribution or 0)
    if amount <= 0:
        m = goal_metrics(g.target_amount, g.current_amount, g.target_date, g.monthly_contribution)
        amount = float(m.get("suggested_monthly") or 0)
    if amount <= 0:
        raise HTTPException(
            status_code=400,
            detail="Set a monthly savings amount on this goal first.",
        )
    name = f"Goal: {g.name.strip()}"[:120]
    existing = _item_in_month(db, hh.id, name, year, month)
    if existing:
        return {
            "ok": True,
            "created": False,
            "item_id": existing.id,
            "due_date": existing.due_date.isoformat(),
            "message": f"{name} is already on {existing.due_date.isoformat()}.",
        }
    due = _plan_date(year, month)
    item = BudgetItem(
        household_id=hh.id,
        name=name,
        item_type="estimate",
        amount=amount,
        is_income=False,
        due_date=due,
        frequency="once",
        notes="From Goals — this month's savings",
        category="Goals",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {
        "ok": True,
        "created": True,
        "item_id": item.id,
        "due_date": due.isoformat(),
        "message": f"Added {name} ({amount:.2f}) on {due.isoformat()}.",
    }


# ── Debts + paydown plan ──────────────────────────────────────────

def _debt_out(d: Debt, db: Session | None = None) -> DebtOut:
    txn_count = 0
    if db is not None:
        txn_count = (
            db.query(CardTransaction).filter(CardTransaction.debt_id == d.id).count()
        )
    return DebtOut(
        id=d.id,
        name=d.name,
        balance=float(d.balance or 0),
        apr=float(d.apr or 0),
        min_payment=float(d.min_payment or 0),
        notes=d.notes or "",
        last4=getattr(d, "last4", "") or "",
        due_date=getattr(d, "due_date", None),
        statement_date=getattr(d, "statement_date", None),
        last_interest=float(getattr(d, "last_interest", 0) or 0),
        kind=getattr(d, "kind", None) or "card",
        txn_count=txn_count,
    )


@app.get("/api/debts", response_model=list[DebtOut])
def list_debts(user: User = Depends(current_user), db: Session = Depends(get_db)):
    hh = get_household(db)
    rows = db.query(Debt).filter(Debt.household_id == hh.id).order_by(Debt.id).all()
    return [_debt_out(d, db) for d in rows]


@app.post("/api/debts", response_model=DebtOut)
def create_debt(
    body: DebtCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    hh = get_household(db)
    d = Debt(
        household_id=hh.id,
        name=body.name.strip(),
        balance=float(body.balance),
        apr=float(body.apr or 0),
        min_payment=float(body.min_payment or 0),
        notes=body.notes or "",
        last4=(body.last4 or "").strip()[-4:],
        kind=body.kind if body.kind in ("card", "loan") else "card",
        due_date=body.due_date,
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    if body.put_min_on_calendar and float(d.min_payment or 0) > 0:
        _put_card_min_on_calendar(db, hh, d)
    return _debt_out(d, db)


@app.patch("/api/debts/{debt_id}", response_model=DebtOut)
def update_debt(
    debt_id: int,
    body: DebtUpdate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    hh = get_household(db)
    d = db.query(Debt).filter(Debt.id == debt_id, Debt.household_id == hh.id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Debt not found")
    old_name = d.name
    data = body.model_dump(exclude_unset=True)
    if "last4" in data and data["last4"] is not None:
        data["last4"] = str(data["last4"]).strip()[-4:]
    for k, v in data.items():
        setattr(d, k, v)
    db.commit()
    db.refresh(d)
    _sync_card_min_bill(db, hh, d, old_name=old_name)
    return _debt_out(d, db)


@app.delete("/api/debts/{debt_id}")
def delete_debt(
    debt_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    hh = get_household(db)
    d = db.query(Debt).filter(Debt.id == debt_id, Debt.household_id == hh.id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Debt not found")
    db.delete(d)
    db.commit()
    return {"ok": True}


@app.post("/api/cards/preview")
async def cards_preview(
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Read a credit-card PDF. Does not save. Does not touch the calendar."""
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")
    try:
        parsed = parse_card_pdf(raw)
    except Exception as ex:
        raise HTTPException(status_code=400, detail=f"Could not read card PDF: {ex}") from ex
    hh = get_household(db)
    last4 = (parsed.get("summary") or {}).get("last4") or ""
    match = None
    if last4:
        match = (
            db.query(Debt)
            .filter(Debt.household_id == hh.id, Debt.last4 == last4)
            .first()
        )
    if match is None:
        name = (parsed.get("summary") or {}).get("card_name") or ""
        if name:
            match = (
                db.query(Debt)
                .filter(Debt.household_id == hh.id, Debt.name == name)
                .first()
            )
    parsed["matched_debt_id"] = match.id if match else None
    parsed["matched_debt_name"] = match.name if match else None
    parsed["matched_apr"] = float(match.apr or 0) if match else None
    parsed["matched_min_payment"] = float(match.min_payment or 0) if match else None
    parsed["filename"] = file.filename or "statement.pdf"
    return parsed


def _dedupe_named_monthlies(db: Session, household_id: int, name: str) -> None:
    """Keep one calendar copy per due date for a repeating bill name."""
    rows = (
        db.query(BudgetItem)
        .filter(BudgetItem.household_id == household_id, BudgetItem.name == name)
        .order_by(BudgetItem.due_date, BudgetItem.id)
        .all()
    )
    seen: set[date] = set()
    for row in rows:
        if row.due_date in seen:
            db.delete(row)
        else:
            seen.add(row.due_date)
    db.commit()


def _sync_card_min_bill(db: Session, hh: Household, debt: Debt, old_name: str | None = None) -> None:
    """Keep the calendar 'Card min' bill in sync when you rename or change autopay."""
    names = [f"Card min: {debt.name}"[:120]]
    if old_name and old_name != debt.name:
        names.append(f"Card min: {old_name}"[:120])
    rows = (
        db.query(BudgetItem)
        .filter(
            BudgetItem.household_id == hh.id,
            BudgetItem.name.in_(names),
        )
        .all()
    )
    if not rows:
        return
    new_name = f"Card min: {debt.name}"[:120]
    due_day = debt.due_date.day if debt.due_date else None
    for row in rows:
        row.name = new_name
        if debt.min_payment and float(debt.min_payment) > 0:
            row.amount = float(debt.min_payment)
        if due_day and row.due_date:
            last = monthrange(row.due_date.year, row.due_date.month)[1]
            row.due_date = date(row.due_date.year, row.due_date.month, min(due_day, last))
    db.commit()
    _dedupe_named_monthlies(db, hh.id, new_name)


def _put_card_min_on_calendar(db: Session, hh: Household, debt: Debt) -> dict:
    if not debt.min_payment or float(debt.min_payment) <= 0:
        return {"created": False, "message": "No minimum payment to put on the calendar."}
    due = debt.due_date or _plan_date(date.today().year, date.today().month)
    name = f"Card min: {debt.name}"[:120]
    year, month = due.year, due.month
    existing = _item_in_month(db, hh.id, name, year, month)
    if existing is None and (debt.last4 or ""):
        start = date(year, month, 1)
        end = date(year, month, monthrange(year, month)[1])
        existing = (
            db.query(BudgetItem)
            .filter(
                BudgetItem.household_id == hh.id,
                BudgetItem.due_date >= start,
                BudgetItem.due_date <= end,
                BudgetItem.name.like("Card min:%"),
                BudgetItem.name.like(f"%{debt.last4}%"),
            )
            .first()
        )
    if existing:
        existing.name = name
        existing.amount = float(debt.min_payment)
        existing.due_date = due
        existing.item_type = "bill"
        existing.frequency = "monthly"
        db.commit()
        _dedupe_named_monthlies(db, hh.id, name)
        return {
            "created": False,
            "item_id": existing.id,
            "message": f"Updated {name} on the calendar ({float(debt.min_payment):.2f}).",
        }
    item = BudgetItem(
        household_id=hh.id,
        name=name,
        item_type="bill",
        amount=float(debt.min_payment),
        is_income=False,
        due_date=due,
        frequency="monthly",
        notes=f"Minimum payment from card statement · due {due.isoformat()}",
        category="Debt",
        is_subscription=False,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    _dedupe_named_monthlies(db, hh.id, name)
    return {
        "created": True,
        "item_id": item.id,
        "message": f"Added {name} ({float(debt.min_payment):.2f}) as a monthly bill.",
    }


@app.post("/api/cards/apply")
def cards_apply(
    body: CardApplyRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Save statement totals onto a card (feeds Debt plan). Charges stay off the calendar."""
    hh = get_household(db)
    last4 = (body.last4 or "").strip()[-4:]
    debt = None
    if body.debt_id:
        debt = db.query(Debt).filter(Debt.id == body.debt_id, Debt.household_id == hh.id).first()
        if not debt:
            raise HTTPException(status_code=404, detail="Card not found")
    if debt is None and last4:
        debt = db.query(Debt).filter(Debt.household_id == hh.id, Debt.last4 == last4).first()
    if debt is None:
        debt = Debt(
            household_id=hh.id,
            name=(body.name or "Chase card").strip()[:120],
            balance=0.0,
            apr=0.0,
            min_payment=0.0,
            kind="card",
        )
        db.add(debt)
        db.flush()
    debt.name = (body.name or debt.name).strip()[:120]
    if last4:
        debt.last4 = last4
        if "…" not in debt.name and last4 not in debt.name:
            debt.name = f"{debt.name} …{last4}"[:120]
    debt.balance = float(body.new_balance)
    if body.apr and body.apr > 0:
        debt.apr = float(body.apr)
    if body.min_payment and body.min_payment >= 0:
        debt.min_payment = float(body.min_payment)
    debt.due_date = body.due_date
    debt.statement_date = body.statement_date
    debt.last_interest = float(body.last_interest or 0)
    debt.kind = "card"
    extra = f"Statement {body.statement_date.isoformat()}" if body.statement_date else "Card statement"
    debt.notes = extra[:500]

    added = 0
    existing_keys = {
        (t.txn_date.isoformat(), round(float(t.amount), 2), (t.description or "").strip().lower()[:80])
        for t in db.query(CardTransaction).filter(CardTransaction.debt_id == debt.id).all()
    }
    for row in body.transactions:
        key = (
            row.date.isoformat(),
            round(float(row.amount), 2),
            (row.description or "").strip().lower()[:80],
        )
        if key in existing_keys:
            continue
        db.add(
            CardTransaction(
                household_id=hh.id,
                debt_id=debt.id,
                txn_date=row.date,
                description=(row.description or "")[:200],
                amount=float(row.amount),
                is_credit=bool(row.is_credit),
                category=(row.category or "")[:64],
            )
        )
        existing_keys.add(key)
        added += 1
    db.commit()
    db.refresh(debt)

    cal_msg = ""
    if body.put_min_on_calendar:
        cal = _put_card_min_on_calendar(db, hh, debt)
        cal_msg = " " + cal.get("message", "")

    stored = (
        db.query(CardTransaction)
        .filter(CardTransaction.debt_id == debt.id)
        .order_by(CardTransaction.txn_date)
        .all()
    )
    recurring = find_recurring_charges(
        [
            {
                "date": t.txn_date.isoformat(),
                "description": t.description,
                "amount": t.amount,
                "is_credit": t.is_credit,
                "category": t.category,
            }
            for t in stored
        ]
    )
    return {
        "ok": True,
        "debt": _debt_out(debt, db),
        "added_transactions": added,
        "recurring": recurring,
        "message": (
            f"Saved {debt.name}: balance ${float(debt.balance):,.2f}, "
            f"APR {float(debt.apr):g}%, min ${float(debt.min_payment):,.2f}."
            f"{cal_msg} Charges stay on Cards — not on the calendar."
        ),
    }


@app.get("/api/cards/spend")
def card_spend(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Spending across every uploaded card statement (no bank login)."""
    hh = get_household(db)
    rows = (
        db.query(CardTransaction, Debt)
        .join(Debt, Debt.id == CardTransaction.debt_id)
        .filter(CardTransaction.household_id == hh.id)
        .all()
    )
    payload = []
    for t, d in rows:
        desc = t.description or ""
        cat = t.category or ""
        if not cat or cat in ("Other", "Water", "Fees"):
            cat = suggest_category(desc, bool(t.is_credit))
            if cat != (t.category or ""):
                t.category = cat
        payload.append(
            {
                "date": t.txn_date.isoformat() if t.txn_date else "",
                "description": desc,
                "amount": float(t.amount),
                "is_credit": bool(t.is_credit),
                "category": cat,
                "card_name": d.name,
                "last4": d.last4 or "",
            }
        )
    # Checking / debit from Import (Bank of America CSV, Chase PDF, etc.)
    actuals = (
        db.query(BudgetItem)
        .filter(
            BudgetItem.household_id == hh.id,
            BudgetItem.item_type == "actual",
            BudgetItem.is_income.is_(False),
        )
        .all()
    )
    for i in actuals:
        desc = i.name or ""
        cat = i.category or suggest_category(desc, False)
        payload.append(
            {
                "date": i.due_date.isoformat() if i.due_date else "",
                "description": desc,
                "amount": float(i.amount),
                "is_credit": False,
                "category": cat,
                "card_name": "Checking / bank",
                "last4": "",
            }
        )
    db.commit()
    return analyze_card_spend(payload)


@app.get("/api/cards")
def list_cards(user: User = Depends(current_user), db: Session = Depends(get_db)):
    hh = get_household(db)
    rows = (
        db.query(Debt)
        .filter(Debt.household_id == hh.id)
        .order_by(Debt.id)
        .all()
    )
    cards = []
    all_recurring = []
    for d in rows:
        txns = (
            db.query(CardTransaction)
            .filter(CardTransaction.debt_id == d.id)
            .order_by(CardTransaction.txn_date.desc())
            .all()
        )
        rec = find_recurring_charges(
            [
                {
                    "date": t.txn_date.isoformat(),
                    "description": t.description,
                    "amount": t.amount,
                    "is_credit": t.is_credit,
                    "category": t.category,
                }
                for t in txns
            ]
        )
        for r in rec:
            r["debt_id"] = d.id
            r["card_name"] = d.name
            r["hidden"] = False
        all_recurring.extend(rec)
        cards.append(
            {
                **_debt_out(d, db).model_dump(),
                "recent": [
                    {
                        "date": t.txn_date.isoformat(),
                        "description": t.description,
                        "amount": t.amount,
                        "is_credit": t.is_credit,
                        "category": t.category,
                    }
                    for t in txns[:12]
                ],
                "recurring": rec,
            }
        )
    marks = {
        (m.merchant_key or "").strip().upper(): (m.status or "ignore")
        for m in db.query(CardRecurringMark).filter(CardRecurringMark.household_id == hh.id).all()
    }
    cal_names = {
        (i.name or "")
        for i in db.query(BudgetItem)
        .filter(BudgetItem.household_id == hh.id, BudgetItem.name.like("Card: %"))
        .all()
    }
    for r in all_recurring:
        key = (r.get("key") or "").strip().upper()
        r["hidden"] = marks.get(key) == "ignore"
        r["on_calendar"] = f"Card: {r.get('merchant')}" in cal_names
    all_recurring.sort(key=lambda r: (-r.get("count", 0), -r.get("typical_amount", 0)))
    return {
        "cards": cards,
        "recurring": all_recurring,
        "total_balance": round(sum(float(c["balance"] or 0) for c in cards), 2),
        "total_min": round(sum(float(c["min_payment"] or 0) for c in cards), 2),
    }


@app.post("/api/cards/{debt_id}/min-to-calendar")
def card_min_to_calendar(
    debt_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    hh = get_household(db)
    d = db.query(Debt).filter(Debt.id == debt_id, Debt.household_id == hh.id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Card not found")
    return _put_card_min_on_calendar(db, hh, d)


@app.post("/api/cards/recurring/mark")
def mark_recurring(
    key: str = Query(..., min_length=1),
    status: str = Query(default="ignore"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Hide (ignore) or restore (watch) a spotted merchant."""
    hh = get_household(db)
    k = key.strip().upper()
    st = "watch" if (status or "").lower() == "watch" else "ignore"
    row = (
        db.query(CardRecurringMark)
        .filter(CardRecurringMark.household_id == hh.id, CardRecurringMark.merchant_key == k)
        .first()
    )
    if st == "watch":
        if row:
            db.delete(row)
            db.commit()
        return {"ok": True, "status": "watch"}
    if row:
        row.status = "ignore"
    else:
        db.add(CardRecurringMark(household_id=hh.id, merchant_key=k, status="ignore"))
    db.commit()
    return {"ok": True, "status": "ignore"}


@app.post("/api/cards/recurring/remove-calendar")
def recurring_remove_calendar(
    merchant: str = Query(..., min_length=1),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    hh = get_household(db)
    name = f"Card: {merchant.strip()}"[:120]
    rows = (
        db.query(BudgetItem)
        .filter(BudgetItem.household_id == hh.id, BudgetItem.name == name)
        .all()
    )
    n = 0
    for row in rows:
        db.delete(row)
        n += 1
    db.commit()
    return {"ok": True, "deleted": n, "message": f"Removed {name} from the calendar." if n else "Nothing to remove."}


@app.post("/api/cards/recurring/to-calendar")
def recurring_to_calendar(
    merchant: str = Query(..., min_length=1),
    amount: float = Query(..., gt=0),
    year: int = Query(default=None),
    month: int = Query(default=None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Put a spotted card recurring charge on the calendar as a monthly estimate."""
    today = date.today()
    year = year or today.year
    month = month or today.month
    hh = get_household(db)
    name = f"Card: {merchant.strip()}"[:120]
    existing = _item_in_month(db, hh.id, name, year, month)
    if existing:
        return {
            "ok": True,
            "created": False,
            "message": f"{name} is already on {existing.due_date.isoformat()}.",
        }
    due = _plan_date(year, month)
    item = BudgetItem(
        household_id=hh.id,
        name=name,
        item_type="estimate",
        amount=float(amount),
        is_income=False,
        due_date=due,
        frequency="monthly",
        notes="Spotted on a credit-card statement (recurring)",
        category="Subscriptions",
        is_subscription=True,
    )
    db.add(item)
    db.commit()
    return {
        "ok": True,
        "created": True,
        "due_date": due.isoformat(),
        "message": f"Added {name} ({float(amount):.2f}/mo) to the calendar.",
    }


@app.get("/api/debts/plans")
def list_debt_plan_presets(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """A few ready-made payoff scenarios using current card balances."""
    hh = get_household(db)
    rows = db.query(Debt).filter(Debt.household_id == hh.id).all()
    payload = [
        {
            "id": r.id,
            "name": r.name,
            "balance": r.balance,
            "apr": r.apr,
            "min_payment": r.min_payment,
        }
        for r in rows
        if float(r.balance or 0) > 0.005
    ]
    presets = [
        {
            "id": "mins",
            "title": "Minimums only",
            "blurb": "Pay only what you already send each month. Slowest; no extra.",
            "strategy": "avalanche",
            "extra_monthly": 0,
        },
        {
            "id": "av50",
            "title": "Avalanche + $50",
            "blurb": "Highest interest first, small extra. Gentle if money is tight.",
            "strategy": "avalanche",
            "extra_monthly": 50,
        },
        {
            "id": "av100",
            "title": "Avalanche + $100",
            "blurb": "Highest APR first. Usually the least interest overall.",
            "strategy": "avalanche",
            "extra_monthly": 100,
        },
        {
            "id": "av250",
            "title": "Avalanche + $250",
            "blurb": "Same order, more extra — faster once pay is steadier.",
            "strategy": "avalanche",
            "extra_monthly": 250,
        },
        {
            "id": "av500",
            "title": "Avalanche + $500",
            "blurb": "For when income is back. Hits high-APR cards hard.",
            "strategy": "avalanche",
            "extra_monthly": 500,
        },
        {
            "id": "sn100",
            "title": "Snowball + $100",
            "blurb": "Smallest balance first for quick wins, then roll that payment forward.",
            "strategy": "snowball",
            "extra_monthly": 100,
        },
        {
            "id": "sn250",
            "title": "Snowball + $250",
            "blurb": "Same small-balance first, with more extra each month.",
            "strategy": "snowball",
            "extra_monthly": 250,
        },
    ]
    out = []
    for p in presets:
        plan = simulate_debt_paydown(
            payload, strategy=p["strategy"], extra_monthly=p["extra_monthly"]
        )
        out.append(
            {
                **p,
                "months": plan.get("months") or 0,
                "debt_free_label": plan.get("debt_free_label") or "—",
                "total_interest": plan.get("total_interest") or 0,
                "monthly_budget": plan.get("monthly_budget") or 0,
                "payoff_order": (plan.get("payoff_order") or [])[:4],
            }
        )
    return {"plans": out, "card_count": len(payload)}


@app.post("/api/debts/plan", response_model=DebtPlanSummary)
def debt_plan(
    body: DebtPlanRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    hh = get_household(db)
    rows = db.query(Debt).filter(Debt.household_id == hh.id).all()
    payload = [
        {
            "id": r.id,
            "name": r.name,
            "balance": r.balance,
            "apr": r.apr,
            "min_payment": r.min_payment,
        }
        for r in rows
    ]
    plan = simulate_debt_paydown(
        payload, strategy=body.strategy, extra_monthly=body.extra_monthly
    )
    plan["compare"] = compare_strategies(payload, body.extra_monthly)
    plan["planning_notes"] = demographic_planning_notes(
        primary_age=getattr(hh, "primary_age", None),
        partner_age=getattr(hh, "partner_age", None),
        state=getattr(hh, "state", None),
        plan_months=plan.get("months"),
    )
    return DebtPlanSummary(**plan)


@app.post("/api/debts/extra-to-calendar")
def debt_extra_to_calendar(
    extra_monthly: float = Query(..., gt=0),
    year: int = Query(default=None),
    month: int = Query(default=None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Put this month's extra debt payment on the calendar as a bill."""
    today = date.today()
    year = year or today.year
    month = month or today.month
    hh = get_household(db)
    amount = round(float(extra_monthly), 2)
    name = "Debt extra payment"
    existing = _item_in_month(db, hh.id, name, year, month)
    if existing:
        return {
            "ok": True,
            "created": False,
            "item_id": existing.id,
            "due_date": existing.due_date.isoformat(),
            "message": f"{name} is already on {existing.due_date.isoformat()}.",
        }
    due = _plan_date(year, month)
    item = BudgetItem(
        household_id=hh.id,
        name=name,
        item_type="bill",
        amount=amount,
        is_income=False,
        due_date=due,
        frequency="once",
        notes="From Debt plan — extra beyond minimums",
        category="Debt",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {
        "ok": True,
        "created": True,
        "item_id": item.id,
        "due_date": due.isoformat(),
        "message": f"Added {name} ({amount:.2f}) on {due.isoformat()}.",
    }


# ── Investments (simple buckets) ──────────────────────────────────

def _inv_out(row: Investment) -> InvestmentOut:
    value = float(row.current_value or 0)
    basis = float(row.cost_basis or 0)
    gain = round(value - basis, 2) if basis > 0 else 0.0
    pct = round((gain / basis) * 100, 1) if basis > 0 else None
    return InvestmentOut(
        id=row.id,
        name=row.name,
        account_type=row.account_type,
        current_value=value,
        cost_basis=basis,
        monthly_contribution=float(row.monthly_contribution or 0),
        notes=row.notes or "",
        last_updated=row.last_updated,
        gain_loss=gain,
        gain_loss_pct=pct,
    )


@app.get("/api/investments", response_model=list[InvestmentOut])
def list_investments(user: User = Depends(current_user), db: Session = Depends(get_db)):
    hh = get_household(db)
    rows = (
        db.query(Investment)
        .filter(Investment.household_id == hh.id)
        .order_by(Investment.id)
        .all()
    )
    return [_inv_out(r) for r in rows]


@app.post("/api/investments", response_model=InvestmentOut)
def create_investment(
    body: InvestmentCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    hh = get_household(db)
    row = Investment(
        household_id=hh.id,
        name=body.name.strip(),
        account_type=body.account_type,
        current_value=float(body.current_value or 0),
        cost_basis=float(body.cost_basis or 0),
        monthly_contribution=float(body.monthly_contribution or 0),
        notes=body.notes or "",
        last_updated=date.today(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _inv_out(row)


@app.patch("/api/investments/{inv_id}", response_model=InvestmentOut)
def update_investment(
    inv_id: int,
    body: InvestmentUpdate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    hh = get_household(db)
    row = (
        db.query(Investment)
        .filter(Investment.id == inv_id, Investment.household_id == hh.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Investment not found")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(row, k, v)
    if "current_value" in data or "cost_basis" in data:
        row.last_updated = date.today()
    db.commit()
    db.refresh(row)
    return _inv_out(row)


@app.delete("/api/investments/{inv_id}")
def delete_investment(
    inv_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    hh = get_household(db)
    row = (
        db.query(Investment)
        .filter(Investment.id == inv_id, Investment.household_id == hh.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Investment not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


# ── Snapshot + household people ───────────────────────────────────

@app.get("/api/snapshot", response_model=SnapshotOut)
def snapshot(user: User = Depends(current_user), db: Session = Depends(get_db)):
    hh = get_household(db)

    # Cash = most recent bank-balance entry, else household starting balance
    anchor = (
        db.query(BudgetItem)
        .filter(BudgetItem.household_id == hh.id, BudgetItem.item_type == "balance")
        .order_by(BudgetItem.due_date.desc(), BudgetItem.id.desc())
        .first()
    )
    cash = float(anchor.amount) if anchor else float(hh.starting_balance)
    cash_as_of = anchor.due_date if anchor else None

    invs = db.query(Investment).filter(Investment.household_id == hh.id).all()
    debts = db.query(Debt).filter(Debt.household_id == hh.id).all()
    goals = db.query(Goal).filter(Goal.household_id == hh.id).all()
    members = db.query(User).order_by(User.id).all()

    inv_total = sum(float(i.current_value or 0) for i in invs)
    debt_total = sum(float(d.balance or 0) for d in debts)
    goals_saved = sum(float(g.current_amount or 0) for g in goals)
    goals_target = sum(float(g.target_amount or 0) for g in goals)
    monthly_inv = sum(float(i.monthly_contribution or 0) for i in invs)

    return SnapshotOut(
        household_name=hh.name,
        cash=round(cash, 2),
        cash_as_of=cash_as_of,
        investments_total=round(inv_total, 2),
        debts_total=round(debt_total, 2),
        goals_saved=round(goals_saved, 2),
        goals_target=round(goals_target, 2),
        net_worth=round(cash + inv_total - debt_total, 2),
        monthly_invest_contrib=round(monthly_inv, 2),
        members=[
            {
                "id": m.id,
                "username": m.username,
                "display_name": m.display_name or m.username,
                "role": m.role,
            }
            for m in members
        ],
        goal_count=len(goals),
        debt_count=len(debts),
        investment_count=len(invs),
    )


ALLOWED_ROLES = {"owner", "partner", "member", "viewer", "admin"}  # admin legacy alias


def _role_label(role: str) -> str:
    return {
        "owner": "Owner (full control)",
        "partner": "Partner (full access — spouse/co-parent)",
        "admin": "Partner (full access)",
        "member": "Member (edit money, not people)",
        "viewer": "Viewer (look only)",
    }.get(role, role)


@app.get("/api/members", response_model=list[MemberOut])
def list_members(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(User).order_by(User.id).all()
    return [
        MemberOut(
            id=r.id,
            username=r.username,
            display_name=r.display_name or r.username,
            role=r.role,
            must_change_password=bool(getattr(r, "must_change_password", False)),
        )
        for r in rows
    ]


@app.post("/api/members", response_model=MemberOut)
def create_member(
    body: MemberCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Add another login on this local install (spouse, partner, helper)."""
    if user.role not in ("owner", "admin", "partner"):
        raise HTTPException(status_code=403, detail="Only owners/partners can add people")
    uname = body.username.strip().lower()
    if db.query(User).filter(User.username == uname).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    role = body.role if body.role in ALLOWED_ROLES else "partner"
    # Map legacy admin → partner for new accounts
    if role == "admin":
        role = "partner"
    row = User(
        username=uname,
        password_hash=pwd.hash(body.password),
        display_name=(body.display_name or body.username).strip(),
        role=role,
        must_change_password=bool(body.require_password_change),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return MemberOut(
        id=row.id,
        username=row.username,
        display_name=row.display_name,
        role=row.role,
        must_change_password=bool(row.must_change_password),
    )


@app.delete("/api/members/{member_id}")
def delete_member(
    member_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Remove a login from this local install."""
    if user.role not in ("owner", "admin", "partner"):
        raise HTTPException(status_code=403, detail="Only owners/partners can remove people")
    if member_id == user.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own login while signed in")

    target = db.get(User, member_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    # Keep at least one owner/admin so the household is not locked out
    owners = (
        db.query(User)
        .filter(User.role.in_(("owner", "admin")))
        .count()
    )
    if target.role in ("owner", "admin") and owners <= 1:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete the last owner account",
        )

    # Drop their sessions so they are signed out
    db.query(SessionToken).filter(SessionToken.user_id == target.id).delete()
    db.delete(target)
    db.commit()
    return {"ok": True, "deleted_id": member_id}


# ── Pay stubs (PDF) + job pay profiles ────────────────────────────

def _job_out(row: JobPay) -> JobPayOut:
    nxt: list[date] = []
    if row.last_pay_date:
        nxt = next_pay_dates(row.last_pay_date, row.frequency, count=6)
    return JobPayOut(
        id=row.id,
        employer=row.employer,
        employee_label=row.employee_label,
        frequency=row.frequency,
        gross_pay=float(row.gross_pay or 0),
        net_pay=float(row.net_pay or 0),
        last_pay_date=row.last_pay_date,
        monthly_net_estimate=float(row.monthly_net_estimate or 0),
        notes=row.notes or "",
        next_pay_dates=nxt,
    )


@app.post("/api/paystub/parse")
async def paystub_parse(
    file: UploadFile = File(...),
    user: User = Depends(current_user),
):
    """
    Parse a pay stub PDF locally (text extract + field heuristics).
    Does not save the PDF. Review fields before applying.
    """
    name = (file.filename or "").lower()
    if not (name.endswith(".pdf") or (file.content_type or "").endswith("pdf")):
        # still try if content looks like pdf
        pass
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")
    if not raw[:8].startswith(b"%PDF") and not name.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF pay stub")

    try:
        parsed = parse_paystub_pdf(raw)
    except Exception as ex:
        raise HTTPException(status_code=400, detail=f"Could not read PDF: {ex}") from ex

    return {
        "ok": True,
        "parsed": parsed.to_dict(),
        "message": (
            f"Parsed with {parsed.confidence} confidence. "
            "Check net pay and pay date before saving."
        ),
    }


@app.post("/api/paystub/apply")
def paystub_apply(
    body: PayStubApplyRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Create paycheck calendar items and/or save a job pay profile."""
    hh = get_household(db)
    created_items: list[int] = []
    job_id = None
    monthly = monthly_equivalent(body.net_pay, body.frequency) or 0.0

    name = (body.employer or "Paycheck").strip()[:120]
    if body.employee_label:
        name = f"{body.employee_label}: {name}"[:120]

    dates = [body.pay_date]
    if body.schedule_future > 0:
        more = next_pay_dates(body.pay_date, body.frequency, count=body.schedule_future + 1)
        dates = more  # includes pay_date

    if body.create_paycheck:
        for i, d in enumerate(dates):
            item = BudgetItem(
                household_id=hh.id,
                name=name if i == 0 else f"{name} (planned)",
                item_type="paycheck" if i == 0 else "paycheck",
                amount=float(body.net_pay),
                is_income=True,
                due_date=d,
                frequency=body.frequency if i == 0 else "once",
                notes=(body.notes or "")
                + (
                    f" Gross ${body.gross_pay:.2f}" if body.gross_pay else ""
                )
                + (f" · from pay stub" if i == 0 else " · scheduled from pay stub"),
                category="Income",
            )
            db.add(item)
            db.flush()
            created_items.append(item.id)

    if body.save_job_profile:
        job = JobPay(
            household_id=hh.id,
            employer=(body.employer or "").strip()[:120],
            employee_label=(body.employee_label or "").strip()[:120],
            frequency=body.frequency,
            gross_pay=float(body.gross_pay or 0),
            net_pay=float(body.net_pay),
            last_pay_date=body.pay_date,
            monthly_net_estimate=float(monthly),
            notes=body.notes or "From pay stub",
            updated_at=datetime.utcnow(),
        )
        db.add(job)
        db.flush()
        job_id = job.id

    db.commit()
    return {
        "ok": True,
        "created_item_ids": created_items,
        "job_id": job_id,
        "monthly_net_estimate": monthly,
        "pay_dates": [d.isoformat() for d in dates],
        "message": (
            f"Saved {len(created_items)} paycheck(s)"
            + ("; job profile stored" if job_id else "")
            + f". ~${monthly:,.2f}/mo take-home estimate."
        ),
    }


@app.post("/api/jobs/{job_id}/to-calendar")
def job_to_calendar(
    job_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Put this job's net pay on the calendar (this month onward)."""
    hh = get_household(db)
    job = db.query(JobPay).filter(JobPay.id == job_id, JobPay.household_id == hh.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    freq = job.frequency if job.frequency in RECURRING else "biweekly"
    name = " · ".join(p for p in [(job.employee_label or "").strip(), (job.employer or "").strip()] if p)
    name = (name or "Paycheck")[:120]
    existing = (
        db.query(BudgetItem)
        .filter(
            BudgetItem.household_id == hh.id,
            BudgetItem.name == name,
            BudgetItem.item_type == "paycheck",
            BudgetItem.frequency == freq,
        )
        .first()
    )
    if existing:
        return {
            "ok": True,
            "created": False,
            "message": f"{name} is already on the calendar as {freq} pay.",
        }
    last = job.last_pay_date or date.today()
    start = next_after(last, freq) or (last + timedelta(days=14))
    month_start = date.today().replace(day=1)
    guard = 0
    while start < month_start and guard < 40:
        start = next_after(start, freq) or (start + timedelta(days=14))
        guard += 1
    schedule = _repeat_dates(start, freq, months_ahead=12)
    first = None
    for i, due in enumerate(schedule):
        row = BudgetItem(
            household_id=hh.id,
            name=name,
            item_type="paycheck",
            amount=float(job.net_pay),
            is_income=True,
            due_date=due,
            frequency=freq,
            notes=f"From job profile · {freq}",
            category="Income",
        )
        db.add(row)
        if first is None:
            first = row
    db.commit()
    return {
        "ok": True,
        "created": True,
        "count": len(schedule),
        "first_date": start.isoformat(),
        "message": (
            f"Added {name} ${float(job.net_pay):,.2f} {freq} starting {start.isoformat()} "
            f"({len(schedule)} paydays). Shows as income on Home."
        ),
    }


@app.get("/api/jobs", response_model=list[JobPayOut])
def list_jobs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    hh = get_household(db)
    rows = db.query(JobPay).filter(JobPay.household_id == hh.id).order_by(JobPay.id).all()
    return [_job_out(r) for r in rows]


@app.post("/api/jobs", response_model=JobPayOut)
def create_job(
    body: JobPayCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    hh = get_household(db)
    monthly = body.monthly_net_estimate or monthly_equivalent(body.net_pay, body.frequency) or 0
    row = JobPay(
        household_id=hh.id,
        employer=body.employer.strip()[:120],
        employee_label=body.employee_label.strip()[:120],
        frequency=body.frequency,
        gross_pay=float(body.gross_pay or 0),
        net_pay=float(body.net_pay or 0),
        last_pay_date=body.last_pay_date,
        monthly_net_estimate=float(monthly),
        notes=body.notes or "",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _job_out(row)


@app.delete("/api/jobs/{job_id}")
def delete_job(
    job_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    hh = get_household(db)
    row = db.query(JobPay).filter(JobPay.id == job_id, JobPay.household_id == hh.id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


# ── Statement CSV import (top US banks) ───────────────────────────

@app.get("/api/import/banks")
def list_import_banks(user: User = Depends(current_user)):
    """Supported bank import presets."""
    return {
        "banks": [
            {"id": k, "label": v}
            for k, v in BANK_PRESETS.items()
        ],
        "note": (
            "CSV for most banks. Chase monthly statements also support PDF "
            "(text PDFs from online banking). Always Preview before import."
        ),
    }


@app.post("/api/import/statement", response_model=StatementParseResponse)
async def import_statement(
    file: UploadFile = File(...),
    commit: bool = Query(default=False),
    bank: str = Query(default="auto"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """
    Parse bank activity CSV or Chase PDF statements.
    PDF path is local text extract only (no OCR).
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")

    fname = (file.filename or "").lower()
    is_pdf = raw[:4] == b"%PDF" or fname.endswith(".pdf")

    try:
        if is_pdf:
            parsed, detected, msg = parse_statement_pdf(raw, bank=bank)
        else:
            parsed, detected, msg = parse_bank_csv(raw, bank=bank)
    except Exception as ex:
        kind = "PDF" if is_pdf else "CSV"
        raise HTTPException(status_code=400, detail=f"Could not parse {kind}: {ex}") from ex

    hh_for_dup = get_household(db)
    # Existing keys for duplicate detection (date + amount + name)
    existing_items = db.query(BudgetItem).filter(BudgetItem.household_id == hh_for_dup.id).all()
    existing_keys = {
        (
            i.due_date.isoformat() if i.due_date else "",
            round(float(i.amount), 2),
            (i.name or "").strip().lower()[:80],
        )
        for i in existing_items
    }

    rows = []
    for r in parsed:
        cat = suggest_category(r.description, r.is_income)
        key = (
            r.date.isoformat() if r.date else "",
            round(float(r.amount), 2),
            (r.description or "").strip().lower()[:80],
        )
        is_dup = key in existing_keys and bool(r.date) and r.amount > 0
        rows.append(
            StatementRow(
                date=r.date,
                description=r.description,
                amount=r.amount,
                is_income=r.is_income,
                raw=r.raw,
                category=cat,
                # Default: select non-duplicates
                selected=not is_dup,
                possible_duplicate=is_dup,
            )
        )
    skipped = sum(1 for r in rows if not r.date or r.amount <= 0)
    dup_count = sum(1 for r in rows if r.possible_duplicate)

    first_date = None
    last_date = None
    dated = [r for r in rows if r.date and r.amount > 0]
    if dated:
        first_date = min(r.date for r in dated)  # type: ignore[arg-type]
        last_date = max(r.date for r in dated)  # type: ignore[arg-type]

    # Legacy commit=true still works (imports everything dated). Prefer /api/import/commit for selection.
    imported = 0
    if commit:
        hh = get_household(db)
        label = BANK_PRESETS.get(detected, detected)
        fmt = "PDF" if is_pdf else "CSV"
        for r in dated:
            item_type = "paycheck" if r.is_income else "actual"
            db.add(
                BudgetItem(
                    household_id=hh.id,
                    name=r.description[:120],
                    item_type=item_type,
                    amount=r.amount,
                    is_income=r.is_income,
                    due_date=r.date,
                    frequency="once",
                    notes=f"Imported ({label} {fmt})",
                    category=r.category or ("Income" if r.is_income else "Other"),
                    is_subscription=(
                        True
                        if (r.category or "") == "Subscriptions"
                        or looks_like_subscription(r.description, r.category or "")
                        else None
                    ),
                )
            )
            imported += 1
        db.commit()

    bank_label = BANK_PRESETS.get(detected, detected)
    req_bank = (bank or "").lower()
    if req_bank == "chase_credit":
        bank_label = "Chase credit card"
    elif is_pdf and detected == "chase":
        bank_label = "Chase checking PDF"
    if commit:
        if imported:
            range_txt = ""
            if first_date and last_date:
                range_txt = f" ({first_date.isoformat()} → {last_date.isoformat()})"
            suffix = (
                f" — SAVED {imported} transaction(s){range_txt}. "
                "Open Home and use the month arrows to that period if you do not see them."
            )
        else:
            suffix = " — nothing saved (rows missing dates or amounts)"
    else:
        suffix = (
            " — preview only. Check the rows you want, set a category bucket, "
            "then click Import selected."
        )
    if skipped:
        suffix += f"; {skipped} row(s) missing date/amount cannot be saved"
    if dup_count:
        suffix += (
            f"; {dup_count} possible duplicate(s) unchecked "
            "(same date + amount + name already in your budget)"
        )
    if not rows:
        suffix += " — no transactions found"
    return StatementParseResponse(
        rows=rows[:400],
        imported=imported,
        message=msg + suffix,
        bank=detected,
        bank_label=bank_label,
        skipped=skipped,
        first_date=first_date,
        last_date=last_date,
        categories=list(IMPORT_CATEGORIES),
    )


@app.post("/api/import/commit", response_model=ImportCommitResponse)
def import_commit(
    body: ImportCommitRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Save only the rows the user selected/categorized in the Import preview."""
    if not body.rows:
        raise HTTPException(status_code=400, detail="No rows selected to import")

    hh = get_household(db)
    imported = 0
    dates: list = []
    label = (body.bank_label or "Import").strip()[:80]

    for r in body.rows:
        if r.amount <= 0:
            continue
        is_income = bool(r.is_income) or r.category == "Income"
        item_type = r.item_type if r.item_type in ("actual", "paycheck", "bill", "estimate") else "actual"
        if is_income and item_type == "actual":
            item_type = "paycheck"
        if not is_income and item_type == "paycheck":
            item_type = "actual"
        cat = (r.category or "").strip() or ("Income" if is_income else "Other")
        if cat not in IMPORT_CATEGORIES:
            cat = "Other" if not is_income else "Income"

        src = (getattr(r, "source", None) or "").strip()
        note = f"Imported ({src})" if src else f"Imported ({label})"
        db.add(
            BudgetItem(
                household_id=hh.id,
                name=r.description.strip()[:120],
                item_type=item_type,
                amount=float(r.amount),
                is_income=is_income,
                due_date=r.date,
                frequency="once",
                notes=note[:500],
                category=cat,
                is_subscription=(
                    True
                    if cat == "Subscriptions" or looks_like_subscription(r.description.strip(), cat)
                    else None
                ),
            )
        )
        dates.append(r.date)
        imported += 1

    if imported == 0:
        raise HTTPException(status_code=400, detail="No valid rows to import")

    debts_created = 0
    debts_updated = 0
    for dlink in body.debts or []:
        name = dlink.name.strip()[:120]
        if not name:
            continue
        # Only create/update if user provided something useful for paydown
        if dlink.apr <= 0 and dlink.balance <= 0 and dlink.min_payment <= 0:
            continue

        existing = (
            db.query(Debt)
            .filter(Debt.household_id == hh.id, Debt.name == name)
            .first()
        )
        if existing and dlink.update_existing:
            if dlink.apr > 0:
                existing.apr = float(dlink.apr)
            if dlink.balance > 0:
                existing.balance = float(dlink.balance)
            if dlink.min_payment > 0:
                existing.min_payment = float(dlink.min_payment)
            note = (existing.notes or "").strip()
            tag = "APR from import"
            if tag not in note:
                existing.notes = (note + f" · {tag}").strip(" ·")
            debts_updated += 1
        elif not existing:
            # Need at least a balance or min payment for a useful debt row;
            # APR alone still creates a stub they can finish in Debt plan.
            bal = float(dlink.balance) if dlink.balance > 0 else 0.01
            db.add(
                Debt(
                    household_id=hh.id,
                    name=name,
                    balance=bal,
                    apr=float(dlink.apr or 0),
                    min_payment=float(dlink.min_payment or 0),
                    notes="From statement import — set balance/min payment if needed for paydown.",
                )
            )
            debts_created += 1

    db.commit()
    first_date = min(dates)
    last_date = max(dates)
    extra = ""
    if debts_created or debts_updated:
        parts = []
        if debts_created:
            parts.append(f"{debts_created} card(s) added to Debt plan")
        if debts_updated:
            parts.append(f"{debts_updated} card(s) updated (APR/balance)")
        extra = " " + "; ".join(parts) + "."
    return ImportCommitResponse(
        imported=imported,
        first_date=first_date,
        last_date=last_date,
        debts_created=debts_created,
        debts_updated=debts_updated,
        message=(
            f"Saved {imported} selected transaction(s) "
            f"({first_date.isoformat()} → {last_date.isoformat()})."
            f"{extra}"
        ),
    )


# ── Static frontend ───────────────────────────────────────────────

if BRAND.exists():
    app.mount("/brand", StaticFiles(directory=str(BRAND)), name="brand")

if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")


@app.get("/")
def index():
    index_path = FRONTEND / "index.html"
    if not index_path.exists():
        return {"message": "Frontend missing", "path": str(index_path)}
    # Avoid browsers keeping an old Import page after update.bat
    return FileResponse(
        index_path,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/api/version")
def app_version():
    ver = read_local_version()
    return {
        "version": ver,
        "chase_pdf_import": (ROOT / "backend" / "app" / "bank_pdf.py").exists(),
    }


def _can_update(user: User) -> bool:
    return user.role in ("owner", "admin", "partner")


@app.get("/api/update/status")
def update_status(user: User = Depends(current_user)):
    """Plain-language status for the Household settings Update button."""
    current = read_local_version()
    latest = None
    check_ok = True
    check_error = ""
    try:
        latest = fetch_latest_version()
    except Exception as exc:
        check_ok = False
        check_error = str(exc) or "Could not check for a newer version."

    available = bool(latest and is_newer(latest, current))
    if not check_ok:
        message = (
            "Could not check for a newer version. "
            "This computer needs internet, then tap Check again."
        )
    elif available:
        message = (
            f"A newer version is ready ({latest}). "
            "Your bills, passwords, and budget stay on this computer."
        )
    else:
        message = f"You're all set. This computer already has the latest version ({current})."

    return {
        "current": current,
        "latest": latest,
        "update_available": available,
        "can_update": _can_update(user),
        "in_docker": running_in_docker(),
        "check_ok": check_ok,
        "check_error": check_error,
        "message": message,
    }


@app.post("/api/update/apply")
def update_apply(user: User = Depends(current_user)):
    """Download the official app and replace program files. Keeps the data folder."""
    if not _can_update(user):
        raise HTTPException(
            status_code=403,
            detail="Ask the person who set up this app to run the update.",
        )
    current = read_local_version()
    try:
        latest = fetch_latest_version()
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Could not reach the update. Check internet on this computer, then try again.",
        )
    if not is_newer(latest, current):
        return {
            "ok": True,
            "updated": False,
            "version": current,
            "restarting": False,
            "message": f"You're already on the latest version ({current}). Nothing to do.",
        }
    try:
        new_ver = apply_update()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="The update did not finish. Nothing was erased. Try again in a minute.",
        )

    schedule_restart(1.8)
    return {
        "ok": True,
        "updated": True,
        "version": new_ver or latest,
        "restarting": True,
        "message": (
            "Update installed. Please wait — this page will come back by itself. "
            "Your money data was not changed."
        ),
    }
