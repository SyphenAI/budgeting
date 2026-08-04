# Household Money

A simple budget app for your household.

- Runs **on your Windows computer** (not on a website in the cloud)
- Keeps your money information **private on your PC**
- Helps with bills, paychecks, goals, debt plans, and simple savings/investments

You do **not** need to know how to code.

---

## Important: Windows Defender / “blocked” messages

On many Windows PCs, **Windows Defender** (or SmartScreen) will warn you about `.bat` files or Python. That is common for apps that are not from the Microsoft Store.

### If Windows blocks the app

Try these in order:

1. **Run as administrator (often required)**  
   - Right-click **`install.bat`** → **Run as administrator**  
   - Later, right-click **`start.bat`** → **Run as administrator**  
   - If Windows asks “Do you want to allow this app to make changes?”, click **Yes**

2. **SmartScreen “Windows protected your PC”**  
   - Click **More info**  
   - Click **Run anyway**

3. **Defender deleted or quarantined a file**  
   - Open **Windows Security** → **Virus & threat protection** → **Protection history**  
   - Find the blocked item related to this folder  
   - Choose **Allow** / **Restore**  
   - Optionally: **Manage settings** → **Exclusions** → **Add an exclusion** → **Folder**  
     and select this app folder (the one that contains `install.bat`)

4. **Still blocked**  
   - Temporarily turn off real-time protection, run `install.bat` / `start.bat`, then turn protection back on  
   - Or ask whoever manages the PC (work laptop policies can block this)

**Note:** Running as admin is for **installing and starting** the app on a locked-down PC. Your money data still stays on this computer. Only use admin when Windows will not let the app run otherwise.

---

## What you will do (overview)

1. **One-time setup** on the computer (about 15–20 minutes)  
2. **Start the app** with a double-click (or **Run as administrator** if Defender blocks it)  
3. **Sign in** in your web browser  
4. Enter your bills and income at your own pace  

---

## Before you start (one-time downloads)

You only need these if this computer does not already have them.

### 1) Python (required)

1. Open this page: [https://www.python.org/downloads/](https://www.python.org/downloads/)  
2. Click the big yellow **Download Python** button  
3. Run the installer  
4. **Very important:** on the first screen, check the box that says  
   **“Add python.exe to PATH”**  
5. Click **Install Now** and finish  

If you already installed Python earlier without that box, uninstall Python from Windows Settings, then install again with the box checked.

### 2) Get the app folder onto this computer

**Easiest if someone sent you a zip file**

1. Download the zip  
2. Right-click it → **Extract All…**  
3. Choose a simple place, such as:  
   `Documents\HouseholdMoney`  
4. Open the extracted folder  

**Or download from GitHub (website only — no typing)**

1. Open: [https://github.com/SyphenAI/budgeting](https://github.com/SyphenAI/budgeting)  
2. Click the green **Code** button  
3. Click **Download ZIP**  
4. Extract the zip as above  

---

## First-time setup

1. Open the app folder  
2. Find the file named **`install.bat`**  
3. Right-click it → **Run as administrator**  
   - (If that works without admin later, a normal double-click is fine)  
4. If Windows says it protected your PC: **More info** → **Run anyway**  
5. A black window will show progress — **wait until it says DONE**  
6. Press any key to close that window when finished  

That step may create a desktop shortcut named **Household Money** when possible.

---

## Every time you want to use the app

1. Right-click **`start.bat`** → **Run as administrator**  
   - (or double-click if your PC allows it)  
   - or use the **Household Money** shortcut if setup created one  
2. Wait until the window says **App is ready** (can take up to a minute the first time)  
3. Your browser should open to the app  
4. Leave the window titled **“Household Money - keep open”** running while you work  
5. When finished, close that **keep open** window  

If the browser opens but the page fails, wait 10 seconds and press **Refresh** (F5).

If the browser does not open, open Chrome or Edge and type exactly:

**http://127.0.0.1:8787**

### If the page still will not load

1. Look at the **“Household Money - keep open”** window for red error text  
2. Confirm you used **Run as administrator** if Defender was blocking things  
3. Run **`install.bat`** again (as admin), then **`start.bat`** (as admin)  
4. Restart the computer once, then try **`start.bat`** again  
5. Make sure you are using the folder that contains **both** `install.bat` and the `backend` folder (not an empty outer folder from the zip)

---


## Sign in (first time)

|  | Type this |
|--|-----------|
| Username | `admin` |
| Password | `admin` |

The app will then **make you choose a new password**.  
Pick something only you know. Do not share it with kids.

After that, you can add a spouse or partner login under **Household** if you want both adults to use it.

---

## What each screen is for

| Screen | What it’s for |
|--------|----------------|
| **Home** | Your month calendar, balances, and overview |
| **Money in / out** | Add bills, estimates, paychecks, real spending |
| **Pay stub** | Upload a pay stub PDF and put pay on the calendar |
| **Goals** | Things you are saving for (vacation, emergency fund, etc.) |
| **Debt plan** | Credit cards / loans — simple payoff plan |
| **Investments** | Simple “what is this account worth?” list |
| **Import** | Optional: bank CSV download (not PDF statements) |
| **Household** | Rename household, change password, add/remove people |

---

## Common problems

**“Python was not found” when I run install.bat**  
Install Python again and check **Add python.exe to PATH**, then run `install.bat` again.

**Browser shows “can’t connect” / page won’t load**  
- Run `start.bat` again and wait 5 seconds  
- Make sure you open **http://127.0.0.1:8787** (not google.com search)  
- Leave the black window open  

**I forgot my password**  
Someone technical can delete the file `data\budget.db` and run the app again.  
That resets logins **and** erases budget data on that computer — only do this if you accept losing that data.

**Kids got into the app**  
Change your password under **Household**, and use the 10-minute auto sign-out (already built in).

---

## Privacy (simple version)

- Your budget lives in a file on **this computer** (`data` folder)  
- It is **not** uploaded to GitHub when you download the app  
- Do not email pay stubs or bank statements into the app folder if you also share that folder with others  

---

## Getting a newer version (update)

When we release improvements, you can update **without losing your budget**.

1. Close the app (close any “Household Money - keep open” window)  
2. Open your app folder  
3. Right-click **`update.bat`** → **Run as administrator**  
4. Read the message, then press a key to continue  
5. Wait until it says **Update finished**  
6. Right-click **`start.bat`** → **Run as administrator**  

**What update does**
- Downloads the latest app from the official GitHub page only  
- Replaces program files  
- **Keeps** your `data` folder (balances, logins, entries)  
- Does **not** run in the background every time you start the app — you choose when to update  

**If update fails**
- Download a fresh ZIP from GitHub  
- Copy your old `data` folder into the new folder  
- Run `install.bat`, then `start.bat`  

---

## For helpers / advanced users only

Command-line and Docker instructions are optional. Most people should use **`install.bat`** and **`start.bat`** only.

```text
python -m venv .venv
.venv\Scripts\python -m pip install -r backend\requirements.txt
.venv\Scripts\python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8787
```

Docker: `docker compose up --build -d` then open http://localhost:8787

Developers: see `NOTES.md` for product design notes. Sample bank CSVs are in `samples/bank-csv/` (fake data only).
