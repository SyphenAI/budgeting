"""Suggest budget buckets for imported bank lines (local heuristics only)."""

from __future__ import annotations

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
