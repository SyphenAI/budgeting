"""
CSV statement parsers for major US banks (activity export, not PDF).

Supported presets:
  chase, bank_of_america, wells_fargo, citi, us_bank, auto, generic

These match common online-banking "Download CSV" layouts. Banks change headers
occasionally — auto mode sniffs headers; users can force a bank if needed.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional


BANK_PRESETS = {
    "auto": "Auto-detect",
    "chase": "Chase",
    "bank_of_america": "Bank of America",
    "wells_fargo": "Wells Fargo",
    "citi": "Citi",
    "us_bank": "U.S. Bank",
    "generic": "Generic CSV",
}


@dataclass
class ParsedRow:
    date: Optional[date]
    description: str
    amount: float
    is_income: bool
    raw: str = ""


def parse_bank_csv(
    raw: bytes,
    bank: str = "auto",
) -> tuple[list[ParsedRow], str, str]:
    """
    Returns (rows, detected_bank, human_message).
    """
    text = raw.decode("utf-8-sig", errors="replace")
    # Normalize weird newlines
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln for ln in text.split("\n") if ln.strip() != ""]
    if not lines:
        return [], bank, "File is empty"

    bank_key = (bank or "auto").lower().strip()
    if bank_key not in BANK_PRESETS:
        bank_key = "auto"

    # Wells Fargo often has NO header row: Date,Amount,*,,Description
    if bank_key == "wells_fargo" or (
        bank_key == "auto" and _looks_like_wells_no_header(lines[0])
    ):
        rows = _parse_wells_fargo(lines)
        return rows, "wells_fargo", f"Parsed as Wells Fargo ({len(rows)} rows)"

    # Skip metadata lead-in rows some banks add before the real header
    header_idx, fieldnames = _find_header_row(lines)
    body = "\n".join(lines[header_idx:])
    reader = csv.DictReader(io.StringIO(body))
    if not reader.fieldnames:
        return [], bank_key, "Could not read CSV headers"

    headers_l = [_norm_header(h) for h in reader.fieldnames if h]
    detected = bank_key
    if bank_key == "auto":
        detected = _detect_bank(headers_l, lines[header_idx])
    elif bank_key == "generic":
        detected = "generic"

    rows = _parse_dict_rows(reader, detected)
    label = BANK_PRESETS.get(detected, detected)
    return rows, detected, f"Parsed as {label} ({len(rows)} rows)"


def _norm_header(h: str) -> str:
    return re.sub(r"\s+", " ", (h or "").strip().lower())


def _find_header_row(lines: list[str]) -> tuple[int, list[str]]:
    """Find the first CSV line that looks like a header with date/amount/desc."""
    for i, line in enumerate(lines[:25]):
        try:
            cols = next(csv.reader([line]))
        except Exception:
            continue
        norms = [_norm_header(c) for c in cols if c and c.strip()]
        joined = " ".join(norms)
        score = 0
        if any("date" in n for n in norms):
            score += 2
        if any(n in ("amount", "debit", "credit", "withdrawal", "deposit") for n in norms):
            score += 2
        if any(
            x in joined
            for x in ("description", "memo", "payee", "name", "transaction")
        ):
            score += 1
        if score >= 3:
            return i, cols
    # default first line
    cols = next(csv.reader([lines[0]]))
    return 0, cols


def _detect_bank(headers: list[str], header_line: str) -> str:
    hset = set(headers)
    blob = " | ".join(headers)

    # Chase credit: transaction date, post date, description, category, type, amount, memo
    if "transaction date" in hset and "post date" in hset and "amount" in hset:
        return "chase"
    # Chase checking: details, posting date, description, amount, type, balance
    if "posting date" in hset and "details" in hset and "amount" in hset:
        return "chase"
    if "posting date" in hset and "description" in hset and "amount" in hset:
        return "chase"

    # Bank of America: Date, Description, Amount, Running Bal.
    if "running bal." in hset or "running bal" in hset or "running balance" in hset:
        if "date" in hset and "description" in hset:
            return "bank_of_america"
    if headers == ["date", "description", "amount", "running bal."] or (
        "running bal" in blob and "description" in blob
    ):
        return "bank_of_america"

    # Citi: Status, Date, Description, Debit, Credit
    if "debit" in hset and "credit" in hset and "status" in hset:
        return "citi"
    if "debit" in hset and "credit" in hset and "date" in hset:
        return "citi"

    # U.S. Bank: often Name, Memo, Amount or Transaction
    if "name" in hset and "memo" in hset and "amount" in hset:
        return "us_bank"
    if "transaction" in hset and "name" in hset:
        return "us_bank"

    # Wells with header
    if "withdrawals" in blob or "deposits" in blob:
        return "wells_fargo"

    return "generic"


def _looks_like_wells_no_header(first_line: str) -> bool:
    """Wells Fargo classic: 01/15/2024,-45.00,*,,STORE NAME"""
    try:
        cols = next(csv.reader([first_line]))
    except Exception:
        return False
    if len(cols) < 3:
        return False
    # First col date-like, second amount-like, no "date" header word
    if "date" in (cols[0] or "").lower():
        return False
    if _parse_date(cols[0]) and _parse_amount(cols[1]) is not None:
        return True
    return False


def _parse_wells_fargo(lines: list[str]) -> list[ParsedRow]:
    rows: list[ParsedRow] = []
    start = 0
    # Optional header
    try:
        first = next(csv.reader([lines[0]]))
        if any("date" in (c or "").lower() for c in first):
            start = 1
    except Exception:
        pass

    for line in lines[start:]:
        try:
            cols = next(csv.reader([line]))
        except Exception:
            continue
        if len(cols) < 2:
            continue
        dval = _parse_date(cols[0])
        amt = _parse_amount(cols[1])
        if amt is None:
            continue
        # Description often last non-empty field or col 4+
        desc_parts = [c.strip() for c in cols[2:] if c and c.strip() and c.strip() != "*"]
        desc = " ".join(desc_parts) if desc_parts else "Wells Fargo transaction"
        rows.append(
            ParsedRow(
                date=dval,
                description=desc[:200],
                amount=abs(amt),
                is_income=amt > 0,
                raw=line,
            )
        )
    return rows


def _parse_dict_rows(reader: csv.DictReader, bank: str) -> list[ParsedRow]:
    fields = {_norm_header(f): f for f in (reader.fieldnames or []) if f}

    def pick(*cands: str) -> Optional[str]:
        for c in cands:
            c = c.lower()
            if c in fields:
                return fields[c]
        for key, original in fields.items():
            for c in cands:
                if c in key:
                    return original
        return None

    # Bank-specific column preference
    if bank == "chase":
        date_col = pick(
            "posting date",
            "transaction date",
            "post date",
            "date",
        )
        desc_col = pick("description", "memo", "details")
        amount_col = pick("amount")
        debit_col = None
        credit_col = None
        # Chase credit: Type CREDIT/DEBIT sometimes; amount signed
    elif bank == "bank_of_america":
        date_col = pick("date", "posted date")
        desc_col = pick("description", "payee", "memo")
        amount_col = pick("amount")
        debit_col = None
        credit_col = None
    elif bank == "citi":
        date_col = pick("date", "transaction date", "posted date")
        desc_col = pick("description", "memo", "payee")
        amount_col = pick("amount")
        debit_col = pick("debit", "withdrawal")
        credit_col = pick("credit", "deposit")
    elif bank == "us_bank":
        date_col = pick("date", "posted date", "transaction date")
        desc_col = pick("name", "description", "memo", "transaction")
        amount_col = pick("amount")
        debit_col = pick("debit", "withdrawal")
        credit_col = pick("credit", "deposit")
        # Combine name + memo when both exist
    elif bank == "wells_fargo":
        date_col = pick("date")
        desc_col = pick("description", "name", "payee")
        amount_col = pick("amount")
        debit_col = pick("withdrawals", "withdrawal", "debit")
        credit_col = pick("deposits", "deposit", "credit")
    else:
        date_col = pick(
            "posting date",
            "transaction date",
            "post date",
            "posted date",
            "date",
        )
        desc_col = pick(
            "description",
            "memo",
            "payee",
            "name",
            "details",
            "transaction",
        )
        amount_col = pick("amount", "value", "transaction amount")
        debit_col = pick("debit", "withdrawal", "withdrawals")
        credit_col = pick("credit", "deposit", "deposits")

    memo_col = pick("memo") if bank in ("chase", "us_bank") else None
    name_col = pick("name") if bank == "us_bank" else None
    type_col = pick("type") if bank == "chase" else None

    rows: list[ParsedRow] = []
    for line in reader:
        # Description
        desc = ""
        if bank == "us_bank" and name_col:
            desc = (line.get(name_col) or "").strip()
            if memo_col and (line.get(memo_col) or "").strip():
                memo = line.get(memo_col).strip()
                if memo and memo not in desc:
                    desc = f"{desc} — {memo}".strip(" —")
        elif desc_col:
            desc = (line.get(desc_col) or "").strip()
            if memo_col and bank == "chase":
                memo = (line.get(memo_col) or "").strip()
                if memo and memo not in desc:
                    desc = f"{desc} {memo}".strip()

        dval = _parse_date(line.get(date_col) or "") if date_col else None

        amount = 0.0
        is_income = False
        if amount_col and (line.get(amount_col) or "").strip():
            amt = _parse_amount(line.get(amount_col))
            if amt is None:
                continue
            # Chase Type column: CREDIT / SALE / DEBIT etc.
            t = (line.get(type_col) or "").strip().upper() if type_col else ""
            if t in ("CREDIT", "PAYMENT", "REFUND", "INTEREST", "RETURN"):
                is_income = True
                amount = abs(amt)
            elif t in ("DEBIT", "SALE", "FEE", "CHECK"):
                is_income = False
                amount = abs(amt)
            else:
                is_income = amt > 0
                amount = abs(amt)
        else:
            deb = _parse_amount(line.get(debit_col) or "") if debit_col else None
            cred = _parse_amount(line.get(credit_col) or "") if credit_col else None
            deb = abs(deb) if deb is not None else 0.0
            cred = abs(cred) if cred is not None else 0.0
            if cred and not deb:
                amount, is_income = cred, True
            elif deb:
                amount, is_income = deb, False
            elif cred:
                amount, is_income = cred, True
            else:
                continue

        if amount <= 0 and not desc:
            continue
        # Skip total/summary rows
        dl = desc.lower()
        if dl in ("total", "totals", "beginning balance", "ending balance"):
            continue

        rows.append(
            ParsedRow(
                date=dval,
                description=desc or "Imported",
                amount=round(amount, 2),
                is_income=is_income,
                raw=str(dict(line)),
            )
        )
    return rows


def _parse_date(s: str) -> Optional[date]:
    s = (s or "").strip().strip('"')
    if not s:
        return None
    # Strip time portion
    if " " in s and not re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}\s", s):
        s = s.split(" ")[0]
    for fmt in (
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%d/%m/%Y",
        "%Y/%m/%d",
        "%m-%d-%Y",
        "%m-%d-%y",
        "%d-%b-%Y",
        "%d-%b-%y",
        "%b %d, %Y",
        "%B %d, %Y",
    ):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(s: str) -> Optional[float]:
    if s is None:
        return None
    s = str(s).strip().strip('"')
    if not s or s in ("*", "—", "-", "–"):
        return None
    # Accounting: (123.45) = negative
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1]
    s = s.replace("$", "").replace(",", "").replace(" ", "")
    # Some exports use trailing -
    if s.endswith("-"):
        neg = True
        s = s[:-1]
    if s.startswith("+"):
        s = s[1:]
    try:
        val = float(s)
    except ValueError:
        return None
    if neg:
        val = -abs(val)
    return val
