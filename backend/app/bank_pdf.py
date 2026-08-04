"""
PDF bank statement parsers (local text extract only — no OCR).

Currently tuned for Chase personal checking/savings monthly statements
from a real sample layout (sections: Deposits, ATM/Debit, Electronic Withdrawals).
"""

from __future__ import annotations

import io
import re
from datetime import date
from typing import Optional

from .bank_import import ParsedRow, _parse_amount, _parse_date
from .paystub import extract_pdf_text


# Month names for statement period header
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def parse_statement_pdf(
    raw: bytes,
    bank: str = "auto",
) -> tuple[list[ParsedRow], str, str]:
    """
    Returns (rows, detected_bank, message).
    """
    text = extract_pdf_text(raw)
    if not text or len(text.strip()) < 40:
        return (
            [],
            bank or "auto",
            "Little text found in PDF. Scanned/image statements need OCR (not supported). "
            "Use a PDF downloaded from online banking.",
        )

    detected = (bank or "auto").lower().strip()
    if detected in ("auto", "generic", ""):
        detected = _detect_pdf_bank(text)

    if detected == "chase":
        rows = _parse_chase_checking(text)
        return (
            rows,
            "chase",
            f"Parsed Chase PDF statement ({len(rows)} transactions). Preview carefully.",
        )

    # Fallback: generic line scan MM/DD ... amount
    year = _guess_year(text) or date.today().year
    rows = _parse_generic_mmdd_lines(text, year, default_income=False)
    return (
        rows,
        detected if detected not in ("auto", "") else "generic",
        f"Parsed PDF with generic line rules ({len(rows)} rows). "
        "If this looks wrong, try bank=Chase or enter items by hand.",
    )


def _detect_pdf_bank(text: str) -> str:
    t = text.lower()
    if "jpmorgan chase" in t or "chase.com" in t or "chase premier" in t or "chase total" in t:
        return "chase"
    if "bank of america" in t or "bankofamerica.com" in t:
        return "bank_of_america"
    if "wells fargo" in t:
        return "wells_fargo"
    if "citibank" in t or "citi.com" in t:
        return "citi"
    if "u.s. bank" in t or "us bank" in t:
        return "us_bank"
    return "generic"


def _guess_year(text: str) -> Optional[int]:
    # "June 26, 2026 through July 24, 2026"
    m = re.search(
        r"(january|february|march|april|may|june|july|august|september|october|november|december)"
        r"\s+\d{1,2},\s*(20\d{2})\s+through\s+"
        r"(january|february|march|april|may|june|july|august|september|october|november|december)"
        r"\s+\d{1,2},\s*(20\d{2})",
        text,
        re.I,
    )
    if m:
        return int(m.group(4) or m.group(2))
    m = re.search(r"\b(20\d{2})\b", text)
    if m:
        return int(m.group(1))
    return None


def _parse_period_years(text: str) -> tuple[Optional[int], Optional[int], Optional[int], Optional[int]]:
    """
    Returns (start_month, start_year, end_month, end_year) if header found.
    """
    m = re.search(
        r"(january|february|march|april|may|june|july|august|september|october|november|december)"
        r"\s+(\d{1,2}),\s*(20\d{2})\s+through\s+"
        r"(january|february|march|april|may|june|july|august|september|october|november|december)"
        r"\s+(\d{1,2}),\s*(20\d{2})",
        text,
        re.I,
    )
    if not m:
        return None, None, None, None
    sm = _MONTHS[m.group(1).lower()]
    sy = int(m.group(3))
    em = _MONTHS[m.group(4).lower()]
    ey = int(m.group(6))
    return sm, sy, em, ey


def _mmdd_to_date(mm: int, dd: int, start_m: Optional[int], start_y: Optional[int], end_m: Optional[int], end_y: Optional[int], fallback_year: int) -> Optional[date]:
    if start_m and start_y and end_m and end_y:
        # Prefer year that places month in statement range
        candidates = []
        for y in {start_y, end_y, fallback_year}:
            try:
                candidates.append(date(y, mm, dd))
            except ValueError:
                continue
        # Pick date within [period_start, period_end] if possible
        try:
            p0 = date(start_y, start_m, 1)
            # rough end
            p1 = date(end_y, end_m, 28)
        except ValueError:
            p0 = p1 = None
        for c in candidates:
            if p0 and p1 and p0.replace(day=1) <= c.replace(day=1) <= p1.replace(day=28):
                # Better: if month == start_m use start_y, if month == end_m use end_y
                if mm == start_m:
                    try:
                        return date(start_y, mm, dd)
                    except ValueError:
                        pass
                if mm == end_m:
                    try:
                        return date(end_y, mm, dd)
                    except ValueError:
                        pass
        if mm == start_m:
            try:
                return date(start_y, mm, dd)
            except ValueError:
                return None
        if mm == end_m:
            try:
                return date(end_y, mm, dd)
            except ValueError:
                return None
    try:
        return date(fallback_year, mm, dd)
    except ValueError:
        return None


def _chase_is_income(desc: str) -> bool:
    """
    Chase PDF text often lists transactions before section headers, so we classify
    by description rather than relying on section order.
    """
    dl = re.sub(r"\s+", " ", (desc or "").lower()).strip()

    # Interest is income (must beat generic "payment" rule)
    if "interest payment" in dl or dl.startswith("interest "):
        return True

    # Clear expenses first (avoid "payment" false positives on income)
    expense_markers = (
        "payment to chase",
        "card purchase",
        "autopay",
        "online transfer to",
        "atm withdrawal",
        "withdrawal",
        "web pmts",
        "crcardpmt",
        "insurance",
        "electric",
        "wireless",
        "moneyline",  # brokerage transfer out
    )
    if any(k in dl for k in expense_markers):
        return False
    # Generic bill payments / transfers out
    if re.search(r"\bpayment\b", dl) and "payment from" not in dl and "zelle payment from" not in dl:
        if not dl.startswith("deposit") and "interest" not in dl:
            return False
    if "trnsfer" in dl or "transfer   " in dl or re.search(r"\btransfer\b", dl):
        # Paypal Transfer can be either; payroll/deposit keywords handled below
        if "paypal" in dl:
            return True  # often P2P receive; user can fix in preview
        if "online transfer to" in dl or "transfer to chk" in dl:
            return False
        if "transfer" in dl and "from" not in dl:
            return False

    income_markers = (
        "deposit",
        "payroll",
        "interest payment",
        "zelle payment from",
        "payment from",
        "xxva benef",
        "vacp treas",
        "direct dep",
        "treasury",
        "tax refund",
        "refund",
    )
    if any(k in dl for k in income_markers):
        return True
    return False


def _parse_chase_checking(text: str) -> list[ParsedRow]:
    """
    Chase checking statement lines: MM/DD Description .... amount
    Multi-line card purchases end with $total on its own line.
    """
    start_m, start_y, end_m, end_y = _parse_period_years(text)
    year = end_y or start_y or date.today().year

    lines = [ln.strip() for ln in text.splitlines()]
    rows: list[ParsedRow] = []
    pending: Optional[dict] = None  # multi-line card purchase

    def flush_pending():
        nonlocal pending
        if not pending:
            return
        if pending.get("amount", 0) > 0:
            rows.append(
                ParsedRow(
                    date=pending["date"],
                    description=pending["desc"][:200],
                    amount=pending["amount"],
                    is_income=False,
                    raw=pending.get("raw", ""),
                )
            )
        pending = None

    for line in lines:
        if not line:
            continue
        low = line.lower()

        # Ignore summary / header noise
        if low.startswith("total ") or "page of" in low:
            continue
        if low in (
            "deposits and additions",
            "atm & debit card withdrawals",
            "electronic withdrawals",
            "checking summary",
            "date description amount",
        ):
            continue
        if low.startswith("*start*") or low.startswith("*end*"):
            continue

        # Standalone amount completing multi-line debit
        if pending and re.match(r"^\$?[\d,]+\.\d{2}$", line.replace(" ", "")):
            amt = _parse_amount(line)
            if amt is not None:
                pending["amount"] = abs(amt)
                flush_pending()
                continue

        m = re.match(
            r"^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\s+(.+)$",
            line,
        )
        if not m:
            if pending and ("purchase $" in low or "cash back" in low):
                pending["desc"] += " " + line
                pending["raw"] += " | " + line
            continue

        flush_pending()
        mm, dd = int(m.group(1)), int(m.group(2))
        y_part = m.group(3)
        rest = m.group(4).strip()
        if y_part:
            y = int(y_part)
            if y < 100:
                y += 2000
            try:
                dval = date(y, mm, dd)
            except ValueError:
                dval = None
        else:
            dval = _mmdd_to_date(mm, dd, start_m, start_y, end_m, end_y, year)

        am = re.search(r"\$?\s*([\d,]+\.\d{2})\s*$", rest)
        amount = None
        desc = rest
        if am:
            amount = _parse_amount(am.group(1))
            desc = rest[: am.start()].strip()
            desc = re.sub(r"\s{2,}", " ", desc).strip(" -")

        if amount is None and "card purchase" in (desc + " " + low).lower():
            pending = {"date": dval, "desc": desc, "amount": 0.0, "raw": line}
            continue

        if amount is None or abs(float(amount)) < 0.001:
            continue
        if desc.lower().startswith("total "):
            continue

        is_income = _chase_is_income(desc)
        rows.append(
            ParsedRow(
                date=dval,
                description=desc[:200] or "Chase transaction",
                amount=abs(float(amount)),
                is_income=is_income,
                raw=line,
            )
        )

    flush_pending()
    return rows


def _parse_generic_mmdd_lines(text: str, year: int, default_income: bool) -> list[ParsedRow]:
    rows: list[ParsedRow] = []
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\s+(.+)$", line)
        if not m:
            continue
        mm, dd = int(m.group(1)), int(m.group(2))
        rest = m.group(4)
        am = re.search(r"(-?\$?[\d,]+\.\d{2})\s*$", rest)
        if not am:
            continue
        amount = _parse_amount(am.group(1))
        if amount is None:
            continue
        desc = rest[: am.start()].strip()
        try:
            if m.group(3):
                y = int(m.group(3))
                if y < 100:
                    y += 2000
                dval = date(y, mm, dd)
            else:
                dval = date(year, mm, dd)
        except ValueError:
            dval = None
        rows.append(
            ParsedRow(
                date=dval,
                description=desc[:200] or "Imported",
                amount=abs(amount),
                is_income=amount > 0 if default_income else amount > 0,
                raw=line,
            )
        )
    return rows
