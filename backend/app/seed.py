from __future__ import annotations

from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .models import Household, ItemName, User

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
    ("Apple (iCloud / App Store)", "bill"),
    ("Netflix", "bill"),
    ("Spotify", "bill"),
    ("YouTube Premium", "bill"),
    ("Amazon Prime", "bill"),
    ("Disney+", "bill"),
    ("Hulu", "bill"),
    ("Max (HBO)", "bill"),
    ("Apple TV+", "bill"),
    ("iCloud+", "bill"),
    ("Adobe", "bill"),
    ("Microsoft 365", "bill"),
    ("Gym / membership", "bill"),
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

    # Dropdown name suggestions only — no pre-filled money items
    for name, kind in DEFAULT_NAMES:
        db.add(
            ItemName(
                household_id=household.id,
                name=name,
                kind=kind,
                is_default=True,
            )
        )

    db.commit()


EXTRA_SUB_NAMES = [
    ("Apple (iCloud / App Store)", "bill"),
    ("Netflix", "bill"),
    ("Spotify", "bill"),
    ("YouTube Premium", "bill"),
    ("Amazon Prime", "bill"),
    ("Disney+", "bill"),
    ("Hulu", "bill"),
    ("Max (HBO)", "bill"),
    ("Apple TV+", "bill"),
    ("iCloud+", "bill"),
    ("Adobe", "bill"),
    ("Microsoft 365", "bill"),
    ("Gym / membership", "bill"),
    ("Streaming", "bill"),
]


def ensure_subscription_names(db: Session) -> None:
    """Add common streaming names on existing installs (no duplicates)."""
    hh = db.query(Household).first()
    if not hh:
        return
    existing = {
        (n.name or "").strip().lower()
        for n in db.query(ItemName).filter(ItemName.household_id == hh.id).all()
    }
    added = 0
    for name, kind in EXTRA_SUB_NAMES:
        if name.strip().lower() in existing:
            continue
        db.add(ItemName(household_id=hh.id, name=name, kind=kind, is_default=True))
        existing.add(name.strip().lower())
        added += 1
    if added:
        db.commit()
