"""Credit-card statement helpers — summary fields, charges, recurring merchants.

Does not write to the calendar. Used by the Cards tracker.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from typing import Any, Optional

from .bank_import import _parse_amount, _parse_date
from .bank_pdf import _normalize_statement_text, _parse_chase_statement, parse_statement_pdf
from .categorize import looks_like_subscription, suggest_category

SKIP_SPEND_CATS = {"Payment", "Transfer", "Credit card payment", "Income"}


_SKIP_TXN = (
    "purchase interest charge",
    "interest charged",
    "late fee",
    "minimum payment",
    "new balance",
    "previous balance",
    "past due",
)


def parse_card_pdf(raw: bytes) -> dict[str, Any]:
    """Parse a credit-card PDF into summary + transactions (local text only)."""
    from .paystub import extract_pdf_text
    from .bank_pdf import _pdf_to_text

    text = _pdf_to_text(raw) or extract_pdf_text(raw)
    text = _normalize_statement_text(text or "")
    summary = parse_card_summary(text)
    rows = _parse_chase_statement(text, credit_like=True)
    if not rows:
        parsed, _detected, _msg = parse_statement_pdf(raw, bank="chase_credit")
        rows = parsed
    txns = []
    for r in rows:
        desc = (r.description or "").strip()
        if not r.date or not r.amount:
            continue
        low = desc.lower()
        if any(s in low for s in _SKIP_TXN):
            if "interest" in low and summary.get("interest_charged") in (None, 0):
                summary["interest_charged"] = round(float(r.amount), 2)
            continue
        is_credit = bool(r.is_income) or bool(
            re.search(r"payment thank|payment received|statement credit|refund", low)
        )
        txns.append(
            {
                "date": r.date.isoformat(),
                "description": desc[:200],
                "amount": round(float(r.amount), 2),
                "is_credit": is_credit,
                "category": "Payment"
                if is_credit
                else suggest_category(desc, is_income=False),
            }
        )
    recurring = find_recurring_charges(txns)
    return {
        "summary": summary,
        "transactions": txns,
        "recurring": recurring,
        "message": (
            f"Found {len(txns)} card charge(s). "
            + (
                f"New balance {summary.get('new_balance')} · "
                if summary.get("new_balance") is not None
                else ""
            )
            + (
                f"min pay {summary.get('min_payment')} · "
                if summary.get("min_payment") is not None
                else ""
            )
            + (f"APR {summary.get('apr')}%." if summary.get("apr") else "")
        ).strip(),
    }


def parse_card_summary(text: str) -> dict[str, Any]:
    t = text or ""
    out: dict[str, Any] = {
        "card_name": _guess_card_name(t),
        "last4": _find_last4(t),
        "new_balance": _money_near(
            t, r"(?:new\s+balance|current\s+balance|statement\s+balance)"
        ),
        "previous_balance": _money_near(t, r"previous\s+balance"),
        "min_payment": _money_near(t, r"minimum\s+payment(?:\s+due)?"),
        "due_date": _date_near(t, r"payment\s+due\s+date"),
        "statement_date": _date_near(t, r"(?:statement\s+closing\s+date|closing\s+date)"),
        "apr": _apr_near(t),
        "interest_charged": _money_near(
            t, r"(?:purchase\s+interest\s+charge|interest\s+charged|interest\s+charge)"
        ),
    }
    return out


def _guess_card_name(text: str) -> str:
    low = text.lower()
    if "sapphire" in low:
        return "Chase Sapphire"
    if "freedom unlimited" in low:
        return "Chase Freedom Unlimited"
    if "freedom" in low:
        return "Chase Freedom"
    if "amazon" in low and "prime" in low:
        return "Amazon Prime Visa"
    if "ink business" in low or "ink cash" in low:
        return "Chase Ink"
    if "slate" in low:
        return "Chase Slate"
    last4 = _find_last4(text)
    if last4:
        return f"Chase card …{last4}"
    return "Chase card"


def _find_last4(text: str) -> str:
    patterns = (
        r"ending\s+in\s+(\d{4})",
        r"account(?:\s+number)?[:\s]+(?:[\dXx*]{4}[\s-]*){3}(\d{4})",
        r"xxxx[\s-]*xxxx[\s-]*xxxx[\s-]*(\d{4})",
        r"x{4,}\s*(\d{4})\b",
    )
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            return m.group(1)
    return ""


def _money_near(text: str, label: str) -> Optional[float]:
    m = re.search(label + r"[:\s$]*([\d,]+\.\d{2})", text, re.I)
    if not m:
        m = re.search(r"([\d,]+\.\d{2})[:\s]*" + label, text, re.I)
    if not m:
        return None
    return _parse_amount(m.group(1))


def _apr_near(text: str) -> Optional[float]:
    for pat in (
        r"purchase\s+apr[:\s]*([\d.]+)\s*%",
        r"purchase\s+apr[\s\S]{0,80}?([\d]{1,2}\.[\d]{1,2})\s*%",
        r"annual\s+percentage\s+rate\s*\(?\s*apr\s*\)?[:\s]*([\d.]+)\s*%",
        r"variable\s+apr[:\s]*([\d.]+)\s*%",
        r"apr[:\s]*([\d.]+)\s*%",
        r"([\d.]+)\s*%\s*(?:purchase|variable)",
    ):
        m = re.search(pat, text, re.I)
        if m:
            try:
                val = float(m.group(1))
            except ValueError:
                continue
            if 0 < val < 80:
                return round(val, 2)
    return None


def _date_near(text: str, label: str) -> Optional[str]:
    m = re.search(
        label + r"[:\s]*(\d{1,2}/\d{1,2}/\d{2,4}|\w+\s+\d{1,2},\s*\d{4})",
        text,
        re.I,
    )
    if not m:
        return None
    d = _parse_date(m.group(1))
    return d.isoformat() if d else None


def merchant_key(description: str, amount: float | None = None) -> str:
    d = (description or "").upper()
    d = re.sub(r"AMZN\.COM/BILL\S*", "AMAZON", d)
    d = re.sub(r"AMAZON\s+MKTPL\S*", "AMAZON MARKETPLACE", d)
    d = re.sub(r"AMAZON\.COM\S*", "AMAZON", d)
    # Apple bills the same APPLE.COM/BILL for iCloud, Apple One, etc. — keep amount so they don't merge.
    if "APPLE" in d and ("BILL" in d or "ITUNES" in d or "APPLE.COM" in d):
        if amount is not None:
            return f"APPLE.COM/BILL {float(amount):.2f}"
        return "APPLE.COM/BILL"
    d = re.sub(r"APPLE\.COM/\S*", "APPLE", d)
    d = re.sub(r"\b\d{4,}\b", " ", d)
    d = re.sub(r"[^A-Z0-9 &+]", " ", d)
    d = re.sub(r"\s+", " ", d).strip()
    tokens = [
        t
        for t in d.split()
        if t not in {"THE", "AND", "WWW", "COM", "BILL"} and not re.fullmatch(r"\d{3,}", t)
    ]
    return " ".join(tokens[:4]) or d[:40]


def find_recurring_charges(txns: list[dict]) -> list[dict[str, Any]]:
    """Group similar merchants that show up more than once (or look like a sub)."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for t in txns:
        if t.get("is_credit"):
            continue
        key = merchant_key(t.get("description") or "", t.get("amount"))
        if not key:
            continue
        groups[key].append(t)

    out: list[dict[str, Any]] = []
    for key, rows in groups.items():
        months = {(r.get("date") or "")[:7] for r in rows if r.get("date")}
        amounts = [float(r["amount"]) for r in rows]
        avg = round(sum(amounts) / len(amounts), 2)
        looks_sub = looks_like_subscription(key, rows[0].get("category") or "")
        if len(months) < 2 and not looks_sub and len(rows) < 2:
            continue
        if len(rows) == 1 and not looks_sub:
            continue
        last = max(rows, key=lambda r: r.get("date") or "")
        out.append(
            {
                "merchant": key.title(),
                "count": len(rows),
                "months": len(months),
                "typical_amount": avg,
                "last_date": last.get("date"),
                "last_description": last.get("description"),
                "key": key,
                "looks_like_subscription": looks_sub,
                "guessed": len(months) >= 2 or looks_sub,
            }
        )
    out.sort(key=lambda r: (-r["count"], -r["typical_amount"]))
    return out


def analyze_card_spend(rows: list[dict]) -> dict:
    """rows: date, description, amount, is_credit, category, card_name, last4"""
    spend = []
    for r in rows:
        if r.get("is_credit"):
            continue
        cat = r.get("category") or suggest_category(r.get("description") or "", False)
        if cat in SKIP_SPEND_CATS:
            continue
        desc = (r.get("description") or "").lower()
        if "thank you" in desc or "automatic payment" in desc:
            continue
        spend.append({**r, "category": cat, "key": merchant_key(r.get("description") or "", r.get("amount"))})

    total = round(sum(float(r["amount"]) for r in spend), 2)
    by_cat: dict[str, dict] = {}
    by_card: dict[str, dict] = {}
    by_merch: dict[str, dict] = {}
    for r in spend:
        amt = float(r["amount"])
        cat = r["category"] or "Other"
        card = r.get("card_name") or "Card"
        last4 = r.get("last4") or ""
        ck = f"{card}|{last4}"
        mk = r.get("key") or (r.get("description") or "Unknown")[:40]
        by_cat.setdefault(cat, {"category": cat, "amount": 0.0, "count": 0})
        by_cat[cat]["amount"] += amt
        by_cat[cat]["count"] += 1
        by_card.setdefault(ck, {"name": card, "last4": last4, "amount": 0.0, "count": 0})
        by_card[ck]["amount"] += amt
        by_card[ck]["count"] += 1
        by_merch.setdefault(mk, {"merchant": mk.title() if mk == mk.upper() else mk, "amount": 0.0, "count": 0, "category": cat, "cards": set()})
        by_merch[mk]["amount"] += amt
        by_merch[mk]["count"] += 1
        by_merch[mk]["cards"].add(card)

    def _pct(n):
        return round(100.0 * n / total, 1) if total else 0.0

    cats = sorted(by_cat.values(), key=lambda x: -x["amount"])
    for c in cats:
        c["amount"] = round(c["amount"], 2)
        c["pct"] = _pct(c["amount"])
    cards = sorted(by_card.values(), key=lambda x: -x["amount"])
    for c in cards:
        c["amount"] = round(c["amount"], 2)
        c["pct"] = _pct(c["amount"])
    merchants = []
    for m in sorted(by_merch.values(), key=lambda x: -x["amount"])[:40]:
        merchants.append(
            {
                "merchant": m["merchant"],
                "amount": round(m["amount"], 2),
                "count": m["count"],
                "category": m["category"],
                "cards": sorted(m["cards"]),
                "pct": _pct(m["amount"]),
            }
        )
    dining = next((c for c in cats if c["category"] == "Dining / coffee"), None)
    return {
        "total": total,
        "count": len(spend),
        "by_category": cats,
        "by_card": cards,
        "merchants": merchants,
        "dining_total": dining["amount"] if dining else 0,
        "dining_count": dining["count"] if dining else 0,
    }
