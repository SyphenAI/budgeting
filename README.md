# Household Money

A simple budget app that runs on your own computer.

- Bills, paychecks, goals, debt plans, and simple savings
- Your data stays in a local `data` folder (not in the cloud)
- No coding required

The recommended way to run it on Windows is **Docker Desktop**.

---

## What you need

1. [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/)
2. This app folder (clone or download the ZIP from this repository)

You do **not** need to install Python if you use Docker.

---

## First-time setup (Windows + Docker Desktop)

1. Install Docker Desktop and restart if the installer asks you to.
2. Open **Docker Desktop** and wait until it says it is running.
3. Put this project in an easy folder, such as `Documents\HouseholdMoney`.
4. Open that folder in File Explorer.
5. Right-click **`docker-start.bat`** → **Run as administrator**.
   - Administrator is so Windows Firewall can allow other devices on your home network.
   - If SmartScreen says “Windows protected your PC”: **More info** → **Run anyway**.
6. The first start can take a few minutes while Docker builds the app.
7. When it says the app is ready, your browser should open to:

**http://127.0.0.1:50100**

If the browser does not open, type that address into Chrome or Edge.

---

## Every time you want to use the app

1. Start **Docker Desktop** and wait until it is running.
2. Right-click **`docker-start.bat`** → **Run as administrator** (or double-click if your PC allows it).
3. Leave **Docker Desktop** running while you use the app. Closing it closes the app.
4. When finished, double-click **`docker-stop.bat`**.

Your budget stays in the `data` folder. Stopping Docker does not erase it.

Monthly bills and every-2-weeks pay keep showing up in later months by themselves. You do not need to copy last month.

---

## Sign in (first time)

|  | Type this |
|--|-----------|
| Username | `admin` |
| Password | `admin` |

The app will ask you to choose a **new password**. Pick one only you know.

You can add another adult login later under **Household**.

The app will also show a **rescue code**. Write it on paper. If you forget the password later, tap **I forgot my password** on the sign-in page and type that code. The budget is not erased.

---

## Use it from a phone or another computer

The app listens on **port 50100** on the computer running Docker, including that computer’s `192.` address.

1. On the computer running the app, look at the `docker-start.bat` window.
2. It prints a line like **http://192.168.x.x:50100**.
3. On the other device, open that address in a browser.
4. Use the same login.

The other device must be on the **same Wi-Fi or home network**. Guest Wi-Fi, VPN, and cellular data often block this.

If the page works on the Docker computer but not on a phone:

- Run **`docker-start.bat` as administrator** once so the firewall rule is added
- In **Windows Security** → **Firewall**, allow inbound **TCP 50100** on **Private** networks
- Confirm the phone is on the same `192.` network

---

## What each screen is for

| Screen | What it’s for |
|--------|----------------|
| **Home** | Month calendar, balances, and overview |
| **Money in / out** | Bills, estimates, paychecks, real spending |
| **Pay stub** | Upload a pay stub PDF and put pay on the calendar |
| **Goals** | Savings targets (vacation, emergency fund, etc.) |
| **Debt plan** | Credit cards / loans — simple payoff plan |
| **Investments** | Simple “what is this account worth?” list |
| **Import** | Optional bank CSV or supported PDF statement import |
| **Household** | Rename household, change password, add/remove people |

---

## Common problems

**Docker was not found / Docker is not running**  
Install Docker Desktop, open it, wait until it says it is running, then run `docker-start.bat` again.

**Browser shows “can’t connect”**  
- Confirm Docker Desktop is running  
- Wait 10 seconds and refresh  
- Open **http://127.0.0.1:50100** exactly (do not search for it in Google)  
- Run `docker-start.bat` again  

**Windows blocked the `.bat` file**  
Right-click → **Run as administrator**. On SmartScreen: **More info** → **Run anyway**.

**Forgot the password**  
On the sign-in page tap **I forgot my password**. Type the rescue code you wrote down and a new password. The budget stays.

If you never made a rescue code, someone who can still sign in should open **Household** and tap **Make a rescue code**.

**Phone cannot load the page**  
See [Use it from a phone or another computer](#use-it-from-a-phone-or-another-computer). The phone must be on the same local network, and Windows Firewall must allow port **50100**.

---

## Privacy

- Budget data lives in the `data` folder on the computer running the app
- That folder is not uploaded when you download this project
- Do not commit or email pay stubs, bank statements, or `data\budget.db`

---

## Getting a newer version

Easiest (no extra files):

1. Sign in
2. Open **Household** on the left
3. Find **App updates**
4. Tap **Check for a newer version**
5. If it says a newer version is ready, tap **Update now**
6. Wait. The page comes back by itself. Your bills and passwords stay on this computer.

The computer needs internet for this step.

If the button cannot run:

1. Double-click **`docker-stop.bat`**
2. Right-click **`update.bat`** → **Run as administrator**
3. When it finishes, run **`docker-start.bat`** again

---

## For the person who set this up

Family members should use Docker Desktop only. The Python `install.bat` path is for you, not for them.
