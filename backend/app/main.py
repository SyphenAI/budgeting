from __future__ import annotations

import csv
import io
import secrets
from calendar import monthrange
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .db import Base, engine, get_db, migrate_sqlite
from .models import (
    BudgetItem,
    Debt,
    Goal,
    Household,
    Investment,
    ItemName,
    JobPay,
    SessionToken,
    User,
)
from .paystub import monthly_equivalent, next_pay_dates, parse_paystub_pdf
from .planning import compare_strategies, goal_metrics, simulate_debt_paydown
from .schemas import (
    BudgetItemCreate,
    BudgetItemOut,
    BudgetItemUpdate,
    CalendarDay,
    CalendarResponse,
    DebtCreate,
    DebtOut,
    DebtPlanRequest,
    DebtPlanSummary,
    DebtUpdate,
    GoalCreate,
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
    PayStubApplyRequest,
    SnapshotOut,
    StatementParseResponse,
    StatementRow,
    UpcomingResponse,
)
from .bank_import import BANK_PRESETS, parse_bank_csv
from .seed import seed_if_empty

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Local shared-PC safety: expire sessions after idle (minutes)
IDLE_TIMEOUT_MINUTES = 10

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
BRAND = ROOT / "brand"

app = FastAPI(title="Family Budget", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    migrate_sqlite()
    db = next(get_db())
    try:
        seed_if_empty(db)
    finally:
        db.close()


def current_user(
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
    idle_seconds = (now - last).total_seconds()
    if idle_seconds > IDLE_TIMEOUT_MINUTES * 60:
        db.delete(row)
        db.commit()
        raise HTTPException(
            status_code=401,
            detail=f"Signed out after {IDLE_TIMEOUT_MINUTES} minutes idle",
        )

    row.last_seen = now
    db.commit()

    user = db.get(User, row.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def get_household(db: Session) -> Household:
    hh = db.query(Household).first()
    if not hh:
        raise HTTPException(status_code=500, detail="No household configured")
    return hh


# ── Auth ──────────────────────────────────────────────────────────

@app.post("/api/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username.strip().lower()).first()
    # usernames stored lowercase-ish; also try exact
    if not user:
        user = db.query(User).filter(User.username == body.username.strip()).first()
    if not user or not pwd.verify(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Wrong username or password")
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
def me(user: User = Depends(current_user)):
    return {
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "must_change_password": bool(getattr(user, "must_change_password", False)),
    }


@app.post("/api/me/password")
def change_password(
    body: PasswordChangeRequest,
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
    db.commit()
    return {"ok": True, "must_change_password": False}


# ── Household ─────────────────────────────────────────────────────

@app.get("/api/household", response_model=HouseholdOut)
def household_get(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return get_household(db)


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
    db.commit()
    db.refresh(hh)
    return hh


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


@app.post("/api/items", response_model=BudgetItemOut)
def create_item(
    body: BudgetItemCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    hh = get_household(db)
    item = BudgetItem(
        household_id=hh.id,
        name=body.name.strip(),
        item_type=body.item_type,
        amount=float(body.amount),
        is_income=body.is_income if body.item_type != "paycheck" else True,
        due_date=body.due_date,
        frequency=body.frequency,
        notes=body.notes or "",
        is_paid=body.is_paid,
        category=body.category or "",
    )
    if body.item_type == "paycheck":
        item.is_income = True
    if body.item_type == "balance":
        # Absolute bank balance snapshot — not income/expense
        item.is_income = False
        item.name = item.name or "Bank balance"
    if body.item_type in ("bill", "estimate", "actual") and body.is_income is False:
        item.is_income = False

    db.add(item)

    if body.retain_name:
        exists = (
            db.query(ItemName)
            .filter(ItemName.household_id == hh.id, ItemName.name == item.name)
            .first()
        )
        if not exists:
            kind = (
                "income"
                if item.is_income or body.item_type == "paycheck"
                else (
                    "estimate"
                    if body.item_type == "estimate"
                    else ("general" if body.item_type == "balance" else "bill")
                )
            )
            db.add(
                ItemName(
                    household_id=hh.id,
                    name=item.name,
                    kind=kind,
                    is_default=False,
                )
            )

    db.commit()
    db.refresh(item)
    return item


@app.patch("/api/items/{item_id}", response_model=BudgetItemOut)
def update_item(
    item_id: int,
    body: BudgetItemUpdate,
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
    for k, v in data.items():
        setattr(item, k, v)
    if item.item_type == "paycheck":
        item.is_income = True
    db.commit()
    db.refresh(item)
    return item


@app.delete("/api/items/{item_id}")
def delete_item(
    item_id: int,
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
    db.delete(item)
    db.commit()
    return {"ok": True}


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

    days: list[CalendarDay] = []
    for day_n in range(1, last + 1):
        d = date(year, month, day_n)
        day_items = by_day.get(d, [])
        running_est, running_actual, delta_est, delta_actual, anchored = _apply_day_balances(
            day_items, running_est, running_actual
        )
        days.append(
            CalendarDay(
                date=d,
                items=[BudgetItemOut.model_validate(i) for i in day_items],
                running_balance_est=round(running_est, 2),
                day_delta_est=round(delta_est, 2),
                running_balance_actual=round(running_actual, 2),
                day_delta_actual=round(delta_actual, 2),
                balance_anchored=anchored,
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
    expenses = sum(i.amount for i in items if not i.is_income)
    estimates = sum(i.amount for i in items if i.item_type == "estimate")
    bills = sum(i.amount for i in items if i.item_type == "bill")
    actuals = sum(i.amount for i in items if i.item_type == "actual")

    by_category: dict[str, float] = {}
    by_type: dict[str, float] = {}
    for i in items:
        if i.is_income:
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
        net=round(income - expenses, 2),
        by_category={k: round(v, 2) for k, v in sorted(by_category.items(), key=lambda x: -x[1])},
        by_type={k: round(v, 2) for k, v in by_type.items()},
    )


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
        )
        .order_by(BudgetItem.due_date, BudgetItem.id)
        .limit(50)
        .all()
    )
    return UpcomingResponse(items=items)


# ── Goals ─────────────────────────────────────────────────────────

def _goal_out(g: Goal) -> GoalOut:
    m = goal_metrics(g.target_amount, g.current_amount, g.target_date, g.monthly_contribution)
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
    )


@app.get("/api/goals", response_model=list[GoalOut])
def list_goals(user: User = Depends(current_user), db: Session = Depends(get_db)):
    hh = get_household(db)
    rows = db.query(Goal).filter(Goal.household_id == hh.id).order_by(Goal.id).all()
    return [_goal_out(g) for g in rows]


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
    db.commit()
    db.refresh(g)
    return _goal_out(g)


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
    return _goal_out(g)


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


# ── Debts + paydown plan ──────────────────────────────────────────

@app.get("/api/debts", response_model=list[DebtOut])
def list_debts(user: User = Depends(current_user), db: Session = Depends(get_db)):
    hh = get_household(db)
    return db.query(Debt).filter(Debt.household_id == hh.id).order_by(Debt.id).all()


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
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


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
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(d, k, v)
    db.commit()
    db.refresh(d)
    return d


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
    return DebtPlanSummary(**plan)


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
    """Supported bank CSV presets for the import UI."""
    return {
        "banks": [
            {"id": k, "label": v}
            for k, v in BANK_PRESETS.items()
        ],
        "note": "CSV activity export only — not PDF statements. Auto-detect works for most files.",
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
    Parse bank activity CSV exports.
    Built for: Chase, Bank of America, Wells Fargo, Citi, U.S. Bank (+ generic/auto).
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")

    try:
        parsed, detected, msg = parse_bank_csv(raw, bank=bank)
    except Exception as ex:
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {ex}") from ex

    rows = [
        StatementRow(
            date=r.date,
            description=r.description,
            amount=r.amount,
            is_income=r.is_income,
            raw=r.raw,
        )
        for r in parsed
    ]
    skipped = sum(1 for r in rows if not r.date or r.amount <= 0)

    imported = 0
    if commit:
        hh = get_household(db)
        label = BANK_PRESETS.get(detected, detected)
        for r in rows:
            if not r.date or r.amount <= 0:
                continue
            db.add(
                BudgetItem(
                    household_id=hh.id,
                    name=r.description[:120],
                    item_type="actual",
                    amount=r.amount,
                    is_income=r.is_income,
                    due_date=r.date,
                    frequency="once",
                    notes=f"Imported ({label})",
                    category="Imported",
                )
            )
            imported += 1
        db.commit()

    bank_label = BANK_PRESETS.get(detected, detected)
    suffix = f"; imported {imported}" if commit else " — preview only (not saved yet)"
    if skipped:
        suffix += f"; {skipped} row(s) missing date/amount skipped on save"
    return StatementParseResponse(
        rows=rows[:300],
        imported=imported,
        message=msg + suffix,
        bank=detected,
        bank_label=bank_label,
        skipped=skipped,
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
    return FileResponse(index_path)
