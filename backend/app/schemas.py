from __future__ import annotations

from datetime import date as Date
from typing import Literal, Optional

from pydantic import BaseModel, Field


ItemType = Literal["bill", "estimate", "paycheck", "actual", "balance"]
Frequency = Literal["once", "weekly", "biweekly", "monthly"]


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    display_name: str
    username: str
    role: str
    must_change_password: bool = False


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=4, max_length=128)


class HouseholdOut(BaseModel):
    id: int
    name: str
    starting_balance: float
    safety_threshold: float = 0.0
    onboarding_done: bool = False
    currency: str

    class Config:
        from_attributes = True


class HouseholdUpdate(BaseModel):
    name: Optional[str] = None
    starting_balance: Optional[float] = None
    safety_threshold: Optional[float] = None
    onboarding_done: Optional[bool] = None


class ItemNameOut(BaseModel):
    id: int
    name: str
    kind: str
    is_default: bool

    class Config:
        from_attributes = True


class ItemNameCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = "general"


class BudgetItemOut(BaseModel):
    id: int
    name: str
    item_type: str
    amount: float
    is_income: bool
    due_date: Date
    frequency: str
    notes: str
    is_paid: bool
    category: str

    class Config:
        from_attributes = True


class BudgetItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    item_type: ItemType = "bill"
    amount: float = Field(gt=0)
    is_income: bool = False
    due_date: Date
    frequency: Frequency = "once"
    notes: str = ""
    is_paid: bool = False
    category: str = ""
    retain_name: bool = True


class BudgetItemUpdate(BaseModel):
    name: Optional[str] = None
    item_type: Optional[ItemType] = None
    amount: Optional[float] = None
    is_income: Optional[bool] = None
    due_date: Optional[Date] = None
    frequency: Optional[Frequency] = None
    notes: Optional[str] = None
    is_paid: Optional[bool] = None
    category: Optional[str] = None


class CalendarDay(BaseModel):
    date: Date
    items: list[BudgetItemOut]
    # Planned path (bills + estimates + pay + actuals); orange in UI
    running_balance_est: float
    day_delta_est: float
    # Confirmed path (bank balance anchors + paychecks + actuals); green in UI
    running_balance_actual: float
    day_delta_actual: float
    # True if a bank-balance entry reset the actual track on this day
    balance_anchored: bool = False
    # Safety threshold warnings (at or below user threshold)
    warn_est: bool = False
    warn_actual: bool = False
    # Legacy alias = estimate running (older clients)
    running_balance: float
    day_delta: float


class CalendarResponse(BaseModel):
    year: int
    month: int
    starting_balance: float
    ending_balance: float
    ending_balance_est: float
    ending_balance_actual: float
    safety_threshold: float = 0.0
    warn_days_est: int = 0
    warn_days_actual: int = 0
    days: list[CalendarDay]


class MetricsResponse(BaseModel):
    month_income: float
    month_expenses: float
    month_estimates: float
    month_bills: float
    month_actuals: float
    net: float
    by_category: dict[str, float]
    by_type: dict[str, float]


class UpcomingResponse(BaseModel):
    items: list[BudgetItemOut]


class StatementRow(BaseModel):
    date: Optional[Date] = None
    description: str
    amount: float
    is_income: bool
    raw: str = ""
    category: str = "Other"
    selected: bool = True
    possible_duplicate: bool = False


class StatementParseResponse(BaseModel):
    rows: list[StatementRow]
    imported: int = 0
    message: str = ""
    bank: str = "generic"
    bank_label: str = "Generic CSV"
    skipped: int = 0
    # Helps the UI jump the calendar to where imports landed
    first_date: Optional[Date] = None
    last_date: Optional[Date] = None
    categories: list[str] = []


class ImportCommitRow(BaseModel):
    date: Date
    description: str = Field(min_length=1, max_length=200)
    amount: float = Field(gt=0)
    is_income: bool = False
    category: str = "Other"
    item_type: str = "actual"  # actual | paycheck


class ImportDebtLink(BaseModel):
    """Optional credit-card debt for paydown math (APR etc.)."""

    name: str = Field(min_length=1, max_length=120)
    apr: float = Field(default=0, ge=0, le=100)  # annual % e.g. 22.9
    balance: float = Field(default=0, ge=0)  # remaining balance if known
    min_payment: float = Field(default=0, ge=0)
    # If true and debt exists, update APR/min/balance when provided
    update_existing: bool = True


class ImportCommitRequest(BaseModel):
    rows: list[ImportCommitRow]
    bank_label: str = "Import"
    debts: list[ImportDebtLink] = []


class ImportCommitResponse(BaseModel):
    imported: int
    message: str
    first_date: Optional[Date] = None
    last_date: Optional[Date] = None
    debts_updated: int = 0
    debts_created: int = 0


# ── Goals ──────────────────────────────────────────────────────────

class GoalCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target_amount: float = Field(gt=0)
    current_amount: float = Field(default=0, ge=0)
    target_date: Optional[Date] = None
    monthly_contribution: float = Field(default=0, ge=0)
    notes: str = ""


class GoalUpdate(BaseModel):
    name: Optional[str] = None
    target_amount: Optional[float] = None
    current_amount: Optional[float] = None
    target_date: Optional[Date] = None
    monthly_contribution: Optional[float] = None
    notes: Optional[str] = None


class GoalOut(BaseModel):
    id: int
    name: str
    target_amount: float
    current_amount: float
    target_date: Optional[Date] = None
    monthly_contribution: float
    notes: str
    remaining: float
    percent: float
    months_to_target: Optional[int] = None
    suggested_monthly: Optional[float] = None
    eta_date: Optional[Date] = None
    on_track: Optional[bool] = None

    class Config:
        from_attributes = True


# ── Debts / paydown ────────────────────────────────────────────────

class DebtCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    balance: float = Field(gt=0)
    apr: float = Field(default=0, ge=0)
    min_payment: float = Field(default=0, ge=0)
    notes: str = ""


class DebtUpdate(BaseModel):
    name: Optional[str] = None
    balance: Optional[float] = None
    apr: Optional[float] = None
    min_payment: Optional[float] = None
    notes: Optional[str] = None


class DebtOut(BaseModel):
    id: int
    name: str
    balance: float
    apr: float
    min_payment: float
    notes: str

    class Config:
        from_attributes = True


class DebtPlanRequest(BaseModel):
    strategy: Literal["avalanche", "snowball"] = "avalanche"
    extra_monthly: float = Field(default=0, ge=0)


class DebtPlanStep(BaseModel):
    month: int
    date_label: str
    payments: dict[str, float]
    balances: dict[str, float]
    total_paid: float
    total_interest: float
    paid_off: list[str] = []


class DebtPlanSummary(BaseModel):
    strategy: str
    strategy_label: str
    strategy_blurb: str
    extra_monthly: float
    total_min_payments: float
    monthly_budget: float
    months: int
    total_interest: float
    total_paid: float
    debt_free_label: str
    payoff_order: list[str]
    steps: list[DebtPlanStep]
    # Compare both strategies at a glance
    compare: Optional[dict] = None


# ── Investments (simple) ───────────────────────────────────────────

InvestmentType = Literal[
    "401k", "ira", "brokerage", "crypto", "529", "hsa", "savings", "other"
]


class InvestmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    account_type: InvestmentType = "other"
    current_value: float = Field(default=0, ge=0)
    cost_basis: float = Field(default=0, ge=0)
    monthly_contribution: float = Field(default=0, ge=0)
    notes: str = ""


class InvestmentUpdate(BaseModel):
    name: Optional[str] = None
    account_type: Optional[InvestmentType] = None
    current_value: Optional[float] = None
    cost_basis: Optional[float] = None
    monthly_contribution: Optional[float] = None
    notes: Optional[str] = None


class InvestmentOut(BaseModel):
    id: int
    name: str
    account_type: str
    current_value: float
    cost_basis: float
    monthly_contribution: float
    notes: str
    last_updated: Optional[Date] = None
    gain_loss: float = 0.0
    gain_loss_pct: Optional[float] = None

    class Config:
        from_attributes = True


class SnapshotOut(BaseModel):
    """One-screen family money picture."""

    household_name: str
    cash: float  # latest bank balance anchor or starting balance
    investments_total: float
    debts_total: float
    goals_saved: float
    goals_target: float
    net_worth: float  # cash + investments - debts
    monthly_invest_contrib: float
    members: list[dict]
    goal_count: int
    debt_count: int
    investment_count: int


RoleName = Literal["owner", "partner", "member", "viewer"]


class MemberOut(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    must_change_password: bool = False


class MemberCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=4, max_length=128)
    display_name: str = Field(default="", max_length=120)
    # owner = full control; partner = same day-to-day for spouse;
    # member = money edits; viewer = read-only
    role: RoleName = "partner"
    require_password_change: bool = False


# ── Pay stub / job pay ─────────────────────────────────────────────

class JobPayCreate(BaseModel):
    employer: str = ""
    employee_label: str = ""
    frequency: Literal["weekly", "biweekly", "semimonthly", "monthly"] = "biweekly"
    gross_pay: float = Field(default=0, ge=0)
    net_pay: float = Field(default=0, ge=0)
    last_pay_date: Optional[Date] = None
    monthly_net_estimate: float = Field(default=0, ge=0)
    notes: str = ""


class JobPayOut(BaseModel):
    id: int
    employer: str
    employee_label: str
    frequency: str
    gross_pay: float
    net_pay: float
    last_pay_date: Optional[Date] = None
    monthly_net_estimate: float
    notes: str
    next_pay_dates: list[Date] = []

    class Config:
        from_attributes = True


class PayStubApplyRequest(BaseModel):
    """Apply parsed/edited pay stub values into the household budget."""

    employer: str = "Paycheck"
    net_pay: float = Field(gt=0)
    gross_pay: float = Field(default=0, ge=0)
    pay_date: Date
    frequency: Literal["weekly", "biweekly", "semimonthly", "monthly"] = "biweekly"
    create_paycheck: bool = True
    save_job_profile: bool = True
    schedule_future: int = Field(default=0, ge=0, le=12)  # extra future paychecks
    employee_label: str = ""
    notes: str = ""
