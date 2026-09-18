"""Keep monthly / every-2-weeks / weekly bills and pay on the calendar.

Only extends after the latest existing date so a deleted month stays deleted.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from typing import Iterable

from sqlalchemy.orm import Session

from .models import BudgetItem

RECURRING = ("weekly", "biweekly", "monthly", "yearly")
REPEAT_TYPES = ("bill", "estimate", "paycheck")


def _add_months(d: date, months: int, day: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    return date(y, m, min(day, monthrange(y, m)[1]))


def next_after(last: date, frequency: str, monthly_day: int | None = None) -> date | None:
    if frequency == "monthly":
        return _add_months(last, 1, monthly_day or last.day)
    if frequency == "yearly":
        return _add_months(last, 12, monthly_day or last.day)
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
    month_start = date(year, month, 1)
    month_end = date(year, month, monthrange(year, month)[1])

    for items in groups.values():
        items_sorted = sorted(items, key=lambda i: (i.due_date, i.id))
        latest = items_sorted[-1]
        freq = latest.frequency
        if freq not in RECURRING:
            continue
        monthly_day = latest.due_date.day
        series_start = items_sorted[0].due_date
        stop = None
        for it in items_sorted:
            ru = getattr(it, "repeat_until", None)
            if ru:
                stop = ru if stop is None else max(stop, ru)

        # Fill this viewed month, but never before the first date you set
        # (first Gartner payday Oct 16 must not reappear in September).
        if freq == "monthly":
            due = date(year, month, min(monthly_day, month_end.day))
            if due >= series_start and not (stop and due > stop):
                key = ((latest.name or "").strip().lower(), latest.item_type, due)
                if key not in existing_dates:
                    db.add(
                        BudgetItem(
                            household_id=household_id,
                            name=latest.name,
                            item_type=latest.item_type,
                            amount=float(latest.amount),
                            is_income=bool(latest.is_income),
                            due_date=due,
                            frequency=freq,
                            notes=latest.notes or "",
                            is_paid=False,
                            category=latest.category or "",
                            is_subscription=getattr(latest, "is_subscription", None),
                        )
                    )
                    existing_dates.add(key)
                    created += 1
        elif freq in ("weekly", "biweekly"):
            step = 14 if freq == "biweekly" else 7
            cur = series_start
            while cur < month_start:
                cur += timedelta(days=step)
            while cur <= month_end:
                if cur >= series_start and not (stop and cur > stop):
                    key = ((latest.name or "").strip().lower(), latest.item_type, cur)
                    if key not in existing_dates:
                        db.add(
                            BudgetItem(
                                household_id=household_id,
                                name=latest.name,
                                item_type=latest.item_type,
                                amount=float(latest.amount),
                                is_income=bool(latest.is_income),
                                due_date=cur,
                                frequency=freq,
                                notes=latest.notes or "",
                                is_paid=False,
                                category=latest.category or "",
                                is_subscription=getattr(latest, "is_subscription", None),
                            )
                        )
                        existing_dates.add(key)
                        created += 1
                cur += timedelta(days=step)

        cur = latest.due_date
        group_horizon = horizon
        if freq == "yearly":
            group_horizon = max(horizon, _add_months(latest.due_date, 14, monthly_day))
        # Safety cap so a bad loop cannot flood the calendar
        for _ in range(36):
            nxt = next_after(cur, freq, monthly_day)
            if nxt is None or nxt > group_horizon:
                break
            if stop and nxt > stop:
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
                    is_subscription=getattr(latest, "is_subscription", None),
                )
            )
            existing_dates.add(key)
            created += 1

    if created:
        db.commit()
    return created


def matching_series(db: Session, household_id: int, item: BudgetItem) -> list[BudgetItem]:
    rows = (
        db.query(BudgetItem)
        .filter(
            BudgetItem.household_id == household_id,
            BudgetItem.item_type == item.item_type,
            BudgetItem.frequency == (item.frequency or "once"),
            BudgetItem.is_income == bool(item.is_income),
        )
        .order_by(BudgetItem.due_date, BudgetItem.id)
        .all()
    )
    key = series_key(item)
    return [r for r in rows if series_key(r) == key]


def _shift_due(old: date, new: date, other: date, frequency: str) -> date:
    if frequency in ("monthly", "yearly"):
        last = monthrange(other.year, other.month)[1]
        return date(other.year, other.month, min(new.day, last))
    delta = new - old
    return other + delta


def update_series(
    db: Session,
    household_id: int,
    item: BudgetItem,
    data: dict,
    scope: str = "this",
) -> BudgetItem:
    """Update one occurrence or this date and later in the same series."""
    was_recurring = (item.frequency or "once") in RECURRING
    scope = (scope or "this").strip().lower()
    if scope not in ("this", "future"):
        scope = "this"

    old_due = item.due_date
    old_freq = item.frequency or "once"
    old_name = item.name
    old_amount = float(item.amount)
    old_type = item.item_type

    if scope == "future" and was_recurring:
        mates = [r for r in matching_series(db, household_id, item) if r.due_date >= item.due_date]
        new_due = data.get("due_date")
        for row in mates:
            fields = dict(data)
            if new_due is not None and "due_date" in fields:
                fields["due_date"] = _shift_due(old_due, new_due, row.due_date, old_freq)
            if row.id != item.id:
                fields.pop("is_paid", None)
            for k, v in fields.items():
                setattr(row, k, v)
            if row.item_type == "paycheck":
                row.is_income = True
        db.commit()
        db.refresh(item)
        return item

    this_data = dict(data)
    if was_recurring:
        this_data.pop("frequency", None)
    for k, v in this_data.items():
        setattr(item, k, v)
    if item.item_type == "paycheck":
        item.is_income = True
    # Detach if name/type change, or the date moves to another month.
    # Same-month due-day changes (21st → 19th) stay on the series.
    if was_recurring:
        new_due = this_data.get("due_date", old_due)
        new_name = this_data.get("name", old_name)
        new_type = this_data.get("item_type", old_type)
        month_moved = (
            new_due
            and old_due
            and (new_due.year != old_due.year or new_due.month != old_due.month)
        )
        if new_name != old_name or new_type != old_type or month_moved:
            item.frequency = "once"
    db.commit()
    db.refresh(item)
    return item


def delete_series(db: Session, household_id: int, item: BudgetItem, scope: str = "this") -> dict:
    """Delete one date, or this date and later (stops auto-repeat)."""
    scope = (scope or "this").strip().lower()
    if scope not in ("this", "future"):
        scope = "this"
    freq = item.frequency or "once"
    was_recurring = freq in RECURRING and item.item_type in REPEAT_TYPES
    cut = item.due_date
    deleted = 0

    if scope == "future" and was_recurring:
        mates = matching_series(db, household_id, item)
        remaining = [r for r in mates if r.due_date < cut]
        going = [r for r in mates if r.due_date >= cut]
        stop = cut - timedelta(days=1)
        for row in remaining:
            row.repeat_until = stop
        for row in going:
            db.delete(row)
            deleted += 1
        db.commit()
        return {"ok": True, "deleted": deleted, "scope": "future"}

    # Skip this date only. If it was the last copy, plant the next one so
    # later months still fill in and this hole stays empty.
    plant_next = False
    nxt = None
    template = None
    if was_recurring:
        mates = matching_series(db, household_id, item)
        later = [r for r in mates if r.due_date > cut or (r.due_date == cut and r.id != item.id)]
        if not later:
            monthly_day = mates[0].due_date.day if mates else cut.day
            nxt = next_after(cut, freq, monthly_day)
            template = item
            plant_next = nxt is not None
    db.delete(item)
    deleted = 1
    if plant_next and nxt is not None and template is not None:
        exists = (
            db.query(BudgetItem)
            .filter(
                BudgetItem.household_id == household_id,
                BudgetItem.item_type == template.item_type,
                BudgetItem.due_date == nxt,
                BudgetItem.name == template.name,
            )
            .first()
        )
        if not exists:
            db.add(
                BudgetItem(
                    household_id=household_id,
                    name=template.name,
                    item_type=template.item_type,
                    amount=float(template.amount),
                    is_income=bool(template.is_income),
                    due_date=nxt,
                    frequency=freq,
                    notes=template.notes or "",
                    is_paid=False,
                    category=template.category or "",
                    repeat_until=getattr(template, "repeat_until", None),
                    is_subscription=getattr(template, "is_subscription", None),
                )
            )
    db.commit()
    return {"ok": True, "deleted": deleted, "scope": "this"}
