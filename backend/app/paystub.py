"""
Pay stub PDF helpers — text extract + heuristic field finders.

Works best on text-based (digital) PDFs. Scanned image PDFs need OCR (not included).
Nothing is sent online; parsing is local.
"""

from __future__ import annotations

import io
import re
from calendar import monthrange
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional


@dataclass
class PayStubParse:
    employer: str = ""
    employee_name: str = ""
    pay_date: Optional[date] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    gross_pay: Optional[float] = None
    net_pay: Optional[float] = None
    federal_tax: Optional[float] = None
    state_tax: Optional[float] = None
    social_security: Optional[float] = None
    medicare: Optional[float] = None
    retirement: Optional[float] = None
    health_insurance: Optional[float] = None
    other_deductions: Optional[float] = None
    frequency_guess: str = "biweekly"  # weekly|biweekly|semimonthly|monthly
    monthly_net_estimate: Optional[float] = None
    monthly_gross_estimate: Optional[float] = None
    confidence: str = "low"  # low|medium|high
    notes: list[str] = field(default_factory=list)
    raw_text_preview: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("pay_date", "period_start", "period_end"):
            if d[k] is not None:
                d[k] = d[k].isoformat()
        return d


def extract_pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    parts: list[str] = []
    for page in reader.pages:
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        if t:
            parts.append(t)
    text = "\n".join(parts)
    # Normalize whitespace for regex
    text = text.replace("\u00a0", " ")
    return text


def parse_paystub_pdf(data: bytes) -> PayStubParse:
    text = extract_pdf_text(data)
    result = PayStubParse()
    if not text or len(text.strip()) < 20:
        result.notes.append(
            "Little or no text found. This may be a scanned image PDF — "
            "text-based pay stubs work best. You can still enter amounts by hand."
        )
        result.confidence = "low"
        return result

    result.raw_text_preview = text[:2500]
    flat = re.sub(r"[ \t]+", " ", text)
    lower = flat.lower()

    # --- Money fields (common labels) ---
    result.net_pay = _first_money(
        flat,
        [
            r"net\s*pay[:\s]+\$?\s*([\d,]+\.\d{2})",
            r"net\s*pay[:\s]+\$?\s*([\d,]+)",
            r"take[\s-]*home(?:\s*pay)?[:\s]+\$?\s*([\d,]+\.\d{2})",
            r"net\s*amount[:\s]+\$?\s*([\d,]+\.\d{2})",
            r"direct\s*deposit[:\s]+\$?\s*([\d,]+\.\d{2})",
            r"total\s*net[:\s]+\$?\s*([\d,]+\.\d{2})",
        ],
    )
    result.gross_pay = _first_money(
        flat,
        [
            r"gross\s*pay[:\s]+\$?\s*([\d,]+\.\d{2})",
            r"current\s*gross[:\s]+\$?\s*([\d,]+\.\d{2})",
            r"gross\s*earnings[:\s]+\$?\s*([\d,]+\.\d{2})",
            r"total\s*gross[:\s]+\$?\s*([\d,]+\.\d{2})",
            r"gross\s*wages[:\s]+\$?\s*([\d,]+\.\d{2})",
        ],
    )

    result.federal_tax = _first_money(
        flat,
        [
            r"federal\s*income\s*tax[:\s]+\$?\s*([\d,]+\.\d{2})",
            r"fed(?:eral)?\s*tax[:\s]+\$?\s*([\d,]+\.\d{2})",
            r"withholding\s*fed[:\s]+\$?\s*([\d,]+\.\d{2})",
            r"FIT[:\s]+\$?\s*([\d,]+\.\d{2})",
        ],
    )
    result.state_tax = _first_money(
        flat,
        [
            r"state\s*income\s*tax[:\s]+\$?\s*([\d,]+\.\d{2})",
            r"state\s*tax[:\s]+\$?\s*([\d,]+\.\d{2})",
            r"SIT[:\s]+\$?\s*([\d,]+\.\d{2})",
        ],
    )
    result.social_security = _first_money(
        flat,
        [
            r"social\s*security[:\s]+\$?\s*([\d,]+\.\d{2})",
            r"oasdi[:\s]+\$?\s*([\d,]+\.\d{2})",
            r"\bFICA\b[:\s]+\$?\s*([\d,]+\.\d{2})",
            r"SS\s*tax[:\s]+\$?\s*([\d,]+\.\d{2})",
        ],
    )
    result.medicare = _first_money(
        flat,
        [
            r"medicare[:\s]+\$?\s*([\d,]+\.\d{2})",
            r"med\s*tax[:\s]+\$?\s*([\d,]+\.\d{2})",
        ],
    )
    result.retirement = _first_money(
        flat,
        [
            r"401\s*\(?k\)?[:\s]+\$?\s*([\d,]+\.\d{2})",
            r"403\s*\(?b\)?[:\s]+\$?\s*([\d,]+\.\d{2})",
            r"retirement[:\s]+\$?\s*([\d,]+\.\d{2})",
            r"deferred\s*comp[:\s]+\$?\s*([\d,]+\.\d{2})",
            r"TSP[:\s]+\$?\s*([\d,]+\.\d{2})",
        ],
    )
    result.health_insurance = _first_money(
        flat,
        [
            r"health\s*insurance[:\s]+\$?\s*([\d,]+\.\d{2})",
            r"medical[:\s]+\$?\s*([\d,]+\.\d{2})",
            r"health\s*premium[:\s]+\$?\s*([\d,]+\.\d{2})",
            r"dental[:\s]+\$?\s*([\d,]+\.\d{2})",
        ],
    )

    # --- Dates ---
    result.pay_date = _first_date(
        flat,
        [
            r"pay\s*date[:\s]+([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})",
            r"check\s*date[:\s]+([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})",
            r"payment\s*date[:\s]+([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})",
            r"paid\s*on[:\s]+([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})",
            r"pay\s*date[:\s]+([A-Za-z]{3,9}\s+[0-9]{1,2},?\s+[0-9]{4})",
        ],
    )
    # Period range: 01/01/2026 - 01/15/2026
    m = re.search(
        r"(?:pay\s*period|period\s*(?:start|ending|from)?|period)[:\s]*"
        r"([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})"
        r"\s*[-–to]+\s*"
        r"([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})",
        flat,
        re.I,
    )
    if m:
        result.period_start = _parse_date(m.group(1))
        result.period_end = _parse_date(m.group(2))
    else:
        result.period_start = _first_date(
            flat,
            [
                r"period\s*beginning[:\s]+([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})",
                r"period\s*start[:\s]+([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})",
                r"from[:\s]+([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})",
            ],
        )
        result.period_end = _first_date(
            flat,
            [
                r"period\s*ending[:\s]+([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})",
                r"period\s*end[:\s]+([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})",
                r"through[:\s]+([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})",
            ],
        )

    # Employer — first line-ish company cues
    emp = re.search(
        r"(?:employer|company|organization)[:\s]+([A-Za-z0-9&.,'\- ]{3,60})",
        flat,
        re.I,
    )
    if emp:
        result.employer = emp.group(1).strip()[:80]
    else:
        # Sometimes top of stub is employer name (first non-empty line)
        for line in text.splitlines():
            line = line.strip()
            if len(line) >= 3 and not re.search(r"\d{2}[/-]\d{2}", line):
                if not re.search(r"pay\s*stub|earnings|statement|employee", line, re.I):
                    if re.search(r"[A-Za-z]{3,}", line):
                        result.employer = line[:80]
                        break

    # Frequency guess from period length
    if result.period_start and result.period_end:
        days = (result.period_end - result.period_start).days + 1
        if days <= 8:
            result.frequency_guess = "weekly"
        elif days <= 16:
            result.frequency_guess = "biweekly"
        elif days <= 18:
            result.frequency_guess = "semimonthly"
        else:
            result.frequency_guess = "monthly"
    elif "bi-weekly" in lower or "biweekly" in lower or "bi weekly" in lower:
        result.frequency_guess = "biweekly"
    elif "semi-monthly" in lower or "semimonthly" in lower or "semi monthly" in lower:
        result.frequency_guess = "semimonthly"
    elif "weekly" in lower:
        result.frequency_guess = "weekly"
    elif "monthly" in lower:
        result.frequency_guess = "monthly"

    result.monthly_net_estimate = monthly_equivalent(result.net_pay, result.frequency_guess)
    result.monthly_gross_estimate = monthly_equivalent(
        result.gross_pay, result.frequency_guess
    )

    # Confidence
    hits = sum(
        1
        for v in (result.net_pay, result.gross_pay, result.pay_date, result.period_end)
        if v is not None
    )
    if hits >= 3:
        result.confidence = "high"
    elif hits >= 2:
        result.confidence = "medium"
    else:
        result.confidence = "low"
        result.notes.append(
            "Only a few fields were found. Review and fix amounts before saving."
        )

    if result.net_pay and result.gross_pay and result.net_pay > result.gross_pay:
        result.notes.append(
            "Net looks larger than gross — labels may have been swapped; double-check."
        )

    return result


def monthly_equivalent(amount: Optional[float], frequency: str) -> Optional[float]:
    if amount is None:
        return None
    freq = (frequency or "biweekly").lower()
    mult = {
        "weekly": 52 / 12,
        "biweekly": 26 / 12,
        "semimonthly": 24 / 12,
        "monthly": 1.0,
    }.get(freq, 26 / 12)
    return round(float(amount) * mult, 2)


def next_pay_dates(
    from_date: date,
    frequency: str,
    count: int = 6,
) -> list[date]:
    """Generate upcoming pay dates from a known pay date (inclusive of from_date)."""
    freq = (frequency or "biweekly").lower()
    dates = [from_date]
    d = from_date
    for _ in range(max(count - 1, 0)):
        if freq == "weekly":
            d = d + timedelta(days=7)
        elif freq == "biweekly":
            d = d + timedelta(days=14)
        elif freq == "semimonthly":
            # 1st and 15th style: jump toward next semi
            if d.day < 15:
                d = d.replace(day=15)
            else:
                y, m = d.year, d.month + 1
                if m > 12:
                    y, m = y + 1, 1
                d = date(y, m, 1)
        else:  # monthly — same day next month
            y, m = d.year, d.month + 1
            if m > 12:
                y, m = y + 1, 1
            last = monthrange(y, m)[1]
            d = date(y, m, min(from_date.day, last))
        dates.append(d)
    return dates


def _first_money(text: str, patterns: list[str]) -> Optional[float]:
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def _first_date(text: str, patterns: list[str]) -> Optional[date]:
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            d = _parse_date(m.group(1))
            if d:
                return d
    return None


def _parse_date(s: str) -> Optional[date]:
    s = (s or "").strip()
    for fmt in (
        "%m/%d/%Y",
        "%m/%d/%y",
        "%m-%d-%Y",
        "%m-%d-%y",
        "%Y-%m-%d",
        "%b %d, %Y",
        "%B %d, %Y",
        "%b %d %Y",
        "%B %d %Y",
    ):
        try:
            return datetime.strptime(s.replace(",", ""), fmt.replace(",", "")).date()
        except ValueError:
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
    return None
