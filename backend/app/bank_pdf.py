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
    text = _pdf_to_text(raw)
    if not text or len(text.strip()) < 40:
        return (
            [],
            bank or "auto",
            "Little text found in PDF. Scanned/image statements need OCR (not supported). "
            "Download the PDF from chase.com (not a phone photo), or use Chase CSV.",
        )

    requested = (bank or "auto").lower().strip()
    force_credit = requested in ("chase_credit", "chase-credit", "chase_card")
    detected = requested
    if detected in ("auto", "generic", ""):
        detected = _detect_pdf_bank(text)
    if force_credit:
        detected = "chase"

    if detected == "chase":
        rows = _parse_chase_statement(text, credit_like=True if force_credit else None)
        if not rows:
            year = _guess_year(text) or date.today().year
            rows = _parse_generic_mmdd_lines(text, year, default_income=False)
        if not rows:
            return (
                [],
                "chase",
                "This looks like a Chase PDF, but no dated charges were found. "
                "Credit-card and checking layouts differ. Try downloading CSV from chase.com "
                "(Activity → Download), or pick Chase in the bank list and Preview again. "
                "Phone photos of statements will not work.",
            )
        kind = "credit card" if force_credit else "statement"
        return (
            rows,
            "chase",
            f"Parsed Chase {kind} PDF ({len(rows)} transactions). "
            "You can Preview another file (checking or card) — it adds to this list, then Import selected.",
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


def _pdf_to_text(raw: bytes) -> str:
    """Prefer line-grouped PDF text so Chase tables keep date + amount together."""
    layout = _pdf_text_by_rows(raw)
    plain = extract_pdf_text(raw)
    def _score(t: str) -> int:
        return len(re.findall(r"\b\d{1,2}/\d{1,2}\b", t or ""))
    chosen = layout if _score(layout) >= _score(plain) else plain
    if _score(plain) > 0 and _score(layout) > 0 and abs(_score(layout) - _score(plain)) <= 2:
        # Both look similar; layout usually preserves rows better
        chosen = layout or plain
    return _normalize_statement_text(chosen or plain or "")


def _pdf_text_by_rows(raw: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw))
    lines_out: list[str] = []
    for page in reader.pages:
        bits: list[tuple[float, float, str]] = []

        def visitor(text, cm, tm, font_dict, font_size):  # noqa: ARG001
            t = text or ""
            if not str(t).strip():
                return
            try:
                x = float(tm[4])
                y = float(tm[5])
            except (TypeError, IndexError, ValueError):
                return
            bits.append((y, x, str(t)))

        try:
            page.extract_text(visitor_text=visitor)
        except TypeError:
            bits = []
        if not bits:
            t = page.extract_text() or ""
            lines_out.extend(t.splitlines())
            continue
        bits.sort(key=lambda b: (-round(b[0] / 3.0) * 3.0, b[1]))
        rows: list[list[tuple[float, str]]] = []
        cur_bucket: Optional[float] = None
        cur: list[tuple[float, str]] = []
        for y, x, t in bits:
            bucket = round(y / 3.0)
            if cur_bucket is None or bucket == cur_bucket:
                cur.append((x, t))
                cur_bucket = bucket
            else:
                rows.append(cur)
                cur = [(x, t)]
                cur_bucket = bucket
        if cur:
            rows.append(cur)
        for row in rows:
            row.sort(key=lambda p: p[0])
            parts: list[str] = []
            prev_x: Optional[float] = None
            for x, t in row:
                if parts and prev_x is not None and (x - prev_x) > 2.0:
                    parts.append(" ")
                parts.append(t)
                prev_x = x
            line = re.sub(r"\s+", " ", "".join(parts)).strip()
            line = re.sub(r"(\d)\s+/\s+(\d)", r"\1/\2", line)
            if line:
                lines_out.append(line)
    return "\n".join(lines_out)


def _normalize_statement_text(text: str) -> str:
    text = (text or "").replace("\u00a0", " ").replace("\u2022", " ")
    # Chase page-break markers can swallow the first digit of MM/DD
    text = re.sub(
        r"\*(?:start|end)\*transac(\d?)tion detail",
        r"\1",
        text,
        flags=re.I,
    )
    text = re.sub(r"\*(?:start|end)\*", "\n", text, flags=re.I)
    # Amount glued to the next date: 12.3408/15
    text = re.sub(r"(\d\.\d{2})(\d{1,2}/\d{1,2})", r"\1\n\2", text)
    # Letter glued to a date: WALMART08/15
    text = re.sub(r"([A-Za-z])(\d{1,2}/\d{1,2}\b)", r"\1\n\2", text)
    return text


def _detect_pdf_bank(text: str) -> str:
    t = text.lower()
    if (
        "jpmorgan chase" in t
        or "chase.com" in t
        or "chase premier" in t
        or "chase total" in t
        or "chase sapphire" in t
        or "chase freedom" in t
        or ("chase" in t and "account number" in t)
    ):
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
        r"(\d{1,2})/(\d{1,2})/(\d{2,4})\s*[-–]\s*(\d{1,2})/(\d{1,2})/(\d{2,4})",
        text,
    )
    if m:
        def _y(raw: str) -> int:
            y = int(raw)
            return y + 2000 if y < 100 else y

        return int(m.group(1)), _y(m.group(3)), int(m.group(4)), _y(m.group(6))
    m = re.search(
        r"(january|february|march|april|may|june|july|august|september|october|november|december)"
        r"\s+(\d{1,2})\s*[-–]\s*"
        r"(january|february|march|april|may|june|july|august|september|october|november|december)"
        r"\s+(\d{1,2}),?\s*(20\d{2})",
        text,
        re.I,
    )
    if m:
        return (
            _MONTHS[m.group(1).lower()],
            int(m.group(5)),
            _MONTHS[m.group(3).lower()],
            int(m.group(5)),
        )
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


_AMT_RE = re.compile(r"-?\$?[\d,]+\.\d{2}")
_SKIP_DESC = (
    "beginning balance",
    "ending balance",
    "opening balance",
    "closing balance",
    "previous balance",
    "new balance",
    "average balance",
    "minimum payment",
    "past due",
)


def _line_amounts(s: str) -> list[tuple[int, int, float]]:
    out: list[tuple[int, int, float]] = []
    for m in _AMT_RE.finditer(s or ""):
        val = _parse_amount(m.group(0))
        if val is not None:
            out.append((m.start(), m.end(), float(val)))
    return out


def _parse_chase_statement(text: str, credit_like: bool | None = None) -> list[ParsedRow]:
    """
    Chase checking: MM/DD description amount [running-balance]
    Chase credit:   MM/DD MM/DD description amount
    Multi-line card purchases: date+desc, then $amount on the next line.
    """
    start_m, start_y, end_m, end_y = _parse_period_years(text)
    year = end_y or start_y or date.today().year
    if credit_like is None:
        credit_like = bool(
            re.search(
                r"purchases and adjustments|account number ending|sapphire|freedom unlimited|ink business|prime visa",
                text,
                re.I,
            )
        )

    lines = [ln.strip() for ln in text.splitlines()]
    rows: list[ParsedRow] = []
    pending: Optional[dict] = None

    def flush_pending():
        nonlocal pending
        if not pending:
            return
        if pending.get("date") and pending.get("amount", 0) > 0:
            desc = pending.get("desc") or "Chase transaction"
            rows.append(
                ParsedRow(
                    date=pending["date"],
                    description=str(desc)[:200],
                    amount=float(pending["amount"]),
                    is_income=_chase_is_income(str(desc)),
                    raw=pending.get("raw", ""),
                )
            )
        pending = None

    for line in lines:
        if not line:
            continue
        low = line.lower()

        if low.startswith("total ") or "page of" in low:
            continue
        if low in (
            "deposits and additions",
            "atm & debit card withdrawals",
            "electronic withdrawals",
            "checking summary",
            "date description amount",
            "transaction detail",
            "purchases and adjustments",
            "payments and other credits",
        ):
            continue
        if low.startswith("*start*") or low.startswith("*end*"):
            continue

        # Standalone amount completing a multi-line transaction
        if pending and re.match(r"^-?\$?[\d,]+\.\d{2}$", line.replace(" ", "")):
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
            if pending:
                pending["desc"] = (pending.get("desc") or "") + " " + line
                pending["raw"] = (pending.get("raw") or "") + " | " + line
                extra = _line_amounts(line)
                if extra:
                    pending["amount"] = abs(extra[-1][2])
                    flush_pending()
            continue

        flush_pending()
        mm, dd = int(m.group(1)), int(m.group(2))
        y_part = m.group(3)
        rest = m.group(4).strip()
        # Credit cards often print transaction date then post date
        rest = re.sub(r"^\d{1,2}/\d{1,2}(?:/\d{2,4})?\s+", "", rest)
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

        amounts = _line_amounts(rest)
        amount = None
        desc = rest
        if amounts:
            # Checking: last number is running balance, second-to-last is the charge.
            # Credit: usually a single amount.
            pick = amounts[-1] if (credit_like or len(amounts) == 1) else amounts[-2]
            amount = abs(pick[2])
            desc = rest[: pick[0]].strip()
            desc = re.sub(r"\s{2,}", " ", desc).strip(" -")

        if any(desc.lower().startswith(s) for s in _SKIP_DESC):
            continue
        if desc.lower().startswith("total "):
            continue

        if amount is None:
            pending = {"date": dval, "desc": desc, "amount": 0.0, "raw": line}
            continue
        if amount < 0.001:
            continue
        if not dval:
            continue

        rows.append(
            ParsedRow(
                date=dval,
                description=(desc[:200] or "Chase transaction"),
                amount=amount,
                is_income=_chase_is_income(desc),
                raw=line,
            )
        )

    flush_pending()
    return rows


def _parse_chase_checking(text: str) -> list[ParsedRow]:
    return _parse_chase_statement(text)


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
