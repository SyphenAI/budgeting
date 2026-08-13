# Product notes (public-safe)

Design notes for the Household Money app. No personal or household-specific data.

## Audience

- Non-technical household users
- Local install (Windows + Docker Desktop)
- Listens on port **50100**, bound to `0.0.0.0` so other devices on the home `192.` LAN can open it
- Optional second adult login (partner)
- Simple gate so kids cannot open the app easily

## Core features

- Month calendar with bill / estimate / paycheck / actual pills
- Dual running balances: **act** (confirmed) and **est** (plan including estimates)
- Bank balance entry resets running totals from that date
- Goals with target amount/date and suggested monthly savings
- Debt paydown: avalanche vs snowball (rule-based, no AI)
- Simple investment buckets (manual value updates)
- CSV import for major US banks (Chase, BofA, Wells, Citi, U.S. Bank)
- Pay stub PDF parse (local text extract; review before save)
- Auth: first login `admin` / `admin` → force password change
- Roles: owner, partner, member, viewer
- 10-minute idle sign-out
- Household settings: Check / Update now (keeps the data folder)
- Recurring bills/pay auto-extend into later months
- Idle timeout default 30 minutes (set under Household)
- Rescue code resets a password without wiping data
- Monthly local copies in data/backups

## Non-goals (v1)

- Live bank APIs / Plaid
- Cloud requirement
- PDF bank statement OCR
- Public multi-tenant SaaS billing

## Privacy for this repo

- No real pay stubs, statements, or live `data/*.db`
- Sample CSVs under `samples/bank-csv/` only
- Secrets (`github_pat.txt`, `.env`) gitignored
