"""
Rule-based planning helpers (no AI).

Goals: remaining, % complete, suggested monthly to hit a date, ETA from contribution.
Debts: avalanche (highest APR first) vs snowball (lowest balance first) amortization.
"""

from __future__ import annotations

from calendar import monthrange
from copy import deepcopy
from datetime import date
from typing import Any


def goal_metrics(
    target_amount: float,
    current_amount: float,
    target_date: date | None,
    monthly_contribution: float,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    target = max(float(target_amount), 0.0)
    current = max(float(current_amount), 0.0)
    remaining = max(target - current, 0.0)
    percent = min(100.0, round((current / target) * 100, 1)) if target > 0 else 0.0

    months_to_target: int | None = None
    suggested_monthly: float | None = None
    if target_date and target_date > today and remaining > 0:
        # Whole months until target (at least 1)
        months_to_target = max(
            (target_date.year - today.year) * 12 + (target_date.month - today.month),
            1,
        )
        if target_date.day < today.day and months_to_target > 1:
            # partial month lag — keep simple: already counted
            pass
        suggested_monthly = round(remaining / months_to_target, 2)

    eta_date: date | None = None
    on_track: bool | None = None
    contrib = float(monthly_contribution or 0)
    if remaining <= 0:
        eta_date = today
        on_track = True
    elif contrib > 0:
        import math

        months_needed = max(1, math.ceil(remaining / contrib))
        eta_date = _add_months(today, months_needed)
        if target_date:
            on_track = eta_date <= target_date

    return {
        "remaining": round(remaining, 2),
        "percent": percent,
        "months_to_target": months_to_target,
        "suggested_monthly": suggested_monthly,
        "eta_date": eta_date,
        "on_track": on_track,
    }


def _add_months(d: date, n: int) -> date:
    y = d.year + (d.month - 1 + n) // 12
    m = (d.month - 1 + n) % 12 + 1
    last = monthrange(y, m)[1]
    return date(y, m, min(d.day, last))


def simulate_debt_paydown(
    debts: list[dict[str, Any]],
    strategy: str = "avalanche",
    extra_monthly: float = 0.0,
    start: date | None = None,
    max_months: int = 600,
) -> dict[str, Any]:
    """
    debts: [{id, name, balance, apr, min_payment}, ...]
    strategy: avalanche | snowball
    """
    start = start or date.today()
    extra_monthly = max(float(extra_monthly or 0), 0.0)

    books = []
    for d in debts:
        bal = float(d["balance"])
        if bal <= 0:
            continue
        books.append(
            {
                "id": d.get("id"),
                "name": str(d["name"]),
                "balance": bal,
                "apr": max(float(d.get("apr") or 0), 0.0),
                "min_payment": max(float(d.get("min_payment") or 0), 0.0),
            }
        )

    if not books:
        return {
            "strategy": strategy,
            "strategy_label": _label(strategy),
            "strategy_blurb": _blurb(strategy),
            "extra_monthly": extra_monthly,
            "total_min_payments": 0.0,
            "monthly_budget": extra_monthly,
            "months": 0,
            "total_interest": 0.0,
            "total_paid": 0.0,
            "debt_free_label": "No debts",
            "payoff_order": [],
            "steps": [],
        }

    total_min = sum(b["min_payment"] for b in books)
    monthly_budget = total_min + extra_monthly

    # Guard: each min must at least cover a bit of principal long-term; still allow run
    steps: list[dict] = []
    payoff_order: list[str] = []
    total_interest = 0.0
    total_paid = 0.0
    working = deepcopy(books)

    for month_i in range(1, max_months + 1):
        # Accrue interest
        for b in working:
            if b["balance"] <= 0:
                continue
            monthly_rate = b["apr"] / 100.0 / 12.0
            interest = round(b["balance"] * monthly_rate, 2)
            b["balance"] = round(b["balance"] + interest, 2)
            total_interest += interest

        active = [b for b in working if b["balance"] > 0.005]
        if not active:
            break

        # Minimums first
        payments: dict[str, float] = {b["name"]: 0.0 for b in working}
        paid_off_this: list[str] = []

        for b in active:
            pay = min(b["min_payment"], b["balance"])
            # If min is 0, still require a tiny payment floor later via extra
            if pay <= 0 and b["balance"] > 0:
                pay = min(25.0, b["balance"])  # floor so zero-min debts still move
            b["balance"] = round(b["balance"] - pay, 2)
            payments[b["name"]] = round(payments[b["name"]] + pay, 2)
            total_paid += pay
            if b["balance"] <= 0.005:
                b["balance"] = 0.0
                if b["name"] not in payoff_order:
                    payoff_order.append(b["name"])
                    paid_off_this.append(b["name"])

        # Extra pool = budget - what we already paid in mins this month
        already = sum(payments.values())
        extra_pool = max(monthly_budget - already, 0.0)

        # Also free up mins from paid-off debts (avalanche/snowball snowballing)
        # monthly_budget already includes original total mins; already paid may be less
        # if some paid off — extra_pool handles residual.

        while extra_pool > 0.009:
            targets = [b for b in working if b["balance"] > 0.005]
            if not targets:
                break
            target = _pick_target(targets, strategy)
            pay = min(extra_pool, target["balance"])
            target["balance"] = round(target["balance"] - pay, 2)
            payments[target["name"]] = round(payments[target["name"]] + pay, 2)
            total_paid += pay
            extra_pool = round(extra_pool - pay, 2)
            if target["balance"] <= 0.005:
                target["balance"] = 0.0
                if target["name"] not in payoff_order:
                    payoff_order.append(target["name"])
                    paid_off_this.append(target["name"])

        label_date = _add_months(start, month_i - 1)
        steps.append(
            {
                "month": month_i,
                "date_label": label_date.strftime("%b %Y"),
                "payments": {k: round(v, 2) for k, v in payments.items() if v > 0},
                "balances": {
                    b["name"]: round(b["balance"], 2) for b in working if b["balance"] > 0
                },
                "total_paid": round(sum(payments.values()), 2),
                "total_interest": round(total_interest, 2),
                "paid_off": paid_off_this,
            }
        )

        if all(b["balance"] <= 0.005 for b in working):
            break
    else:
        # hit max_months
        pass

    months = len(steps)
    free_date = _add_months(start, max(months - 1, 0)) if months else start

    return {
        "strategy": strategy,
        "strategy_label": _label(strategy),
        "strategy_blurb": _blurb(strategy),
        "extra_monthly": round(extra_monthly, 2),
        "total_min_payments": round(total_min, 2),
        "monthly_budget": round(monthly_budget, 2),
        "months": months,
        "total_interest": round(total_interest, 2),
        "total_paid": round(total_paid, 2),
        "debt_free_label": free_date.strftime("%b %Y") if months else "—",
        "payoff_order": payoff_order,
        "steps": steps[:120],  # cap payload; summary stats still full
    }


def _pick_target(active: list[dict], strategy: str) -> dict:
    if strategy == "snowball":
        return sorted(active, key=lambda b: (b["balance"], -b["apr"], b["name"]))[0]
    # avalanche default
    return sorted(active, key=lambda b: (-b["apr"], b["balance"], b["name"]))[0]


def _label(strategy: str) -> str:
    return "Avalanche (highest interest first)" if strategy == "avalanche" else "Snowball (smallest balance first)"


def _blurb(strategy: str) -> str:
    if strategy == "snowball":
        return (
            "Pay minimums on everything, throw all extra at the smallest balance. "
            "Quick wins can feel motivating — may cost more interest than avalanche."
        )
    return (
        "Pay minimums on everything, throw all extra at the highest APR. "
        "Usually costs the least interest over time."
    )


def compare_strategies(
    debts: list[dict[str, Any]], extra_monthly: float = 0.0
) -> dict[str, Any]:
    av = simulate_debt_paydown(debts, "avalanche", extra_monthly)
    sn = simulate_debt_paydown(debts, "snowball", extra_monthly)
    interest_saved = round(sn["total_interest"] - av["total_interest"], 2)
    months_diff = sn["months"] - av["months"]
    return {
        "avalanche": {
            "months": av["months"],
            "total_interest": av["total_interest"],
            "debt_free_label": av["debt_free_label"],
        },
        "snowball": {
            "months": sn["months"],
            "total_interest": sn["total_interest"],
            "debt_free_label": sn["debt_free_label"],
        },
        "interest_saved_with_avalanche": interest_saved,
        "months_diff": months_diff,
        "recommendation": (
            "Avalanche usually saves more on interest."
            if interest_saved > 0
            else "Both look similar on interest — pick the one she’ll stick with."
        ),
    }
