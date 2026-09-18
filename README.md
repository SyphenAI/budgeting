# Household Money

A family budget that lives on **your** Windows computer. Bills, pay, cards, and a month calendar. Nothing is sent to a bank app or the cloud.

You do **not** need to know how to code.

---

## What you are installing

Household Money is a small website that only runs on your PC. To start it, you install one free helper from Docker called **Docker Desktop**. Think of it as a box that runs the budget so you do not have to install Python or other developer tools.

You will:

1. Install Docker Desktop (one time)
2. Put this app in a folder
3. Double-click a Start file
4. Sign in in your browser

---

## What you need

- A Windows PC (Windows 10 or 11)
- About 15 minutes the first time
- Internet for the first install and later updates
- [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/) (free)

A phone is optional. You can use the app on a phone **on the same home Wi‑Fi** after it is running on the PC.

---

## Step 1 — Install Docker Desktop (one time)

1. Open [https://www.docker.com/products/docker-desktop/](https://www.docker.com/products/docker-desktop/)
2. Download **Docker Desktop for Windows**
3. Run the installer. If it asks to restart, restart.
4. After restart, open **Docker Desktop** from the Start menu (whale icon).
5. Wait until it says it is **running**. The first launch can take a few minutes. Sign in to a Docker account only if it asks — you can skip / use it without paying.

Leave Docker Desktop open whenever you want to use Household Money. Closing it is like turning the budget off (your numbers stay saved).

**If Windows says virtualization is off:** that is a PC setting, not the budget. Search Windows for **Windows features**, turn on **Hyper-V** or **Windows Hypervisor Platform** if the Docker installer tells you to, then restart.

---

## Step 2 — Get this app onto the PC

**Easiest:** on GitHub, click the green **Code** button → **Download ZIP**. Unzip it to a simple place, for example:

`Documents\HouseholdMoney`

Keep the whole folder. Do not delete files inside it.

If someone already put the folder on this PC, skip this step.

---

## Step 3 — Start Household Money (first time)

1. Open **Docker Desktop** and wait until it is running.
2. In File Explorer, open the Household Money folder.
3. Right-click **`docker-start.bat`** → **Run as administrator**.
   - Administrator is so Windows can let a phone on your Wi‑Fi open the page.
   - If a blue **Windows protected your PC** box appears: **More info** → **Run anyway**.
4. The first start **builds** the app. That can take several minutes. A black window will show progress. Leave it alone.
5. When it says the app is ready, your browser should open to:

**http://127.0.0.1:50100**

If the browser does not open, copy that address into Edge or Chrome. Type it in the address bar — do not Google it.

You should see a sign-in page.

---

## Step 4 — First sign-in

|  | Type this |
|--|-----------|
| Username | `admin` |
| Password | `admin` |

The app will make you **change the password**. Pick something only your household knows. Four characters is the minimum; longer is better.

It will also show a **rescue code** (a string of letters). **Write it on paper** and keep it with other household papers.

If you forget the password later, on the sign-in page tap **I forgot my password** and type that code. The budget is **not** erased.

You can add another adult under **Household** later (partner, etc.).

---

## Step 5 — First use (about 20 minutes)

Do this in order. You can skip a screen and come back.

### 1. Home — cash on hand

On **Home**, log **what checking shows today** if the app asks, or add a **Bank balance** on today’s date (Money in / out → type **Bank balance**). That number is the starting cash for the green “act” total.

### 2. Recurring — bills and pay that happen every month

Open **Recurring** on the left.

Add the things that always come back:

- Mortgage / rent  
- Car payment  
- Electric, water, phone  
- Insurance  
- **Pay / VA** as type **Paycheck / income**

For **every 2 weeks** pay, choose **Every 2 weeks** and the **first payday** (example: Oct 16). It will not invent paydays *before* that date.

**Water and electric:** when this month’s bill is different, change **This month** only. Change **Usual** when the rate really changed.

### 3. Cards — credit cards (optional but useful)

Open **Cards**. Upload a **credit card PDF** from the card website (not a photo). Check:

- New balance  
- APR (type it if the PDF left it blank)  
- **What I auto-pay** (if you pay more than the minimum, put that higher number)

Save. That feeds **Debt plan**. You can put the auto-pay on the calendar as **Card min**.

Checking statements are different — those go under **Import**, not Cards.

### 4. Import — bank checking PDF or CSV (optional)

**Import** → bank **Chase checking** (or Auto) → Preview → tick rows → **Import selected**.

Preview **adds** files; it does not replace the last file. Checking activity shows on the calendar for that month. Card **charges** stay on **Cards**.

### 5. Glance at Home

- **This month** tile: spent / income  
- Chart: **Income**, **Paid** (bills you marked paid), **Still due**  
- Calendar: tap a day to mark a bill **Paid**

You are ready for normal use.

---

## Every time you open it

1. Start **Docker Desktop** and wait until it is running.
2. Right-click **`docker-start.bat`** → **Run as administrator** (or double-click if your PC allows it).
3. Use **http://127.0.0.1:50100**
4. When finished, double-click **`docker-stop.bat`**. You can also quit Docker Desktop.

Your budget lives in the **`data`** folder. Stopping the app does **not** delete it.

---

## What each screen is for

| Screen | What it’s for |
|--------|----------------|
| **Home** | Month calendar, cash, spent/income, charts |
| **Money in / out** | One-time items, bank balance, edits |
| **Recurring** | Monthly / every-2-weeks bills and pay |
| **Pay stub** | Job PDF + “put pay on the calendar” |
| **Cards** | Credit card PDFs, APR, auto-pay, repeating card charges |
| **Subscriptions** | Streaming / Apple-style repeats |
| **Goals** | Savings targets |
| **Debt plan** | Avalanche vs snowball using your cards |
| **Investments** | “What is this account worth?” |
| **Import** | Checking CSV or Chase checking PDF |
| **Household** | People, password, rescue code, backups, **Update now** |

---

## Phone or another computer (same house)

The start window prints an address like **http://192.168.1.50:50100**. Open that on the phone’s browser. Same Wi‑Fi, not guest Wi‑Fi, not cellular.

If the PC works but the phone does not:

- Run **`docker-start.bat` as administrator** once  
- Windows Security → Firewall → allow **TCP 50100** on **Private** networks  

---

## Getting a newer version

1. Sign in → **Household** → **App updates**  
2. **Check for a newer version** → **Update now**  
3. Wait. Bills and passwords stay on this computer.

Needs internet. If the button cannot run: **`docker-stop.bat`**, then right-click **`update.bat`** → **Run as administrator**, then start again.

---

## Common problems

**“Docker was not found” or “not running”**  
Open Docker Desktop, wait until it is running, run `docker-start.bat` again.

**Browser can’t connect**  
Docker Desktop must be running. Wait 10 seconds and refresh. Use **http://127.0.0.1:50100** in the address bar.

**SmartScreen blocked the `.bat` file**  
More info → Run anyway. Or right-click → Run as administrator.

**Forgot password**  
Sign-in page → **I forgot my password** → rescue code. Budget stays. If nobody has a rescue code, a person who can still sign in should open **Household** → **Make a rescue code**.

**I changed a bill date and the old date is still there**  
On **Recurring**, change **Due day** and tap **Usual** (later months) or **This month**. Then refresh Home.

**Paycheck showed up before the first day I picked**  
Set the first payday on Recurring / Pay stub. Deletes of dates *before* that first payday should stay gone after a refresh.

---

## Privacy

- Numbers live in **`data`** on this PC (`budget.db`).  
- Do not email that file, pay stubs, or bank PDFs.  
- Do not put passwords in the GitHub folder.

---

## For the person who set this up

Family members only need Docker Desktop and the Start / Stop files. The Python `install.bat` path is for you, not for them.
