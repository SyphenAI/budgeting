"""Keep monthly / every-2-weeks / weekly bills and pay on the calendar.

Only extends after the latest existing date so a deleted month stays deleted.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from typing import Iterable

from sqlalchemy.orm import Session

from .models import BudgetItem

RECURRING = ("weekly", "biweekly", "monthly")
REPEAT_TYPES = ("bill", "estimate", "paycheck")


def _add_months(d: date, months: int, day: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    return date(y, m, min(day, monthrange(y, m)[1]))


def next_after(last: date, frequency: str, monthly_day: int | None = None) -> date | None:
    if frequency == "monthly":
        return _add_months(last, 1, monthly_day or last.day)
    step = 14 if frequency == "biweekly" else 7 if frequency == "weekly" else 0
    if step <= 0:
        return None
    return last + timedelta(days=step)


def series_key(item: BudgetItem) -> tuple:
    return (
        (item.name or "").strip().lower(),
        item.item_type,
        item.frequency or "once",
        bool(item.is_income),
    )


def ensure_recurring_through(
    db: Session,
    household_id: int,
    year: int,
    month: int,
    extra_months: int = 2,
) -> int:
    """Create missing future occurrences through month + extra_months. Returns count added."""
    horizon_m = month + extra_months
    horizon_y = year + (horizon_m - 1) // 12
    horizon_m = (horizon_m - 1) % 12 + 1
    horizon = date(horizon_y, horizon_m, monthrange(horizon_y, horizon_m)[1])

    rows: Iterable[BudgetItem] = (
        db.query(BudgetItem)
        .filter(
            BudgetItem.household_id == household_id,
            BudgetItem.item_type.in_(REPEAT_TYPES),
            BudgetItem.frequency.in_(RECURRING),
        )
        .all()
    )
    groups: dict[tuple, list[BudgetItem]] = {}
    for row in rows:
        groups.setdefault(series_key(row), []).append(row)

    existing_dates = {
        ((i.name or "").strip().lower(), i.item_type, i.due_date) for i in rows
    }

    created = 0
    for items in groups.values():
        items_sorted = sorted(items, key=lambda i: (i.due_date, i.id))
        latest = items_sorted[-1]
        freq = latest.frequency
        if freq not in RECURRING:
            continue
        monthly_day = items_sorted[0].due_date.day
        cur = latest.due_date
        # Safety cap so a bad loop cannot flood the calendar
        for _ in range(36):
            nxt = next_after(cur, freq, monthly_day)
            if nxt is None or nxt > horizon:
                break
            key = ((latest.name or "").strip().lower(), latest.item_type, nxt)
            cur = nxt
            if key in existing_dates:
                continue
            db.add(
                BudgetItem(
                    household_id=household_id,
                    name=latest.name,
                    item_type=latest.item_type,
                    amount=float(latest.amount),
                    is_income=bool(latest.is_income),
                    due_date=nxt,
                    frequency=freq,
                    notes=latest.notes or "",
                    is_paid=False,
                    category=latest.category or "",
                )
            )
            existing_dates.add(key)
            created += 1

    if created:
        db.commit()
    return created
