"""Group streaming / Apple / software repeats so they are visible."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from .categorize import looks_like_subscription, monthly_subscription_amount
from .models import BudgetItem
from .recurring import RECURRING


def _norm(name: str) -> str:
    return (name or "").strip().lower()


def summarize_subscriptions(db: Session, household_id: int, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    rows = (
        db.query(BudgetItem)
        .filter(BudgetItem.household_id == household_id, BudgetItem.is_income.is_(False))
        .order_by(BudgetItem.due_date, BudgetItem.id)
        .all()
    )
    groups: dict[str, list[BudgetItem]] = {}
    for it in rows:
        if it.item_type == "balance":
            continue
        flag = getattr(it, "is_subscription", None)
        if flag is False:
            continue
        inferred = looks_like_subscription(it.name, it.category, it.notes)
        if flag is not True and not inferred:
            continue
        groups.setdefault(_norm(it.name), []).append(it)

    items: list[dict[str, Any]] = []
    for _key, bunch in groups.items():
        bunch = sorted(bunch, key=lambda i: (i.due_date, i.id))
        recurring = [r for r in bunch if (r.frequency or "once") in RECURRING]
        canonical = recurring[-1] if recurring else bunch[-1]
        months = {r.due_date.strftime("%Y-%m") for r in bunch if r.due_date}
        freq = canonical.frequency or "once"
        guessed = False
        if freq == "once" and len(months) >= 2:
            freq = "monthly"
            guessed = True
        elif freq == "once":
            guessed = True
        monthly = monthly_subscription_amount(canonical.amount, freq if freq != "once" else "monthly")
        yearly = round(monthly * 12, 2)
        if (canonical.frequency or "once") in ("yearly", "annual"):
            yearly = round(float(canonical.amount), 2)
            monthly = monthly_subscription_amount(canonical.amount, "yearly")
        upcoming = [r.due_date for r in bunch if r.due_date and r.due_date >= today]
        next_date = min(upcoming) if upcoming else None
        repeating = bool(recurring)
        items.append(
            {
                "name": canonical.name,
                "amount": round(float(canonical.amount), 2),
                "monthly": monthly,
                "yearly": yearly,
                "frequency": canonical.frequency or "once",
                "display_frequency": freq,
                "next_date": next_date.isoformat() if next_date else None,
                "category": canonical.category or "",
                "item_id": canonical.id,
                "count": len(bunch),
                "repeating": repeating,
                "guessed": guessed and not repeating,
                "is_subscription": bool(getattr(canonical, "is_subscription", False)),
            }
        )

    items.sort(key=lambda r: (-r["monthly"], r["name"].lower()))
    monthly_total = round(sum(r["monthly"] for r in items), 2)
    return {
        "count": len(items),
        "monthly_total": monthly_total,
        "yearly_total": round(monthly_total * 12, 2),
        "items": items,
    }
