# Install on your computer (plain language)

This app runs **only on your laptop**. It does not need the internet after you download it (except the first setup, to install Python packages or Docker).

## What you need

1. A Windows computer  
2. About 15–20 minutes the first time  
3. Someone technical nearby for the first install if you want help  

---

## Option A — Easy path if someone sets it up once

1. They install the app and create a desktop shortcut or start script.  
2. You open the browser to **http://127.0.0.1:8787**  
3. Sign in with the username/password they give you (not shared with kids).  

Your money data stays in a file on **this** computer.

---

## Option B — Install from GitHub (with help)

### 1. Install tools (one time)

- **Git** — https://git-scm.com/download/win  
- **Python 3.12+** — https://www.python.org/downloads/  
  - During install, check **“Add python.exe to PATH”**

### 2. Download the app

Open **PowerShell** and run:

```powershell
cd $HOME\Documents
git clone https://github.com/SyphenAI/budgeting.git
cd budgeting
```

### 3. Install and start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
uvicorn backend.app.main:app --host 127.0.0.1 --port 8787
```

Leave that window open. Open a browser to:

**http://127.0.0.1:8787**

### 4. First login

- Username: `admin`  
- Password: `admin`  
- The app will **force you to pick a new password** — choose one only you know.

### 5. Optional — spouse / partner login

Go to **Household → People & logins**  
Add them as **Partner** so both adults can use the full app.

### 6. Next times you use it

```powershell
cd $HOME\Documents\budgeting
.\.venv\Scripts\Activate.ps1
uvicorn backend.app.main:app --host 127.0.0.1 --port 8787
```

Then open **http://127.0.0.1:8787** again.

---

## Safety notes

- **Do not** email or commit pay stubs, bank PDFs, or your `data` folder.  
- After 10 minutes of no activity, the app signs you out (shared computer safety).  
- Kids should not get the password.

## Updates (later)

```powershell
cd $HOME\Documents\budgeting
git pull
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
```

Your `data\budget.db` file is not in GitHub — updates should not wipe it if you only `git pull`.

---

## If something breaks

1. Make sure the PowerShell window is still running.  
2. Try the address **http://127.0.0.1:8787** again.  
3. Ask your helper to check that port **8787** is free.  
