# Household Money

Local-only household budget app: calendar cash plan, goals, debt payoff, simple investments, bank CSV import, and pay-stub helpers.

Runs on **your computer**. No cloud account required. Data stays in a local SQLite file.

## First-time login

| Username | Password | Notes |
|----------|----------|--------|
| `admin`  | `admin`  | You **must** set a new password on first login |

Then create partner/spouse logins under **Household** if needed.

## Install (Windows)

```powershell
git clone https://github.com/SyphenAI/budgeting.git
cd budgeting
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
uvicorn backend.app.main:app --host 127.0.0.1 --port 8787
```

Open **http://127.0.0.1:8787**

### Docker

```powershell
git clone https://github.com/SyphenAI/budgeting.git
cd budgeting
docker compose up --build -d
```

Open **http://localhost:8787** — data persists in `./data/budget.db` (never commit that file).

## Sister / non-tech install

See **[INSTALL.md](INSTALL.md)** for a plain-language walkthrough.

## What’s included

| Area | Purpose |
|------|---------|
| **Home** | Net worth snapshot, calendar (act/est), charts, upcoming |
| **Money in / out** | Bills, estimates, paychecks, actuals, bank balance |
| **Pay stub** | Upload PDF, review net/gross, put pay on calendar |
| **Goals** | Targets and progress |
| **Debt plan** | Avalanche / snowball math |
| **Investments** | Simple “what’s it worth?” buckets |
| **Import** | Bank CSV (Chase, BofA, Wells Fargo, Citi, U.S. Bank) |
| **Household** | Name, starting cash, people & permissions, password |

## Sample data only in this repo

- Fresh install seeds **generic sample** bills/paychecks (not real people).
- Bank CSV examples: `samples/bank-csv/` (fake merchants and amounts).
- **Not in git:** pay stubs, real statements, live database, tokens.

## Privacy checklist (before every push)

- [ ] No `*.pdf` pay stubs or statements  
- [ ] No `data/budget.db`  
- [ ] No `github_pat.txt` / `.env`  
- [ ] No real names, SSNs, account numbers in docs or samples  
- [ ] `git status` looks clean  

See `.gitignore` for full exclusions.

## Brand

Optional Syphen.AI styles in `brand/` (company CSS tokens). Product itself is household-facing.

## License / use

Private or public as you choose. Treat real household money data as **local only**.
