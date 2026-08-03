/* Household Money — frontend */
(() => {
  const IDLE_MS = 10 * 60 * 1000; // 10 minutes — local shared-PC safety

  const state = {
    token: localStorage.getItem("budget_token") || "",
    user: null,
    year: new Date().getFullYear(),
    month: new Date().getMonth() + 1,
    names: [],
    charts: { category: null, income: null },
    calendar: null,
    selectedDate: null,
    idleTimer: null,
    lastActivity: Date.now(),
  };

  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

  /** Inline help icon HTML for dynamic sections */
  function helpBtn(text) {
    return `<button type="button" class="help-icon" data-help="${escapeAttr(text)}">?</button>`;
  }

  let helpTipEl = null;
  let helpOpenBtn = null;

  function ensureHelpTip() {
    if (helpTipEl) return helpTipEl;
    helpTipEl = document.createElement("div");
    helpTipEl.className = "help-tip";
    helpTipEl.setAttribute("role", "tooltip");
    document.body.appendChild(helpTipEl);
    return helpTipEl;
  }

  function hideHelp() {
    if (helpTipEl) helpTipEl.classList.remove("visible");
    if (helpOpenBtn) {
      helpOpenBtn.classList.remove("open");
      helpOpenBtn = null;
    }
  }

  function showHelp(btn) {
    const text = btn.getAttribute("data-help");
    if (!text) return;
    const tip = ensureHelpTip();
    tip.textContent = text;
    tip.classList.add("visible");
    btn.classList.add("open");
    helpOpenBtn = btn;

    // Position near the button (prefer below; flip if near bottom)
    const r = btn.getBoundingClientRect();
    const tipW = Math.min(280, window.innerWidth - 16);
    tip.style.width = tipW + "px";
    // force layout for height
    const th = tip.offsetHeight || 80;
    let left = r.left + r.width / 2 - tipW / 2;
    left = Math.max(8, Math.min(left, window.innerWidth - tipW - 8));
    let top = r.bottom + 8;
    if (top + th > window.innerHeight - 8) {
      top = Math.max(8, r.top - th - 8);
    }
    tip.style.left = left + "px";
    tip.style.top = top + "px";
  }

  function wireHelp() {
    document.addEventListener("click", (e) => {
      const btn = e.target.closest(".help-icon");
      if (btn && btn.dataset.help) {
        e.preventDefault();
        e.stopPropagation();
        if (helpOpenBtn === btn) {
          hideHelp();
        } else {
          hideHelp();
          showHelp(btn);
        }
        return;
      }
      hideHelp();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") hideHelp();
    });
    window.addEventListener("scroll", hideHelp, true);
    window.addEventListener("resize", hideHelp);
  }

  function money(n) {
    const v = Number(n) || 0;
    return v.toLocaleString(undefined, { style: "currency", currency: "USD" });
  }

  function monthName(y, m) {
    return new Date(y, m - 1, 1).toLocaleString(undefined, {
      month: "long",
      year: "numeric",
    });
  }

  async function api(path, options = {}) {
    const headers = { ...(options.headers || {}) };
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    if (options.json) {
      headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(options.json);
      delete options.json;
    }
    const res = await fetch(path, { ...options, headers });
    if (res.status === 401) {
      let detail = "Please sign in again";
      try {
        const j = await res.json();
        if (j.detail) detail = typeof j.detail === "string" ? j.detail : detail;
      } catch (_) {}
      logout(false);
      const err = $("#login-error");
      if (err && /idle/i.test(detail)) {
        err.textContent = detail;
        err.classList.add("show");
      }
      throw new Error(detail);
    }
    if (!res.ok) {
      let detail = "Request failed";
      try {
        const j = await res.json();
        detail = j.detail || detail;
      } catch (_) {}
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    // Successful authenticated traffic counts as activity
    if (state.token && path.startsWith("/api/") && path !== "/api/login") {
      touchActivity();
    }
    if (res.status === 204) return null;
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) return res.json();
    return res.text();
  }

  function showApp(show) {
    $("#login-view").classList.toggle("hidden", show);
    $("#app-shell").classList.toggle("visible", show);
  }

  function showPasswordGate(show) {
    const gate = $("#pw-gate");
    if (!gate) return;
    gate.hidden = !show;
    if (show) {
      const err = $("#pw-gate-error");
      if (err) {
        err.classList.remove("show");
        err.textContent = "";
      }
      const cur = $("#pw-current");
      if (cur) {
        cur.value = "";
        setTimeout(() => cur.focus(), 50);
      }
      if ($("#pw-new")) $("#pw-new").value = "";
      if ($("#pw-new2")) $("#pw-new2").value = "";
    }
  }

  function roleLabel(role) {
    return (
      {
        owner: "Owner",
        partner: "Partner",
        admin: "Partner",
        member: "Member",
        viewer: "Viewer",
      }[role] || role
    );
  }

  function clearIdleTimer() {
    if (state.idleTimer) {
      clearTimeout(state.idleTimer);
      state.idleTimer = null;
    }
  }

  function armIdleTimer() {
    clearIdleTimer();
    if (!state.token) return;
    state.idleTimer = setTimeout(() => {
      idleLogout();
    }, IDLE_MS);
  }

  function touchActivity() {
    if (!state.token) return;
    state.lastActivity = Date.now();
    armIdleTimer();
  }

  function idleLogout() {
    const wasIn = !!state.token;
    logout(true);
    if (wasIn) {
      const err = $("#login-error");
      if (err) {
        err.textContent =
          "Signed out after 10 minutes of no activity (keeps kids and shared PCs safer).";
        err.classList.add("show");
      }
    }
  }

  function wireIdleTimeout() {
    const events = [
      "mousemove",
      "mousedown",
      "keydown",
      "scroll",
      "touchstart",
      "click",
      "wheel",
    ];
    // Throttle resets so mousemove isn't expensive
    let scheduled = false;
    const onActivity = () => {
      if (scheduled) return;
      scheduled = true;
      requestAnimationFrame(() => {
        scheduled = false;
        touchActivity();
      });
    };
    events.forEach((ev) => {
      document.addEventListener(ev, onActivity, { passive: true, capture: true });
    });
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible" && state.token) {
        // If tab was hidden past idle window, sign out on return
        if (Date.now() - state.lastActivity >= IDLE_MS) {
          idleLogout();
        } else {
          armIdleTimer();
        }
      }
    });
  }

  function logout(callApi = true) {
    clearIdleTimer();
    if (callApi && state.token) {
      api("/api/logout", { method: "POST" }).catch(() => {});
    }
    state.token = "";
    state.user = null;
    localStorage.removeItem("budget_token");
    showPasswordGate(false);
    showApp(false);
  }

  async function afterAuth(data) {
    state.token = data.token || state.token;
    state.user = data;
    if (data.token) localStorage.setItem("budget_token", data.token);
    $("#user-badge").textContent = `${data.display_name || data.username} · ${roleLabel(data.role)}`;
    state.lastActivity = Date.now();
    armIdleTimer();
    if (data.must_change_password) {
      showApp(true);
      // Hide main shell content interaction via gate overlay
      const shell = $("#app-shell");
      if (shell) shell.classList.add("visible");
      $("#login-view").classList.add("hidden");
      showPasswordGate(true);
      return;
    }
    showPasswordGate(false);
    showApp(true);
    await refreshAll();
  }

  async function login(username, password) {
    const data = await api("/api/login", {
      method: "POST",
      json: { username, password },
    });
    await afterAuth(data);
  }

  async function submitPasswordChange(currentPassword, newPassword) {
    await api("/api/me/password", {
      method: "POST",
      json: {
        current_password: currentPassword,
        new_password: newPassword,
      },
    });
    if (state.user) state.user.must_change_password = false;
    showPasswordGate(false);
    showApp(true);
    await refreshAll();
  }

  function setView(name) {
    $$(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
    $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${name}`));
    if (name === "dashboard") refreshDashboard();
    if (name === "input") refreshInput();
    if (name === "goals") refreshGoals();
    if (name === "debts") refreshDebts();
    if (name === "invest") refreshInvestments();
    if (name === "settings") refreshSettings();
  }

  // ── Dashboard ───────────────────────────────────────────────

  async function refreshDashboard() {
    $("#month-label").textContent = monthName(state.year, state.month);
    const q = `year=${state.year}&month=${state.month}`;
    const [cal, metrics, upcoming, hh, snap] = await Promise.all([
      api(`/api/calendar?${q}`),
      api(`/api/metrics?${q}`),
      api("/api/upcoming"),
      api("/api/household"),
      api("/api/snapshot"),
    ]);
    setHouseholdNameDisplay(hh.name);
    const sub = $("#dash-sub");
    if (sub) {
      const who = (snap.members || []).map((m) => m.display_name).join(" · ");
      sub.textContent = who
        ? `Shared by ${who} · local only`
        : "Cash · plan · goals · debt · investments — all local";
    }
    renderSnapshot(snap);
    renderStats(metrics, cal);
    renderCalendar(cal);
    renderCharts(metrics);
    renderUpcoming(upcoming.items || []);
  }

  function setHouseholdNameDisplay(name) {
    const n = (name || "My Household").trim() || "My Household";
    const title = $("#household-title");
    const heading = $("#dash-heading");
    const input = $("#dash-name-input");
    if (title) title.textContent = n;
    if (heading) heading.textContent = n;
    if (input && input.hidden) input.value = n;
    const settingsName = $("#hh-name");
    if (settingsName && document.activeElement !== settingsName) {
      settingsName.value = n;
    }
  }

  function setDashNameEditing(on) {
    const heading = $("#dash-heading");
    const input = $("#dash-name-input");
    const edit = $("#dash-name-edit");
    const save = $("#dash-name-save");
    const cancel = $("#dash-name-cancel");
    if (!heading || !input) return;
    if (on) {
      input.value = heading.textContent.trim();
      heading.hidden = true;
      input.hidden = false;
      if (edit) edit.hidden = true;
      if (save) save.hidden = false;
      if (cancel) cancel.hidden = false;
      input.focus();
      input.select();
    } else {
      heading.hidden = false;
      input.hidden = true;
      if (edit) edit.hidden = false;
      if (save) save.hidden = true;
      if (cancel) cancel.hidden = true;
    }
  }

  async function saveDashHouseholdName() {
    const input = $("#dash-name-input");
    const msg = $("#dash-name-msg");
    const name = (input?.value || "").trim();
    if (!name) {
      if (msg) msg.textContent = "Enter a name.";
      return;
    }
    try {
      const hh = await api("/api/household", {
        method: "PATCH",
        json: { name },
      });
      setHouseholdNameDisplay(hh.name);
      setDashNameEditing(false);
      if (msg) msg.textContent = "Name saved.";
      setTimeout(() => {
        if (msg && msg.textContent === "Name saved.") msg.textContent = "";
      }, 2000);
    } catch (ex) {
      if (msg) msg.textContent = ex.message || "Could not save name.";
    }
  }

  function renderSnapshot(s) {
    const el = $("#snapshot-hero");
    if (!el) return;
    const nwCls = s.net_worth >= 0 ? "positive" : "negative";
    const members = (s.members || [])
      .map((m) => `<span>${escapeHtml(m.display_name)}</span>`)
      .join("");
    el.innerHTML = `
      <div class="snap-net">
        <div class="stat-label">Simple net worth ${helpBtn("Rough big picture: cash + investments minus debts. Not a bank balance by itself — goals saved are tracked separately.")}</div>
        <div class="stat-value ${nwCls}">${money(s.net_worth)}</div>
        <div class="stat-hint">Cash + investments − debts</div>
        <div class="snap-members">${members || "<span>Household</span>"}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Cash ${helpBtn("Latest bank balance you entered, or starting cash from Household settings if you have not logged a bank balance yet.")}</div>
        <div class="stat-value">${money(s.cash)}</div>
        <div class="stat-hint">Bank balance or starting cash</div>
      </div>
      <div class="stat">
        <div class="stat-label">Investments ${helpBtn("Sum of the simple investment buckets you added (401k, IRA, etc.). Update values when you check those accounts.")}</div>
        <div class="stat-value positive">${money(s.investments_total)}</div>
        <div class="stat-hint">${s.investment_count} account${s.investment_count === 1 ? "" : "s"} · +${money(s.monthly_invest_contrib)}/mo</div>
      </div>
      <div class="stat">
        <div class="stat-label">Debts ${helpBtn("Total balances from the Debt plan list. Paying these down improves net worth.")}</div>
        <div class="stat-value negative">${money(s.debts_total)}</div>
        <div class="stat-hint">${s.debt_count} listed</div>
      </div>
      <div class="stat">
        <div class="stat-label">Goals saved ${helpBtn("Money you marked as saved toward goals (vacation, house…). Tracked on the Goals page — not automatically pulled from the bank.")}</div>
        <div class="stat-value" style="color:var(--brand-light)">${money(s.goals_saved)}</div>
        <div class="stat-hint">of ${money(s.goals_target)} target · ${s.goal_count} goal${s.goal_count === 1 ? "" : "s"}</div>
      </div>`;
  }

  function renderStats(m, cal) {
    const endAct = cal.ending_balance_actual ?? cal.ending_balance;
    const endEst = cal.ending_balance_est ?? cal.ending_balance;
    const cards = [
      {
        label: "Starting balance",
        help: "Opening cash from Household settings. Bank balance entries on the calendar override from that day forward.",
        value: cal.starting_balance,
        hint: "Settings · before bank balance entries",
      },
      {
        label: "Income",
        help: "Paychecks and other income items dated this month.",
        value: m.month_income,
        cls: "positive",
        hint: "This month",
      },
      {
        label: "Month-end actual",
        help: "Green track: where cash ends the month using only confirmed money (pay + actuals).",
        value: endAct,
        cls: endAct >= 0 ? "positive" : "negative",
        hint: "Green track · confirmed only",
      },
      {
        label: "Month-end estimate",
        help: "Orange track: full plan including unpaid bills and estimates — the “will I make it?” number.",
        value: endEst,
        cls: endEst >= 0 ? "positive" : "negative",
        hint: "Orange track · full plan",
      },
    ];
    $("#stat-cards").innerHTML = cards
      .map(
        (c) => `
      <div class="stat">
        <div class="stat-label">${c.label} ${c.help ? helpBtn(c.help) : ""}</div>
        <div class="stat-value ${c.cls || ""}">${money(c.value)}</div>
        <div class="stat-hint">${c.hint || ""}</div>
      </div>`
      )
      .join("");
  }

  function fmtShort(n) {
    const v = Number(n) || 0;
    const abs = Math.abs(v);
    if (abs >= 1000) return (v < 0 ? "-" : "") + "$" + (abs / 1000).toFixed(abs >= 10000 ? 0 : 1) + "k";
    return money(v).replace(/\.00$/, "");
  }

  function renderCalendar(cal) {
    state.calendar = cal;
    const first = new Date(cal.year, cal.month - 1, 1);
    const startPad = first.getDay(); // 0 Sun
    const daysInMonth = cal.days.length;
    const today = new Date();
    const isThisMonth =
      today.getFullYear() === cal.year && today.getMonth() + 1 === cal.month;

    let html = `
      <div class="cal-weekdays">
        <div>Sun</div><div>Mon</div><div>Tue</div><div>Wed</div>
        <div>Thu</div><div>Fri</div><div>Sat</div>
      </div>
      <div class="cal-grid">`;

    for (let i = 0; i < startPad; i++) {
      html += `<div class="cal-cell outside"></div>`;
    }

    for (const day of cal.days) {
      const d = new Date(day.date + "T12:00:00");
      const dayNum = d.getDate();
      const isToday = isThisMonth && today.getDate() === dayNum;
      const selected = state.selectedDate === day.date ? "selected" : "";
      const act = day.running_balance_actual ?? day.running_balance;
      const est = day.running_balance_est ?? day.running_balance;
      const actCls = act < 0 ? "neg" : "";
      const estCls = est < 0 ? "neg" : "";
      const pills = (day.items || [])
        .slice(0, 3)
        .map((it) => {
          if (it.item_type === "balance") {
            return `<div class="pill pill-balance" title="Bank balance ${money(it.amount)}">= ${Math.round(it.amount)} bal</div>`;
          }
          const sign = it.is_income ? "+" : "−";
          return `<div class="pill pill-${it.item_type}" title="${escapeHtml(it.name)} ${money(it.amount)}">${sign}${Math.round(it.amount)} ${escapeHtml(it.name)}</div>`;
        })
        .join("");
      const more =
        day.items.length > 3
          ? `<div class="pill" style="opacity:0.65">+${day.items.length - 3} more · click</div>`
          : "";
      const anchor = day.balance_anchored
        ? `<span class="cal-anchor-dot" title="Bank balance set this day"></span>`
        : "";

      html += `
        <div class="cal-cell ${isToday ? "today" : ""} ${selected}" data-date="${day.date}" role="button" tabindex="0" aria-label="Open ${day.date}">
          <div class="cal-daynum">${dayNum}</div>
          <div class="cal-pills">${pills}${more}</div>
          <div class="cal-balance-row">
            <span class="cal-bal-act ${actCls}">${anchor}act ${fmtShort(act)}</span>
            <span class="cal-bal-est ${estCls}">est ${fmtShort(est)}</span>
          </div>
        </div>`;
    }

    const totalCells = startPad + daysInMonth;
    const trail = (7 - (totalCells % 7)) % 7;
    for (let i = 0; i < trail; i++) {
      html += `<div class="cal-cell outside"></div>`;
    }
    html += `</div>`;
    $("#calendar").innerHTML = html;

    $$(".cal-cell[data-date]").forEach((cell) => {
      const open = () => openDayExpand(cell.dataset.date);
      cell.addEventListener("click", open);
      cell.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          open();
        }
      });
    });

    if (state.selectedDate) {
      openDayExpand(state.selectedDate, false);
    } else {
      closeDayExpand();
    }
  }

  function openDayExpand(dateStr, toggle = true) {
    if (!state.calendar) return;
    if (toggle && state.selectedDate === dateStr) {
      closeDayExpand();
      return;
    }
    state.selectedDate = dateStr;
    $$(".cal-cell[data-date]").forEach((c) => {
      c.classList.toggle("selected", c.dataset.date === dateStr);
    });

    const day = state.calendar.days.find((d) => d.date === dateStr);
    const panel = $("#day-expand");
    if (!day || !panel) return;

    const label = new Date(dateStr + "T12:00:00").toLocaleDateString(undefined, {
      weekday: "long",
      month: "long",
      day: "numeric",
      year: "numeric",
    });
    $("#day-expand-title").textContent = label;
    const act = day.running_balance_actual ?? day.running_balance;
    const est = day.running_balance_est ?? day.running_balance;
    $("#day-expand-balances").innerHTML = `
      <span class="act">act ${money(act)}</span>
      <span class="est">est ${money(est)}</span>
    `;
    $("#day-expand-sub").textContent = day.balance_anchored
      ? "Bank balance was set this day — running totals restart from that amount."
      : `${day.items.length} item${day.items.length === 1 ? "" : "s"} · click the day again to close`;

    const tbody = $("#day-expand-table tbody");
    if (!day.items.length) {
      tbody.innerHTML = "";
      // show empty row via message in table
      tbody.innerHTML = `<tr><td colspan="4" class="day-expand-empty">Nothing scheduled — add bills, estimates, pay, or a bank balance on Input.</td></tr>`;
    } else {
      tbody.innerHTML = day.items
        .map((it) => {
          let amountCell;
          if (it.item_type === "balance") {
            amountCell = `<td class="num text-primary">= ${money(it.amount)}</td>`;
          } else {
            const cls = it.is_income ? "positive" : "negative";
            const sign = it.is_income ? "+" : "−";
            amountCell = `<td class="num ${cls}">${sign}${money(it.amount)}</td>`;
          }
          return `<tr>
            <td>${escapeHtml(it.name)}</td>
            <td><span class="chip chip-${typeChip(it.item_type)}">${it.item_type}</span></td>
            ${amountCell}
            <td class="text-muted">${escapeHtml(it.notes || "")}</td>
          </tr>`;
        })
        .join("");
    }
    panel.classList.add("open");
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function closeDayExpand() {
    state.selectedDate = null;
    const panel = $("#day-expand");
    if (panel) panel.classList.remove("open");
    $$(".cal-cell[data-date]").forEach((c) => c.classList.remove("selected"));
  }

  function renderCharts(m) {
    const catLabels = Object.keys(m.by_category || {});
    const catValues = Object.values(m.by_category || {});
    const brandColors = [
      "#C8102E",
      "#f08080",
      "#58a6ff",
      "#3fb950",
      "#d29922",
      "#a371f7",
      "#79c0ff",
      "#ffa657",
    ];

    destroyChart("category");
    destroyChart("income");

    const catCtx = $("#chart-category");
    if (catCtx && window.Chart) {
      state.charts.category = new Chart(catCtx, {
        type: "doughnut",
        data: {
          labels: catLabels.length ? catLabels : ["No expenses"],
          datasets: [
            {
              data: catValues.length ? catValues : [1],
              backgroundColor: catLabels.length
                ? catLabels.map((_, i) => brandColors[i % brandColors.length])
                : ["#21262d"],
              borderWidth: 0,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          layout: { padding: 4 },
          plugins: {
            legend: {
              position: "bottom",
              labels: {
                color: "#8b949e",
                boxWidth: 10,
                font: { size: 10 },
                padding: 8,
              },
            },
          },
        },
      });
    }

    const incCtx = $("#chart-income");
    if (incCtx && window.Chart) {
      state.charts.income = new Chart(incCtx, {
        type: "bar",
        data: {
          labels: ["Income", "Bills", "Estimates", "Actuals"],
          datasets: [
            {
              data: [m.month_income, m.month_bills, m.month_estimates, m.month_actuals],
              backgroundColor: ["#3fb950", "#58a6ff", "#d29922", "#a371f7"],
              borderRadius: 6,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          layout: { padding: 4 },
          plugins: { legend: { display: false } },
          scales: {
            x: {
              ticks: { color: "#8b949e" },
              grid: { color: "#21262d" },
            },
            y: {
              ticks: { color: "#8b949e" },
              grid: { color: "#21262d" },
            },
          },
        },
      });
    }
  }

  function destroyChart(key) {
    if (state.charts[key]) {
      state.charts[key].destroy();
      state.charts[key] = null;
    }
  }

  function renderUpcoming(items) {
    const tbody = $("#upcoming-table tbody");
    if (!items.length) {
      tbody.innerHTML = `<tr><td colspan="4" class="text-muted">Nothing upcoming — add bills or pay on Input.</td></tr>`;
      return;
    }
    tbody.innerHTML = items
      .map((it) => {
        const cls = it.is_income ? "positive" : "negative";
        const sign = it.is_income ? "+" : "−";
        return `<tr>
          <td>${it.due_date}</td>
          <td>${escapeHtml(it.name)}</td>
          <td><span class="chip chip-${typeChip(it.item_type)}">${it.item_type}</span></td>
          <td class="num ${cls}">${sign}${money(it.amount)}</td>
        </tr>`;
      })
      .join("");
  }

  function typeChip(t) {
    if (t === "paycheck" || t === "actual") return "success";
    if (t === "estimate") return "warning";
    if (t === "balance") return "brand";
    if (t === "bill") return "info";
    return "brand";
  }

  // ── Input ───────────────────────────────────────────────────

  async function refreshInput() {
    await loadNames();
    const q = `year=${state.year}&month=${state.month}`;
    const items = await api(`/api/items?${q}`);
    const tbody = $("#items-table tbody");
    if (!items.length) {
      tbody.innerHTML = `<tr><td colspan="5" class="text-muted">No items this month yet.</td></tr>`;
      return;
    }
    tbody.innerHTML = items
      .map((it) => {
        const cls = it.is_income ? "positive" : "negative";
        const sign = it.is_income ? "+" : "−";
        return `<tr>
          <td>${it.due_date}</td>
          <td>${escapeHtml(it.name)}</td>
          <td><span class="chip chip-${typeChip(it.item_type)}">${it.item_type}</span></td>
          <td class="num ${cls}">${sign}${money(it.amount)}</td>
          <td><button class="btn btn-ghost btn-sm" data-del="${it.id}" type="button">Delete</button></td>
        </tr>`;
      })
      .join("");

    tbody.querySelectorAll("[data-del]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!confirm("Delete this item?")) return;
        await api(`/api/items/${btn.dataset.del}`, { method: "DELETE" });
        await refreshInput();
        await refreshDashboard();
      });
    });
  }

  async function loadNames() {
    state.names = await api("/api/names");
    const sel = $("#item-name");
    const current = sel.value;
    const groups = {
      bill: "Bills",
      estimate: "Estimates / general",
      income: "Income",
      general: "General",
    };
    const byKind = {};
    state.names.forEach((n) => {
      const k = n.kind || "general";
      (byKind[k] ||= []).push(n);
    });
    let html = "";
    for (const [kind, label] of Object.entries(groups)) {
      const list = byKind[kind] || [];
      if (!list.length) continue;
      html += `<optgroup label="${label}">`;
      list.forEach((n) => {
        html += `<option value="${escapeAttr(n.name)}">${escapeHtml(n.name)}</option>`;
      });
      html += `</optgroup>`;
    }
    html += `<option value="__custom__">＋ Custom name…</option>`;
    sel.innerHTML = html;
    if (current && [...sel.options].some((o) => o.value === current)) {
      sel.value = current;
    }
    toggleCustomName();
  }

  function toggleCustomName() {
    const custom = $("#item-name").value === "__custom__";
    $("#custom-name-row").classList.toggle("show", custom);
    $("#item-name-custom").required = custom;
  }

  // ── Goals ───────────────────────────────────────────────────

  async function refreshGoals() {
    const goals = await api("/api/goals");
    const box = $("#goals-list");
    if (!goals.length) {
      box.innerHTML = `<div class="empty"><h3>No goals yet</h3><p>Add something she’s working toward — vacation, house fund, car, emergency savings.</p></div>`;
      return;
    }
    box.innerHTML = goals
      .map((g) => {
        const barCls = g.percent >= 100 ? "ok" : g.percent >= 60 ? "ok" : g.on_track === false ? "warn" : "";
        const badge =
          g.on_track === true
            ? `<span class="goal-badge on">On track</span>`
            : g.on_track === false
              ? `<span class="goal-badge off">Behind target date</span>`
              : "";
        const suggest = g.suggested_monthly
          ? `<div>To hit date: save about <strong>${money(g.suggested_monthly)}</strong>/mo</div>`
          : "";
        const eta = g.eta_date
          ? `<div>At current savings: <strong>${g.eta_date}</strong></div>`
          : g.monthly_contribution > 0
            ? ""
            : `<div class="text-muted">Set a monthly amount to see an arrival date</div>`;
        return `
        <div class="goal-card">
          ${badge}
          <h3>${escapeHtml(g.name)}</h3>
          <div class="progress"><div class="progress-bar ${barCls}" style="width:${Math.min(g.percent, 100)}%"></div></div>
          <div class="goal-meta">
            <div><strong>${money(g.current_amount)}</strong> of ${money(g.target_amount)} · ${g.percent}%</div>
            <div>Still need <strong>${money(g.remaining)}</strong></div>
            ${g.target_date ? `<div>Target date: <strong>${g.target_date}</strong></div>` : ""}
            ${g.monthly_contribution ? `<div>Saving <strong>${money(g.monthly_contribution)}</strong>/mo</div>` : ""}
            ${suggest}
            ${eta}
            ${g.notes ? `<div class="text-muted">${escapeHtml(g.notes)}</div>` : ""}
          </div>
          <div class="goal-actions">
            <button class="btn btn-outline btn-sm" type="button" data-goal-add="${g.id}" data-amt="${g.monthly_contribution || 50}">+ Add monthly</button>
            <button class="btn btn-ghost btn-sm" type="button" data-goal-del="${g.id}">Delete</button>
          </div>
        </div>`;
      })
      .join("");

    box.querySelectorAll("[data-goal-del]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!confirm("Delete this goal?")) return;
        await api(`/api/goals/${btn.dataset.goalDel}`, { method: "DELETE" });
        await refreshGoals();
      });
    });
    box.querySelectorAll("[data-goal-add]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = btn.dataset.goalAdd;
        const add = parseFloat(prompt("How much to add to savings?", btn.dataset.amt || "50"));
        if (!add || add <= 0) return;
        const g = goals.find((x) => String(x.id) === String(id));
        if (!g) return;
        await api(`/api/goals/${id}`, {
          method: "PATCH",
          json: { current_amount: round2(g.current_amount + add) },
        });
        await refreshGoals();
      });
    });
  }

  function round2(n) {
    return Math.round(Number(n) * 100) / 100;
  }

  // ── Debts ───────────────────────────────────────────────────

  async function refreshDebts() {
    const debts = await api("/api/debts");
    const tbody = $("#debts-table tbody");
    if (!debts.length) {
      tbody.innerHTML = `<tr><td colspan="5" class="text-muted">No debts listed — add cards or loans above to build a plan.</td></tr>`;
    } else {
      tbody.innerHTML = debts
        .map(
          (d) => `<tr>
          <td>${escapeHtml(d.name)}</td>
          <td class="num">${money(d.balance)}</td>
          <td class="num">${Number(d.apr).toFixed(2)}%</td>
          <td class="num">${money(d.min_payment)}</td>
          <td><button class="btn btn-ghost btn-sm" type="button" data-debt-del="${d.id}">Delete</button></td>
        </tr>`
        )
        .join("");
      tbody.querySelectorAll("[data-debt-del]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          if (!confirm("Remove this debt?")) return;
          await api(`/api/debts/${btn.dataset.debtDel}`, { method: "DELETE" });
          await refreshDebts();
        });
      });
    }
  }

  async function runDebtPlan() {
    const msg = $("#plan-msg");
    const box = $("#plan-results");
    msg.textContent = "Calculating…";
    try {
      const plan = await api("/api/debts/plan", {
        method: "POST",
        json: {
          strategy: $("#plan-strategy").value,
          extra_monthly: parseFloat($("#plan-extra").value) || 0,
        },
      });
      msg.textContent = "";
      if (!plan.months && !(plan.payoff_order || []).length) {
        box.innerHTML = `<div class="empty"><h3>Nothing to plan</h3><p>Add at least one debt with a balance.</p></div>`;
        return;
      }
      const cmp = plan.compare || {};
      const av = cmp.avalanche || {};
      const sn = cmp.snowball || {};
      box.innerHTML = `
        <div class="alert alert-brand" style="margin-bottom:1rem">${escapeHtml(plan.strategy_blurb)}</div>
        <div class="plan-summary">
          <div class="stat"><div class="stat-label">Debt free</div><div class="stat-value" style="font-size:1.25rem;color:var(--brand-light)">${escapeHtml(plan.debt_free_label)}</div><div class="stat-hint">${plan.months} months</div></div>
          <div class="stat"><div class="stat-label">Total interest</div><div class="stat-value negative" style="font-size:1.25rem">${money(plan.total_interest)}</div></div>
          <div class="stat"><div class="stat-label">Monthly budget</div><div class="stat-value" style="font-size:1.25rem">${money(plan.monthly_budget)}</div><div class="stat-hint">Mins ${money(plan.total_min_payments)} + extra ${money(plan.extra_monthly)}</div></div>
          <div class="stat"><div class="stat-label">Total paid</div><div class="stat-value" style="font-size:1.25rem">${money(plan.total_paid)}</div></div>
        </div>
        <h3 style="margin-bottom:0.5rem">Payoff order</h3>
        <div class="plan-order">${(plan.payoff_order || []).map((n, i) => `<span>${i + 1}. ${escapeHtml(n)}</span>`).join("") || "—"}</div>
        <h3 style="margin:1rem 0 0.5rem">Compare strategies (same extra payment)</h3>
        <div class="plan-compare">
          <div class="card ${plan.strategy === "avalanche" ? "card-featured" : ""}">
            <div class="section-label">Avalanche</div>
            <div class="text-primary" style="font-weight:700">${escapeHtml(av.debt_free_label || "—")}</div>
            <div class="text-secondary" style="font-size:0.85rem;margin-top:0.35rem">${av.months || 0} mo · interest ${money(av.total_interest || 0)}</div>
          </div>
          <div class="card ${plan.strategy === "snowball" ? "card-featured" : ""}">
            <div class="section-label">Snowball</div>
            <div class="text-primary" style="font-weight:700">${escapeHtml(sn.debt_free_label || "—")}</div>
            <div class="text-secondary" style="font-size:0.85rem;margin-top:0.35rem">${sn.months || 0} mo · interest ${money(sn.total_interest || 0)}</div>
          </div>
        </div>
        <p class="text-secondary" style="font-size:0.875rem;margin-bottom:0.75rem">${escapeHtml(cmp.recommendation || "")}
          ${cmp.interest_saved_with_avalanche > 0 ? ` Avalanche saves about <strong class="text-primary">${money(cmp.interest_saved_with_avalanche)}</strong> in interest.` : ""}
        </p>
        <h3 style="margin-bottom:0.5rem">Month-by-month (first ${Math.min((plan.steps || []).length, 120)})</h3>
        <div class="plan-steps-wrap">
          <table class="data">
            <thead><tr><th>Month</th><th>Payments</th><th>Paid off</th><th class="num">Interest so far</th></tr></thead>
            <tbody>
              ${(plan.steps || [])
                .map((s) => {
                  const pays = Object.entries(s.payments || {})
                    .map(([k, v]) => `${escapeHtml(k)} ${money(v)}`)
                    .join(" · ");
                  const done = (s.paid_off || []).map(escapeHtml).join(", ") || "—";
                  return `<tr>
                    <td>${escapeHtml(s.date_label)}</td>
                    <td style="font-size:0.8rem">${pays || "—"}</td>
                    <td>${done}</td>
                    <td class="num">${money(s.total_interest)}</td>
                  </tr>`;
                })
                .join("")}
            </tbody>
          </table>
        </div>`;
    } catch (ex) {
      msg.textContent = ex.message;
      box.innerHTML = "";
    }
  }

  // ── Investments ─────────────────────────────────────────────

  async function refreshInvestments() {
    const rows = await api("/api/investments");
    const total = rows.reduce((s, r) => s + (r.current_value || 0), 0);
    const monthly = rows.reduce((s, r) => s + (r.monthly_contribution || 0), 0);
    const basis = rows.reduce((s, r) => s + (r.cost_basis || 0), 0);
    const gain = basis > 0 ? total - basis : 0;
    const sum = $("#invest-summary");
    if (sum) {
      sum.innerHTML = `
        <div class="stat"><div class="stat-label">Total value</div><div class="stat-value positive">${money(total)}</div></div>
        <div class="stat"><div class="stat-label">Monthly contributions</div><div class="stat-value">${money(monthly)}</div></div>
        <div class="stat"><div class="stat-label">Gain / loss</div><div class="stat-value ${gain >= 0 ? "positive" : "negative"}">${basis > 0 ? money(gain) : "—"}</div><div class="stat-hint">${basis > 0 ? "vs what you put in" : "Add cost basis to track"}</div></div>
        <div class="stat"><div class="stat-label">Accounts</div><div class="stat-value">${rows.length}</div></div>`;
    }
    const tbody = $("#invest-table tbody");
    if (!rows.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="text-muted">No investments yet — add a 401k, IRA, or simple savings bucket above.</td></tr>`;
      return;
    }
    tbody.innerHTML = rows
      .map((r) => {
        const gl =
          r.cost_basis > 0
            ? `<span class="${r.gain_loss >= 0 ? "positive" : "negative"}">${money(r.gain_loss)}${r.gain_loss_pct != null ? ` (${r.gain_loss_pct}%)` : ""}</span>`
            : `<span class="text-muted">—</span>`;
        return `<tr>
          <td>${escapeHtml(r.name)}</td>
          <td><span class="chip chip-info">${escapeHtml(r.account_type)}</span></td>
          <td class="num">${money(r.current_value)}</td>
          <td class="num">${gl}</td>
          <td class="num">${money(r.monthly_contribution)}</td>
          <td class="text-muted">${r.last_updated || "—"}</td>
          <td style="white-space:nowrap">
            <button class="btn btn-outline btn-sm" type="button" data-inv-upd="${r.id}" data-val="${r.current_value}">Update $</button>
            <button class="btn btn-ghost btn-sm" type="button" data-inv-del="${r.id}">Delete</button>
          </td>
        </tr>`;
      })
      .join("");

    tbody.querySelectorAll("[data-inv-del]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!confirm("Remove this investment?")) return;
        await api(`/api/investments/${btn.dataset.invDel}`, { method: "DELETE" });
        await refreshInvestments();
      });
    });
    tbody.querySelectorAll("[data-inv-upd]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const v = parseFloat(prompt("New current value?", btn.dataset.val));
        if (Number.isNaN(v) || v < 0) return;
        await api(`/api/investments/${btn.dataset.invUpd}`, {
          method: "PATCH",
          json: { current_value: v },
        });
        await refreshInvestments();
      });
    });
  }

  // ── Settings ────────────────────────────────────────────────

  async function refreshSettings() {
    const [hh, members] = await Promise.all([
      api("/api/household"),
      api("/api/members"),
    ]);
    $("#hh-name").value = hh.name;
    $("#hh-balance").value = hh.starting_balance;
    const list = $("#members-list");
    const meName = (state.user && (state.user.username || "")).toLowerCase();
    if (list) {
      list.innerHTML = members
        .map((m) => {
          const isMe = (m.username || "").toLowerCase() === meName;
          const delBtn = isMe
            ? `<span class="text-muted" style="font-size:0.75rem">you</span>`
            : `<button class="btn btn-danger btn-sm" type="button" data-member-del="${m.id}" data-member-name="${escapeAttr(m.display_name || m.username)}">Delete</button>`;
          return `<div style="display:flex;justify-content:space-between;align-items:center;gap:0.75rem;padding:0.55rem 0;border-bottom:1px solid var(--border)">
          <div>
            <strong class="text-primary">${escapeHtml(m.display_name)}</strong>
            <span class="text-muted" style="font-size:0.8rem"> · @${escapeHtml(m.username)}</span>
            <div style="margin-top:0.25rem">
              <span class="chip chip-info">${escapeHtml(roleLabel(m.role))}</span>
              ${m.must_change_password ? `<span class="chip chip-warning">must change password</span>` : ""}
              ${isMe ? `<span class="chip chip-brand">signed in</span>` : ""}
            </div>
          </div>
          <div>${delBtn}</div>
        </div>`;
        })
        .join("") || `<p class="text-muted">No members</p>`;

      list.querySelectorAll("[data-member-del]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const name = btn.dataset.memberName || "this user";
          if (!confirm(`Delete login “${name}”? They will no longer be able to sign in on this computer.`)) {
            return;
          }
          try {
            await api(`/api/members/${btn.dataset.memberDel}`, { method: "DELETE" });
            await refreshSettings();
          } catch (ex) {
            alert(ex.message || "Could not delete user");
          }
        });
      });
    }
  }

  // ── Import ──────────────────────────────────────────────────

  async function runImport(commit) {
    const file = $("#statement-file").files[0];
    if (!file) {
      $("#import-msg").textContent = "Choose a CSV file first.";
      return;
    }
    const bank = $("#import-bank")?.value || "auto";
    const fd = new FormData();
    fd.append("file", file);
    const qs = `commit=${commit ? "true" : "false"}&bank=${encodeURIComponent(bank)}`;
    const res = await fetch(`/api/import/statement?${qs}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${state.token}` },
      body: fd,
    });
    if (!res.ok) {
      const j = await res.json().catch(() => ({}));
      throw new Error(j.detail || "Import failed");
    }
    const data = await res.json();
    $("#import-msg").textContent = data.message || "";
    const badge = $("#import-bank-badge");
    if (badge) {
      badge.innerHTML = data.bank_label
        ? `Detected / used: <strong class="text-primary">${escapeHtml(data.bank_label)}</strong>`
        : "";
    }
    // If auto-detected, sync dropdown so user sees what matched
    if (bank === "auto" && data.bank && $("#import-bank")) {
      const opt = [...$("#import-bank").options].find((o) => o.value === data.bank);
      if (opt) {
        /* leave on auto so next file can re-detect; only show badge */
      }
    }
    const tbody = $("#import-table tbody");
    tbody.innerHTML = (data.rows || [])
      .map((r) => {
        const cls = r.is_income ? "positive" : "negative";
        const warn = !r.date ? ' style="opacity:0.6"' : "";
        return `<tr${warn}>
          <td>${r.date || "— missing date"}</td>
          <td>${escapeHtml(r.description)}</td>
          <td class="num ${cls}">${money(r.amount)}</td>
          <td>${r.is_income ? "In" : "Out"}</td>
        </tr>`;
      })
      .join("") || `<tr><td colspan="4" class="text-muted">No rows parsed — try picking your bank above, or confirm the file is CSV not PDF.</td></tr>`;
    if (commit) await refreshDashboard();
  }

  function escapeHtml(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function escapeAttr(s) {
    return escapeHtml(s).replace(/'/g, "&#39;");
  }

  async function refreshAll() {
    await refreshDashboard();
  }

  // ── Wire events ─────────────────────────────────────────────

  function wire() {
    $("#login-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const err = $("#login-error");
      err.classList.remove("show");
      try {
        await login($("#username").value.trim(), $("#password").value);
      } catch (ex) {
        err.textContent = ex.message || "Login failed";
        err.classList.add("show");
      }
    });

    $("#btn-logout").addEventListener("click", () => logout(true));
    $("#logo-home").addEventListener("click", (e) => {
      e.preventDefault();
      setView("dashboard");
    });

    const dashEdit = $("#dash-name-edit");
    const dashSave = $("#dash-name-save");
    const dashCancel = $("#dash-name-cancel");
    const dashInput = $("#dash-name-input");
    if (dashEdit) {
      dashEdit.addEventListener("click", () => {
        const msg = $("#dash-name-msg");
        if (msg) msg.textContent = "";
        setDashNameEditing(true);
      });
    }
    if (dashSave) dashSave.addEventListener("click", () => saveDashHouseholdName());
    if (dashCancel) {
      dashCancel.addEventListener("click", () => {
        setDashNameEditing(false);
        const msg = $("#dash-name-msg");
        if (msg) msg.textContent = "";
      });
    }
    if (dashInput) {
      dashInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          saveDashHouseholdName();
        }
        if (e.key === "Escape") {
          e.preventDefault();
          setDashNameEditing(false);
        }
      });
    }

    $$(".nav-btn").forEach((btn) => {
      btn.addEventListener("click", () => setView(btn.dataset.view));
    });

    $("#prev-month").addEventListener("click", async () => {
      state.month -= 1;
      if (state.month < 1) {
        state.month = 12;
        state.year -= 1;
      }
      await refreshDashboard();
    });
    $("#next-month").addEventListener("click", async () => {
      state.month += 1;
      if (state.month > 12) {
        state.month = 1;
        state.year += 1;
      }
      await refreshDashboard();
    });
    $("#today-month").addEventListener("click", async () => {
      const n = new Date();
      state.year = n.getFullYear();
      state.month = n.getMonth() + 1;
      await refreshDashboard();
    });

    $("#item-name").addEventListener("change", toggleCustomName);

    $("#item-type").addEventListener("change", () => {
      // soft default: paycheck => income naming hint via type only
    });

    $("#item-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const msg = $("#item-form-msg");
      msg.textContent = "";
      try {
        let name = $("#item-name").value;
        if (name === "__custom__") {
          name = $("#item-name-custom").value.trim();
          if (!name) throw new Error("Enter a custom name");
        }
        const itemType = $("#item-type").value;
        if (itemType === "balance" && !name) name = "Bank balance";
        if (itemType === "balance" && name === "__custom__") {
          name = $("#item-name-custom").value.trim() || "Bank balance";
        }
        await api("/api/items", {
          method: "POST",
          json: {
            name: itemType === "balance" ? name || "Bank balance" : name,
            item_type: itemType,
            amount: parseFloat($("#item-amount").value),
            is_income: itemType === "paycheck",
            due_date: $("#item-date").value,
            frequency: itemType === "balance" ? "once" : $("#item-freq").value,
            notes: $("#item-notes").value,
            category: itemType === "balance" ? "Balance" : $("#item-category").value,
            retain_name: $("#item-retain").checked,
          },
        });
        msg.textContent =
          itemType === "balance"
            ? "Bank balance saved — calendar act/est restart from that date."
            : "Saved.";
        $("#item-amount").value = "";
        $("#item-notes").value = "";
        await refreshInput();
        await refreshDashboard();
      } catch (ex) {
        msg.textContent = ex.message;
      }
    });

    $("#settings-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const msg = $("#settings-msg");
      try {
        await api("/api/household", {
          method: "PATCH",
          json: {
            name: $("#hh-name").value.trim(),
            starting_balance: parseFloat($("#hh-balance").value),
          },
        });
        msg.textContent = "Saved.";
        await refreshDashboard();
      } catch (ex) {
        msg.textContent = ex.message;
      }
    });

    $("#btn-preview-import").addEventListener("click", async () => {
      try {
        await runImport(false);
      } catch (ex) {
        $("#import-msg").textContent = ex.message;
      }
    });
    $("#btn-commit-import").addEventListener("click", async () => {
      try {
        await runImport(true);
      } catch (ex) {
        $("#import-msg").textContent = ex.message;
      }
    });

    const closeBtn = $("#day-expand-close");
    if (closeBtn) closeBtn.addEventListener("click", () => closeDayExpand());

    $("#goal-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const msg = $("#goal-form-msg");
      try {
        await api("/api/goals", {
          method: "POST",
          json: {
            name: $("#goal-name").value.trim(),
            target_amount: parseFloat($("#goal-target").value),
            current_amount: parseFloat($("#goal-current").value) || 0,
            target_date: $("#goal-date").value || null,
            monthly_contribution: parseFloat($("#goal-monthly").value) || 0,
            notes: $("#goal-notes").value,
          },
        });
        msg.textContent = "Goal saved.";
        $("#goal-name").value = "";
        $("#goal-target").value = "";
        $("#goal-notes").value = "";
        await refreshGoals();
      } catch (ex) {
        msg.textContent = ex.message;
      }
    });

    $("#debt-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const msg = $("#debt-form-msg");
      try {
        await api("/api/debts", {
          method: "POST",
          json: {
            name: $("#debt-name").value.trim(),
            balance: parseFloat($("#debt-balance").value),
            apr: parseFloat($("#debt-apr").value) || 0,
            min_payment: parseFloat($("#debt-min").value) || 0,
          },
        });
        msg.textContent = "Debt saved.";
        $("#debt-name").value = "";
        $("#debt-balance").value = "";
        await refreshDebts();
      } catch (ex) {
        msg.textContent = ex.message;
      }
    });

    $("#btn-run-plan").addEventListener("click", () => runDebtPlan());

    const invForm = $("#invest-form");
    if (invForm) {
      invForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const msg = $("#invest-form-msg");
        try {
          await api("/api/investments", {
            method: "POST",
            json: {
              name: $("#inv-name").value.trim(),
              account_type: $("#inv-type").value,
              current_value: parseFloat($("#inv-value").value) || 0,
              cost_basis: parseFloat($("#inv-basis").value) || 0,
              monthly_contribution: parseFloat($("#inv-monthly").value) || 0,
              notes: $("#inv-notes").value,
            },
          });
          msg.textContent = "Saved.";
          $("#inv-name").value = "";
          await refreshInvestments();
        } catch (ex) {
          msg.textContent = ex.message;
        }
      });
    }

    const memForm = $("#member-form");
    if (memForm) {
      memForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const msg = $("#member-msg");
        try {
          await api("/api/members", {
            method: "POST",
            json: {
              username: $("#mem-user").value.trim(),
              password: $("#mem-pass").value,
              display_name: $("#mem-name").value.trim(),
              role: $("#mem-role")?.value || "partner",
              require_password_change: !!$("#mem-force-pw")?.checked,
            },
          });
          msg.textContent = "Login added — they can sign in on this computer.";
          $("#mem-user").value = "";
          $("#mem-pass").value = "";
          $("#mem-name").value = "";
          if ($("#mem-role")) $("#mem-role").value = "partner";
          if ($("#mem-force-pw")) $("#mem-force-pw").checked = false;
          await refreshSettings();
        } catch (ex) {
          msg.textContent = ex.message;
        }
      });
    }

    const pwGateForm = $("#pw-gate-form");
    if (pwGateForm) {
      pwGateForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const err = $("#pw-gate-error");
        err?.classList.remove("show");
        const cur = $("#pw-current").value;
        const n1 = $("#pw-new").value;
        const n2 = $("#pw-new2").value;
        if (n1 !== n2) {
          if (err) {
            err.textContent = "New passwords do not match.";
            err.classList.add("show");
          }
          return;
        }
        try {
          await submitPasswordChange(cur, n1);
        } catch (ex) {
          if (err) {
            err.textContent = ex.message || "Could not change password";
            err.classList.add("show");
          }
        }
      });
    }

    const passwordForm = $("#password-form");
    if (passwordForm) {
      passwordForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const msg = $("#password-msg");
        const n1 = $("#set-pw-new").value;
        const n2 = $("#set-pw-new2").value;
        if (n1 !== n2) {
          if (msg) msg.textContent = "New passwords do not match.";
          return;
        }
        try {
          await api("/api/me/password", {
            method: "POST",
            json: {
              current_password: $("#set-pw-current").value,
              new_password: n1,
            },
          });
          if (msg) msg.textContent = "Password updated.";
          $("#set-pw-current").value = "";
          $("#set-pw-new").value = "";
          $("#set-pw-new2").value = "";
        } catch (ex) {
          if (msg) msg.textContent = ex.message;
        }
      });
    }

    // default date = today
    const t = new Date();
    const iso = t.toISOString().slice(0, 10);
    $("#item-date").value = iso;
  }

  async function boot() {
    wireHelp();
    wireIdleTimeout();
    wire();
    if (!state.token) {
      showApp(false);
      return;
    }
    try {
      const me = await api("/api/me");
      await afterAuth({ ...me, token: state.token });
    } catch (_) {
      logout(false);
    }
  }

  boot();
})();
