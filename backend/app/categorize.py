"""Suggest budget buckets for imported bank lines (local heuristics only)."""

from __future__ import annotations

import re


# Shown in Import UI
IMPORT_CATEGORIES = [
    "Income",
    "Housing",
    "Utilities",
    "Electric",
    "Water",
    "Internet / Phone",
    "Insurance",
    "Groceries / Food",
    "Gas / Transport",
    "Credit card payment",
    "Transfer",
    "Medical",
    "Shopping",
    "Subscriptions",
    "Kids",
    "Debt payment",
    "Savings / Investment",
    "Fees",
    "Other",
    "Imported",
]


def suggest_category(description: str, is_income: bool) -> str:
    d = (description or "").lower()
    if is_income:
        return "Income"

    rules: list[tuple[str, tuple[str, ...]]] = [
        ("Electric", ("electric", "sumter electric", "duke energy", "power company", "utility electric")),
        ("Water", ("water", "utility water", "grovelan", "sewer")),
        ("Internet / Phone", ("verizon", "at&t", "att ", "t-mobile", "comcast", "xfinity", "spectrum", "wireless")),
        ("Insurance", ("insurance", "state farm", "geico", "progressive", "allstate", "farm bureau", "usaa fsb cc")),
        ("Housing", ("mortgage", "pennymac", "rent", "hoa", "property")),
        ("Groceries / Food", ("publix", "kroger", "walmart", "aldi", "costco", "sams club", "grocery", "target", "wholefds", "trader joe")),
        ("Gas / Transport", ("shell", "chevron", "exxon", "bp ", "circle k", "gas station", "uber", "lyft")),
        ("Credit card payment", ("payment to chase card", "credit crd", "crcardpmt", "citi autopay", "capital one", "synchrony", "card ending")),
        ("Transfer", ("online transfer", "trnsfer", "transfer to", "zelle payment to", "paypal")),
        ("Savings / Investment", ("fidelity", "vanguard", "schwab", "moneyline", "brokerage", "robinhood")),
        ("Medical", ("pharmacy", "cvs", "walgreens", "hospital", "clinic", "dental", "health")),
        ("Subscriptions", ("netflix", "spotify", "hulu", "disney", "prime video", "apple.com/bill")),
        ("Kids", ("school", "daycare", "childcare", "toys")),
        ("Fees", ("fee", "service charge", "overdraft", "nsf")),
        ("Shopping", ("amazon", "amzn", "ebay", "etsy")),
    ]
    for cat, keys in rules:
        if any(k in d for k in keys):
            return cat
    return "Other"


def is_credit_card_category(category: str, description: str = "") -> bool:
    cat = (category or "").lower()
    if "credit card" in cat or cat == "debt payment":
        return True
    d = (description or "").lower()
    return any(
        k in d
        for k in (
            "payment to chase card",
            "credit crd",
            "crcardpmt",
            "citi autopay",
            "capital one",
            "card ending",
            "synchrony bank",
        )
    )


def suggest_card_name(description: str) -> str:
    """
    Pull a short card label from bank description for debt-plan linking.
    Examples:
      Payment To Chase Card Ending IN 3002 → Chase Card …3002
      Chase Credit Crd Autopay → Chase Credit Card
      Capital One Crcardpmt … → Capital One
    """
    d = re.sub(r"\s+", " ", (description or "").strip())
    if not d:
        return "Credit card"

    m = re.search(r"chase card ending\s*(?:in\s*)?(\d{4})", d, re.I)
    if m:
        return f"Chase Card …{m.group(1)}"

    m = re.search(r"card ending\s*(?:in\s*)?(\d{4})", d, re.I)
    if m:
        brand = "Card"
        if "chase" in d.lower():
            brand = "Chase"
        elif "citi" in d.lower():
            brand = "Citi"
        elif "capital one" in d.lower():
            brand = "Capital One"
        return f"{brand} Card …{m.group(1)}"

    if re.search(r"chase credit crd|chase credit card", d, re.I):
        return "Chase Credit Card"
    if re.search(r"citi autopay|citi card", d, re.I):
        return "Citi Card"
    if re.search(r"capital one", d, re.I):
        return "Capital One"
    if re.search(r"synchrony", d, re.I):
        return "Synchrony"
    if re.search(r"usaa.*cc|cc payment", d, re.I):
        return "USAA Credit Card"
    if re.search(r"amex|american express", d, re.I):
        return "Amex"
    if re.search(r"discover", d, re.I):
        return "Discover"

    # Fallback: first few words
    words = d.split()
    return " ".join(words[:4])[:80]
