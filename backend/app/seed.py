from __future__ import annotations

from datetime import date
from calendar import monthrange

from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .models import BudgetItem, Household, ItemName, User

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

DEFAULT_NAMES = [
    ("Rent / Mortgage", "bill"),
    ("Electric", "bill"),
    ("Water", "bill"),
    ("Internet", "bill"),
    ("Phone", "bill"),
    ("Car payment", "bill"),
    ("Car insurance", "bill"),
    ("Health insurance", "bill"),
    ("Childcare", "bill"),
    ("Credit card", "bill"),
    ("Streaming", "bill"),
    ("Food", "estimate"),
    ("Gas", "estimate"),
    ("Kids activities", "estimate"),
    ("School / supplies", "estimate"),
    ("Household / misc", "estimate"),
    ("Medical / pharmacy", "estimate"),
    ("Clothing", "estimate"),
    ("Paycheck", "income"),
    ("Child support", "income"),
    ("Other income", "income"),
    ("Bank balance", "general"),
]


def ensure_admin_user(db: Session) -> None:
    """If no admin account exists, create first-time admin/admin (must change password)."""
    existing = db.query(User).filter(User.username == "admin").first()
    if existing:
        return
    db.add(
        User(
            username="admin",
            password_hash=pwd.hash("admin"),
            display_name="Admin",
            role="owner",
            must_change_password=True,
        )
    )
    db.commit()


def seed_if_empty(db: Session) -> None:
    if db.query(User).first():
        ensure_admin_user(db)
        return

    # First-time install only. Login: admin / admin — app requires password change.
    admin = User(
        username="admin",
        password_hash=pwd.hash("admin"),
        display_name="Admin",
        role="owner",
        must_change_password=True,
    )
    household = Household(
        name="My Household",
        starting_balance=0.0,
        currency="USD",
    )
    db.add_all([admin, household])
    db.flush()

    for name, kind in DEFAULT_NAMES:
        db.add(
            ItemName(
                household_id=household.id,
                name=name,
                kind=kind,
                is_default=True,
            )
        )

    today = date.today()
    y, m = today.year, today.month
    last_day = monthrange(y, m)[1]

    def d(day: int) -> date:
        return date(y, m, min(day, last_day))

    samples = [
        BudgetItem(
            household_id=household.id,
            name="Paycheck",
            item_type="paycheck",
            amount=2100.0,
            is_income=True,
            due_date=d(1),
            frequency="biweekly",
            notes="Sample — edit or delete",
            category="Income",
        ),
        BudgetItem(
            household_id=household.id,
            name="Paycheck",
            item_type="paycheck",
            amount=2100.0,
            is_income=True,
            due_date=d(15),
            frequency="biweekly",
            notes="Sample — edit or delete",
            category="Income",
        ),
        BudgetItem(
            household_id=household.id,
            name="Rent / Mortgage",
            item_type="bill",
            amount=1450.0,
            is_income=False,
            due_date=d(1),
            frequency="monthly",
            category="Housing",
        ),
        BudgetItem(
            household_id=household.id,
            name="Electric",
            item_type="bill",
            amount=140.0,
            is_income=False,
            due_date=d(12),
            frequency="monthly",
            category="Utilities",
        ),
        BudgetItem(
            household_id=household.id,
            name="Phone",
            item_type="bill",
            amount=95.0,
            is_income=False,
            due_date=d(18),
            frequency="monthly",
            category="Utilities",
        ),
        BudgetItem(
            household_id=household.id,
            name="Car insurance",
            item_type="bill",
            amount=165.0,
            is_income=False,
            due_date=d(22),
            frequency="monthly",
            category="Transport",
        ),
        BudgetItem(
            household_id=household.id,
            name="Food",
            item_type="estimate",
            amount=600.0,
            is_income=False,
            due_date=d(1),
            frequency="monthly",
            notes="Monthly estimate — hits running balance",
            category="Food",
        ),
        BudgetItem(
            household_id=household.id,
            name="Gas",
            item_type="estimate",
            amount=250.0,
            is_income=False,
            due_date=d(1),
            frequency="monthly",
            notes="Monthly estimate",
            category="Transport",
        ),
        BudgetItem(
            household_id=household.id,
            name="Kids activities",
            item_type="estimate",
            amount=120.0,
            is_income=False,
            due_date=d(10),
            frequency="monthly",
            category="Kids",
        ),
    ]
    db.add_all(samples)
    db.commit()
