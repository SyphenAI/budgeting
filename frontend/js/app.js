/* Household Money — frontend */
(() => {
  const DEFAULT_IDLE_MIN = 30;

  const state = {
    token: localStorage.getItem("budget_token") || "",
    user: null,
    year: new Date().getFullYear(),
    month: new Date().getMonth() + 1,
    names: [],
    charts: { category: null, income: null },
    calendar: null,
    metrics: null,
    household: null,
    snapshot: null,
    selectedDate: null,
    idleTimer: null,
    idleMinutes: DEFAULT_IDLE_MIN,
    lastActivity: Date.now(),
    importRows: [],
    importCategories: [],
    importBankLabel: "Import",
    importDebts: [], // { key, name, apr, balance, min_payment }
    subs: null,
    cardPreview: null,
    cardRecurring: [],
    cardRecurringQ: "",
    cardRecurringKind: "active",
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

  function isoDate(d = new Date()) {
    const dt = d instanceof Date ? d : new Date(d);
    const y = dt.getFullYear();
    const m = String(dt.getMonth() + 1).padStart(2, "0");
    const day = String(dt.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  }

  function daysBetween(fromIso, toIso) {
    const a = new Date(`${fromIso}T12:00:00`);
    const b = new Date(`${toIso}T12:00:00`);
    return Math.round((b - a) / 86400000);
  }

  function isRecurringItem(it) {
    return !!(it && it.frequency && it.frequency !== "once" && it.item_type !== "balance");
  }

  function editScopeValue() {
    const picked = document.querySelector('input[name="edit-item-scope"]:checked');
    return (picked && picked.value) || "this";
  }

  async function confirmDeleteItem(item) {
    if (!isRecurringItem(item)) {
      return confirm("Delete this item?") ? "this" : null;
    }
    if (confirm("Delete ONLY this date?\nLater months stay on the calendar.")) return "this";
    if (confirm("Delete this date AND later months?\nThat stops the repeat.")) return "future";
    return null;
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

  function isViewer() {
    return ((state.user && state.user.role) || "").toLowerCase() === "viewer";
  }

  const VIEWER_WRITE_VIEWS = new Set(["input", "paystub", "import"]);

  function applyViewerMode() {
    const viewer = isViewer();
    document.body.classList.toggle("role-viewer", viewer);
    if (viewer) {
      const active = $(".nav-btn.active");
      const view = active && active.dataset.view;
      if (view && VIEWER_WRITE_VIEWS.has(view)) {
        setView("dashboard");
      }
    }
  }

  function clearIdleTimer() {
    if (state.idleTimer) {
      clearTimeout(state.idleTimer);
      state.idleTimer = null;
    }
  }

  function idleMs() {
    const mins = Number(state.idleMinutes) || DEFAULT_IDLE_MIN;
    return Math.max(10, Math.min(120, mins)) * 60 * 1000;
  }

  function applyIdleMinutes(mins) {
    const n = Number(mins);
    state.idleMinutes = Number.isFinite(n) && n > 0 ? n : DEFAULT_IDLE_MIN;
    armIdleTimer();
  }

  function armIdleTimer() {
    clearIdleTimer();
    if (!state.token) return;
    state.idleTimer = setTimeout(() => {
      idleLogout();
    }, idleMs());
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
          `Signed out after ${state.idleMinutes || DEFAULT_IDLE_MIN} minutes with no tapping. Sign in again.`;
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
        if (Date.now() - state.lastActivity >= idleMs()) {
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
    document.body.classList.remove("role-viewer");
    showPasswordGate(false);
    showApp(false);
  }

  async function afterAuth(data) {
    state.token = data.token || state.token;
    state.user = data;
    if (data.token) localStorage.setItem("budget_token", data.token);
    $("#user-badge").textContent = `${data.display_name || data.username} · ${roleLabel(data.role)}`;
    applyViewerMode();
    if (data.idle_minutes) applyIdleMinutes(data.idle_minutes);
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
    const result = await api("/api/me/password", {
      method: "POST",
      json: {
        current_password: currentPassword,
        new_password: newPassword,
      },
    });
    if (state.user) state.user.must_change_password = false;
    if (result && result.rescue_code) {
      showRescueReveal(result.rescue_code);
      return;
    }
    showPasswordGate(false);
    showApp(true);
    await refreshAll();
  }

  function showRescueReveal(code) {
    const box = $("#rescue-reveal");
    const val = $("#rescue-code-value");
    const form = $("#pw-gate-form");
    if (val) val.textContent = code;
    if (form) form.hidden = true;
    if (box) box.hidden = false;
    showPasswordGate(true);
  }

  function setView(name) {
    $$(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
    $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${name}`));
    if (name === "dashboard") refreshDashboard();
    if (name === "input") refreshInput();
    if (name === "recurring") refreshRecurring();
    if (name === "paystub") refreshPaystub();
    if (name === "import") refreshImportHint();
    if (name === "subs") refreshSubs();
    if (name === "goals") refreshGoals();
    if (name === "cards") refreshCards();
    if (name === "spend") refreshSpend();
    if (name === "debts") refreshDebts();
    if (name === "invest") refreshInvestments();
    if (name === "settings") refreshSettings();
  }

  async function refreshImportHint() {
    const el = $("#import-version-hint");
    if (!el) return;
    try {
      const v = await api("/api/version");
      if (v.chase_pdf_import) {
        el.innerHTML = `App version <strong class="text-primary">${escapeHtml(v.version)}</strong> · Chase PDF import is available. Pick your PDF, bank Chase or Auto, then Preview.`;
      } else {
        el.innerHTML =
          `<span class="text-danger">This install is missing Chase PDF support. Close the app, run <strong>update.bat</strong>, then start.bat again. Hard-refresh the browser (Ctrl+F5).</span>`;
      }
    } catch (_) {
      el.textContent = "";
    }
  }

  // ── Dashboard ───────────────────────────────────────────────

  async function refreshDashboard() {
    $("#month-label").textContent = monthName(state.year, state.month);
    const q = `year=${state.year}&month=${state.month}`;
    const [cal, metrics, upcoming, hh, snap, onboarding, subs] = await Promise.all([
      api(`/api/calendar?${q}`),
      api(`/api/metrics?${q}`),
      api("/api/upcoming"),
      api("/api/household"),
      api("/api/snapshot"),
      api("/api/onboarding").catch(() => null),
      api("/api/subscriptions").catch(() => null),
    ]);
    state.calendar = cal;
    state.metrics = metrics;
    state.household = hh;
    state.snapshot = snap;
    if (hh && hh.idle_minutes) applyIdleMinutes(hh.idle_minutes);
    setHouseholdNameDisplay(hh.name);
    const sub = $("#dash-sub");
    if (sub) {
      const who = (snap.members || []).map((m) => m.display_name).join(" · ");
      sub.textContent = who
        ? `Shared by ${who} · local only`
        : "Cash · plan · goals · debt · investments — all local";
    }
    renderOnboarding(onboarding, hh);
    renderEmptyCoach(onboarding, cal, metrics);
    renderSnapshot(snap, metrics);
    renderFocusStrip(cal, upcoming.items || [], snap, subs);
    renderStats(metrics, cal);
    renderThresholdBanner(cal);
    await renderHomeNotes();
    renderCalendar(cal);
    renderCharts(metrics);
    renderUpcoming(upcoming.items || []);
    if (state.selectedDate) {
      // Keep day panel in sync after paid/edit/delete (no toggle)
      openDayExpand(state.selectedDate, false);
    }
  }

  function renderOnboarding(ob, hh) {
    const panel = $("#onboarding-panel");
    if (!panel) return;
    if (isViewer()) {
      panel.style.display = "none";
      panel.innerHTML = "";
      return;
    }
    if (!ob || ob.onboarding_done || (hh && hh.onboarding_done)) {
      panel.style.display = "none";
      panel.innerHTML = "";
      return;
    }
    // Show until complete OR user dismisses
    const steps = ob.steps || [];
    const done = ob.done_count || 0;
    const total = ob.total || steps.length || 1;
    const pct = Math.round((done / total) * 100);
    panel.style.display = "block";
    panel.innerHTML = `
      <div class="onboarding-inner">
        <div class="onboarding-head">
          <div>
            <div class="section-label" style="margin:0">Getting started</div>
            <h2 style="margin:0.25rem 0 0;font-size:1.1rem">Set up your household budget</h2>
            <p class="text-muted" style="margin:0.35rem 0 0;font-size:0.85rem">
              ${done} of ${total} steps done · local only on this computer
            </p>
          </div>
          <div class="onboarding-actions">
            <button type="button" class="btn btn-ghost btn-sm" id="onboarding-dismiss">Hide checklist</button>
          </div>
        </div>
        <div class="onboarding-progress"><div class="onboarding-progress-bar" style="width:${pct}%"></div></div>
        <ul class="onboarding-steps">
          ${steps
            .map(
              (s) => `<li class="${s.done ? "done" : ""}">
                <span class="ob-check">${s.done ? "✓" : "○"}</span>
                <div>
                  <strong>${escapeHtml(s.label)}</strong>
                  <div class="text-muted" style="font-size:0.8rem">${escapeHtml(s.hint || "")}</div>
                </div>
              </li>`
            )
            .join("")}
        </ul>
        ${
          ob.complete
            ? `<button type="button" class="btn btn-primary btn-sm" id="onboarding-finish">All done — hide this</button>`
            : `<div class="onboarding-quick">
                <button type="button" class="btn btn-outline btn-sm" data-go-view="input">Add bill or pay</button>
                <button type="button" class="btn btn-outline btn-sm" data-go-view="import">Import statement</button>
                <button type="button" class="btn btn-outline btn-sm" data-go-view="settings">Household settings</button>
              </div>`
        }
      </div>`;

    const dismiss = () => dismissOnboarding();
    const dBtn = $("#onboarding-dismiss");
    const fBtn = $("#onboarding-finish");
    if (dBtn) dBtn.addEventListener("click", dismiss);
    if (fBtn) fBtn.addEventListener("click", dismiss);
    panel.querySelectorAll("[data-go-view]").forEach((btn) => {
      btn.addEventListener("click", () => setView(btn.dataset.goView));
    });
  }

  async function dismissOnboarding() {
    try {
      await api("/api/household", {
        method: "PATCH",
        json: { onboarding_done: true },
      });
      if (state.household) state.household.onboarding_done = true;
      const panel = $("#onboarding-panel");
      if (panel) {
        panel.style.display = "none";
        panel.innerHTML = "";
      }
    } catch (ex) {
      alert(ex.message || "Could not save");
    }
  }

  function renderEmptyCoach(ob, cal, metrics) {
    const el = $("#empty-coach");
    if (!el) return;
    const itemCount = ob ? ob.item_count : 0;
    const hasMonthItems = (cal?.days || []).some((d) => (d.items || []).length);
    if (isViewer()) {
      el.style.display = "none";
      el.innerHTML = "";
      return;
    }
    // Show coaching when brand new or this month is empty
    if (itemCount > 0 && hasMonthItems) {
      el.style.display = "none";
      el.innerHTML = "";
      return;
    }
    const brandNew = itemCount === 0;
    el.style.display = "grid";
    el.innerHTML = `
      <div class="coach-card">
        <h3>${brandNew ? "Welcome — start simple" : "This month looks empty"}</h3>
        <p>${
          brandNew
            ? "No bank login needed. Add a few bills and a paycheck, or import a statement. Everything stays on this PC."
            : "Add a bill or paycheck, or import a bank statement. Rent and regular pay show up in later months by themselves."
        }</p>
        <div class="coach-actions">
          <button type="button" class="btn btn-primary btn-sm" data-go-view="input">Add money in/out</button>
          <button type="button" class="btn btn-outline btn-sm" data-go-view="import">Import statement</button>
        </div>
      </div>
      <div class="coach-card coach-tips">
        <h3>Quick tips</h3>
        <ul>
          <li><strong>Green act</strong> = money you know about (pay, actuals, paid bills).</li>
          <li><strong>Orange est</strong> = full plan including unpaid bills and estimates.</li>
          <li>Log a <strong>bank balance</strong> on any day to reset totals to real life.</li>
          <li>Set a <strong>safety amount</strong> under Household so low days stand out.</li>
        </ul>
      </div>`;
    el.querySelectorAll("[data-go-view]").forEach((btn) => {
      btn.addEventListener("click", () => setView(btn.dataset.goView));
    });
  }

  async function renderHomeNotes() {
    const el = $("#home-notes");
    if (!el) return;
    let runtime = null;
    try {
      runtime = await api("/api/runtime");
    } catch (_) {
      el.innerHTML = "";
      return;
    }
    if (runtime.idle_minutes) applyIdleMinutes(runtime.idle_minutes);
    const notes = [];
    if (runtime.in_docker) {
      notes.push(
        `<div class="note-card">Leave <strong>Docker Desktop</strong> running while you use this. Closing it closes the app.</div>`
      );
    }
    if (runtime.backup_nag) {
      notes.push(
        `<div class="note-card note-warn">No backup this month yet. Open <button type="button" class="btn btn-ghost btn-sm" data-go-view="settings">Household</button> and tap <strong>Save a copy on this computer</strong>.</div>`
      );
    }
    if (!runtime.has_recovery_key) {
      notes.push(
        `<div class="note-card note-warn">Make a <strong>rescue code</strong> under Household so a forgotten password does not erase your budget.</div>`
      );
    }
    el.innerHTML = notes.join("");
    el.querySelectorAll("[data-go-view]").forEach((btn) => {
      btn.addEventListener("click", () => setView(btn.dataset.goView));
    });
  }

  function buildPrintReport() {
    const cal = state.calendar;
    const m = state.metrics;
    const hh = state.household;
    if (!cal || !m || !hh) {
      alert("Load the Home month first, then try Print month again.");
      return false;
    }

    const title = monthName(cal.year, cal.month);
    const hhName = hh.name || "Household";
    const printed = new Date().toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
    const thr = Number(cal.safety_threshold || 0);
    const endAct = cal.ending_balance_actual ?? cal.ending_balance;
    const endEst = cal.ending_balance_est ?? cal.ending_balance;

    // Collect items from calendar days
    const rows = [];
    (cal.days || []).forEach((day) => {
      (day.items || []).forEach((it) => {
        rows.push({
          date: day.date,
          name: it.name,
          type: it.item_type,
          amount: it.amount,
          is_income: it.is_income || it.item_type === "paycheck",
          balance: it.item_type === "balance",
        });
      });
    });

    const lowDays = (cal.days || []).filter((d) => d.warn_est || d.warn_actual);
    const lowList = lowDays
      .map((d) => {
        const tags = [];
        if (d.warn_actual) tags.push("act");
        if (d.warn_est) tags.push("est");
        return `${d.date} (${tags.join("+")})`;
      })
      .join(", ");

    const itemRows =
      rows.length === 0
        ? `<tr><td colspan="4">No items recorded this month.</td></tr>`
        : rows
            .map((r) => {
              let amt;
              let cls = "";
              if (r.balance) {
                amt = `= ${money(r.amount)}`;
              } else if (r.is_income) {
                amt = `+${money(r.amount)}`;
                cls = "in";
              } else {
                amt = `−${money(r.amount)}`;
                cls = "out";
              }
              return `<tr>
                <td>${escapeHtml(r.date)}</td>
                <td>${escapeHtml(r.name)}</td>
                <td>${escapeHtml(r.type)}</td>
                <td class="num ${cls}">${amt}</td>
              </tr>`;
            })
            .join("");

    const warnBlock =
      thr > 0
        ? `<div class="print-warn">
            <strong>Safety amount:</strong> ${money(thr)}
            ${
              lowDays.length
                ? `<div class="print-low-days"><strong>Days at or below:</strong> ${escapeHtml(lowList)}</div>`
                : `<div class="print-low-days">No days this month fall at or below this amount.</div>`
            }
          </div>`
        : `<div class="print-warn">No safety amount set (optional under Household settings).</div>`;

    const el = $("#print-report");
    if (!el) return false;
    el.innerHTML = `
      <h1>Month overview</h1>
      <div class="print-meta">
        <strong>${escapeHtml(hhName)}</strong> · ${escapeHtml(title)}<br/>
        Printed ${escapeHtml(printed)} · Household Money (local only — not a bank statement)
      </div>

      <h2>Summary</h2>
      <div class="print-summary">
        <div class="print-card"><div class="lbl">Income</div><div class="val">${money(m.month_income)}</div></div>
        <div class="print-card"><div class="lbl">Expenses</div><div class="val">${money(m.month_expenses)}</div></div>
        <div class="print-card"><div class="lbl">Net</div><div class="val">${money(m.net)}</div></div>
        <div class="print-card"><div class="lbl">Confirmed, month end</div><div class="val">${money(endAct)}</div></div>
        <div class="print-card"><div class="lbl">Month-end estimate</div><div class="val">${money(endEst)}</div></div>
        <div class="print-card"><div class="lbl">Starting cash</div><div class="val">${money(cal.starting_balance)}</div></div>
      </div>

      <h2>Safety check</h2>
      ${warnBlock}

      <h2>Items this month</h2>
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Name</th>
            <th>Type</th>
            <th class="num">Amount</th>
          </tr>
        </thead>
        <tbody>${itemRows}</tbody>
      </table>

      <div class="print-footer">
        Generated by Household Money for household planning. Figures may include estimates.
        Keep this paper private — it can show income and bill details.
      </div>
    `;
    el.setAttribute("aria-hidden", "false");
    return true;
  }

  function printMonthOverview() {
    if (!buildPrintReport()) return;
    // Allow layout to settle, then print
    setTimeout(() => {
      window.print();
      const el = $("#print-report");
      if (el) el.setAttribute("aria-hidden", "true");
    }, 100);
  }

  function renderThresholdBanner(cal) {
    const el = $("#threshold-banner");
    if (!el) return;
    const thr = Number(cal.safety_threshold || 0);
    const estDays = Number(cal.warn_days_est || 0);
    const actDays = Number(cal.warn_days_actual || 0);
    if (thr <= 0) {
      el.style.display = "none";
      el.textContent = "";
      return;
    }
    if (estDays <= 0 && actDays <= 0) {
      el.style.display = "none";
      el.className = "alert alert-success";
      el.style.display = "block";
      el.textContent = `Safety check: no days this month fall at or below ${money(thr)}.`;
      return;
    }
    el.className = "alert alert-warning";
    el.style.display = "block";
    const parts = [];
    if (estDays > 0) {
      parts.push(
        `${estDays} day${estDays === 1 ? "" : "s"} where planned (est) balance is at or below ${money(thr)}`
      );
    }
    if (actDays > 0) {
      parts.push(
        `${actDays} day${actDays === 1 ? "" : "s"} where confirmed (act) balance is at or below ${money(thr)}`
      );
    }
    el.textContent = `Safety warning: ${parts.join(" · ")}. Change the amount under Household.`;
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

  function renderSnapshot(s, m) {
    const el = $("#snapshot-hero");
    if (!el) return;
    const nwCls = s.net_worth >= 0 ? "positive" : "negative";
    const spent = m ? Number(m.month_expenses || 0) : 0;
    const got = m ? Number(m.month_income || 0) : 0;
    const monthNet = got - spent;
    const monthNetCls = monthNet >= 0 ? "positive" : "negative";
    const members = (s.members || [])
      .map((mm) => `<span>${escapeHtml(mm.display_name)}</span>`)
      .join("");
    el.innerHTML = `
      <div class="snap-net">
        <div class="stat-label">Simple net worth ${helpBtn("Rough big picture: cash + investments minus debts. Not a bank balance by itself — goals saved are tracked separately.")}</div>
        <div class="stat-value ${nwCls}">${money(s.net_worth)}</div>
        <div class="stat-hint">Cash + investments − debts</div>
        <div class="snap-members">${members || "<span>Household</span>"}</div>
      </div>
      <div class="stat">
        <div class="stat-label">This month ${helpBtn("Spent / income for the month on the calendar. The number underneath is income minus spent (green if ahead, red if behind). Bank-balance snapshots are not counted as spending.")}</div>
        <div class="stat-hint">Spent / income</div>
        <div class="stat-value snap-flow"><span class="negative">${money(spent)}</span><span class="snap-flow-sep"> / </span><span class="positive">${money(got)}</span></div>
        <div class="snap-tally ${monthNetCls}">${money(monthNet)}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Cash ${helpBtn("Latest bank balance you entered, or starting cash from Household settings if you have not logged a bank balance yet.")}</div>
        <div class="stat-value ${Number(s.cash) >= 0 ? "positive" : "negative"}">${money(s.cash)}</div>
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
      <div class="stat snap-link" data-go-goals role="link" title="Open Goals">
        <div class="stat-label">Goals saved ${helpBtn("Money you marked as saved toward goals (vacation, house…). Tracked on the Goals page — not automatically pulled from the bank. Tap this tile to open Goals.")}</div>
        <div class="stat-value" style="color:var(--brand-light)">${money(s.goals_saved)}</div>
        <div class="stat-hint">of ${money(s.goals_target)} target · ${s.goal_count} goal${s.goal_count === 1 ? "" : "s"} · tap to open</div>
      </div>`;
    el.querySelector("[data-go-goals]")?.addEventListener("click", (e) => {
      if (e.target.closest(".help-icon")) return;
      setView("goals");
    });
  }

  function renderFocusStrip(cal, upcoming, snap, subs) {
    if (subs) state.subs = subs;
    subs = subs || state.subs;
    const el = $("#focus-strip");
    if (!el) return;
    const today = isoDate();
    const dueSoon = (upcoming || [])
      .filter((it) => {
        const d = daysBetween(today, it.due_date);
        return d >= 0 && d <= 7 && it.item_type === "bill" && !it.is_paid;
      })
      .slice(0, 5);
    const paydays = (upcoming || [])
      .filter((it) => {
        const d = daysBetween(today, it.due_date);
        return d >= 0 && d <= 14 && it.item_type === "paycheck";
      })
      .slice(0, 4);
    const lowDays = (cal.days || [])
      .filter((d) => d.warn_actual || d.warn_est)
      .slice(0, 5);
    const asOf = snap && snap.cash_as_of;
    const staleDays = asOf ? daysBetween(asOf, today) : null;
    const stale = !asOf || staleDays >= 7;
    const skipped = localStorage.getItem("focus_bank_skip") === today;
    const viewer = isViewer();

    const dueHtml = dueSoon.length
      ? dueSoon
          .map((it) => {
            const d = daysBetween(today, it.due_date);
            const when = d === 0 ? "Today" : d === 1 ? "Tomorrow" : it.due_date.slice(5);
            const btn = viewer
              ? ""
              : `<button type="button" class="btn btn-primary btn-sm" data-focus-paid="${it.id}">Paid</button>`;
            return `<div class="focus-row">
              <div class="focus-main">
                <div class="focus-name">${escapeHtml(it.name)}</div>
                <div class="focus-meta">${when} · ${money(it.amount)}</div>
              </div>
              ${btn}
            </div>`;
          })
          .join("")
      : `<p class="focus-empty">No unpaid bills in the next 7 days.</p>`;

    const payHtml = paydays.length
      ? paydays
          .map((it) => {
            const d = daysBetween(today, it.due_date);
            const when = d === 0 ? "Today" : d === 1 ? "Tomorrow" : it.due_date.slice(5);
            const btn =
              viewer || it.is_paid
                ? it.is_paid
                  ? `<span class="chip chip-success">in</span>`
                  : ""
                : `<button type="button" class="btn btn-outline btn-sm" data-focus-paid="${it.id}">It hit</button>`;
            return `<div class="focus-row">
              <div class="focus-main">
                <div class="focus-name">${escapeHtml(it.name)}</div>
                <div class="focus-meta">${when} · ${money(it.amount)}</div>
              </div>
              ${btn}
            </div>`;
          })
          .join("")
      : `<p class="focus-empty">No paydays in the next 2 weeks.</p>`;

    let bankBody;
    if (asOf) {
      bankBody = `<p class="focus-empty" style="margin-bottom:0.35rem">Last logged ${asOf}${
        staleDays != null ? ` · ${staleDays} day${staleDays === 1 ? "" : "s"} ago` : ""
      } · ${money(snap.cash)}</p>`;
    } else {
      bankBody = `<p class="focus-empty" style="margin-bottom:0.35rem">No bank balance logged yet. Starting cash is ${money(
        snap.cash || 0
      )}.</p>`;
    }
    if (stale && !viewer && !skipped) {
      bankBody += `
        <p class="focus-empty">What does checking show today?</p>
        <form class="focus-bank-form" id="focus-bank-form">
          <input id="focus-bank-amount" class="input-money" type="number" min="0.01" step="0.01" required placeholder="0.00" />
          <button class="btn btn-primary btn-sm" type="submit">Save</button>
          <button class="btn btn-ghost btn-sm" type="button" id="focus-bank-skip">Not now</button>
        </form>`;
    }

    const lowHtml = lowDays.length
      ? lowDays
          .map((d) => {
            const kind = d.warn_actual ? "act" : "est";
            const amt = d.warn_actual ? d.running_balance_actual : d.running_balance_est;
            return `<div class="focus-row">
              <div class="focus-main">
                <div class="focus-name">${d.date}</div>
                <div class="focus-meta">Low ${kind} · ${money(amt)}</div>
              </div>
              <button type="button" class="btn btn-ghost btn-sm" data-focus-day="${d.date}">Open</button>
            </div>`;
          })
          .join("")
      : `<p class="focus-empty">${
          cal.safety_threshold > 0 ? "No low-cash days this month." : "Set a safety amount under Household to flag tight days."
        }</p>`;

    const subCount = subs && subs.count ? subs.count : 0;
    const subHtml = subCount
      ? `<p class="focus-empty" style="margin:0 0 0.35rem"><strong class="text-primary">${money(subs.monthly_total)}</strong>/mo</p>
         <p class="focus-empty" style="margin:0 0 0.55rem">${money(subs.yearly_total)} a year · ${subCount} service${subCount === 1 ? "" : "s"}</p>
         <button type="button" class="btn btn-outline btn-sm" data-go-subs>Open list</button>`
      : `<p class="focus-empty">Add Apple, Netflix, gym… so they stop hiding on the card.</p>
         <button type="button" class="btn btn-outline btn-sm" data-go-subs>Add subscriptions</button>`;

    el.innerHTML = `
      <div class="focus-card">
        <h3>Due this week</h3>
        ${dueHtml}
      </div>
      <div class="focus-card">
        <h3>Paydays</h3>
        ${payHtml}
      </div>
      <div class="focus-card">
        <h3>Bank balance</h3>
        ${bankBody}
        ${lowDays.length ? `<div style="margin-top:0.65rem">${lowHtml}</div>` : `<div style="margin-top:0.35rem">${lowHtml}</div>`}
      </div>
      <div class="focus-card">
        <h3>Subscriptions</h3>
        ${subHtml}
      </div>`;

    el.querySelectorAll("[data-focus-paid]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await api(`/api/items/${btn.dataset.focusPaid}/toggle-paid`, { method: "POST" });
          await refreshDashboard();
        } catch (ex) {
          alert(ex.message || "Could not update");
        }
      });
    });
    el.querySelectorAll("[data-focus-day]").forEach((btn) => {
      btn.addEventListener("click", () => openDayExpand(btn.dataset.focusDay, true));
    });
    el.querySelectorAll("[data-go-subs]").forEach((btn) => {
      btn.addEventListener("click", () => setView("subs"));
    });
    const skip = $("#focus-bank-skip");
    if (skip) {
      skip.addEventListener("click", () => {
        localStorage.setItem("focus_bank_skip", today);
        renderFocusStrip(cal, upcoming, snap);
      });
    }
    const form = $("#focus-bank-form");
    if (form) {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const amt = parseFloat($("#focus-bank-amount").value);
        if (!amt || amt <= 0) return;
        try {
          await api("/api/items", {
            method: "POST",
            json: {
              name: "Bank balance",
              item_type: "balance",
              amount: amt,
              due_date: today,
              frequency: "once",
              retain_name: true,
            },
          });
          localStorage.removeItem("focus_bank_skip");
          await refreshDashboard();
        } catch (ex) {
          alert(ex.message || "Could not save bank balance");
        }
      });
    }
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
        label: "Confirmed, month end",
        help: "Where cash sits at month end using only money that already moved: pay, bills you marked Paid, and imported bank lines. Unpaid bills (mortgage still due, electric not paid yet) do not come out of this number. A bank-balance entry on a day resets this from that amount forward.",
        value: endAct,
        cls: endAct >= 0 ? "positive" : "negative",
        hint: "Pay + Paid only",
      },
      {
        label: "If everything is paid",
        help: "Same month, but unpaid bills and estimates come out too — the “will I make it?” number. Use this to see overspending before you tap Paid.",
        value: endEst,
        cls: endEst >= 0 ? "positive" : "negative",
        hint: "Includes unpaid bills",
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
          return `<div class="pill ${pillClass(it)}" title="${escapeHtml(it.name)} ${money(it.amount)}">${sign}${Math.round(it.amount)} ${escapeHtml(it.name)}</div>`;
        })
        .join("");
      const more =
        day.items.length > 3
          ? `<div class="pill" style="opacity:0.65">+${day.items.length - 3} more · click</div>`
          : "";
      const anchor = day.balance_anchored
        ? `<span class="cal-anchor-dot" title="Bank balance set this day"></span>`
        : "";
      const warnEst = !!day.warn_est;
      const warnAct = !!day.warn_actual;
      const warnClass = `${warnEst ? "warn-est" : ""} ${warnAct ? "warn-act" : ""}`.trim();
      let warnBadge = "";
      if (warnAct) {
        warnBadge = `<span class="cal-warn-badge act" title="Confirmed balance at or below your safety amount">Low act</span>`;
      } else if (warnEst) {
        warnBadge = `<span class="cal-warn-badge est" title="Planned balance at or below your safety amount">Low est</span>`;
      }
      const ariaWarn = warnAct
        ? " low confirmed balance"
        : warnEst
          ? " low planned balance"
          : "";

      html += `
        <div class="cal-cell ${isToday ? "today" : ""} ${selected} ${warnClass}" data-date="${day.date}" role="button" tabindex="0" aria-label="Open ${day.date}${ariaWarn}">
          ${warnBadge}
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
    if (!panel) return;
    if (!day) {
      // Selected day not in this month (e.g. after month change)
      closeDayExpand();
      return;
    }

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
    const thr = Number(state.calendar.safety_threshold || 0);
    let sub = day.balance_anchored
      ? "Bank balance was set this day — running totals restart from that amount."
      : `${day.items.length} item${day.items.length === 1 ? "" : "s"} · click the day again to close`;
    if (thr > 0 && (day.warn_actual || day.warn_est)) {
      const bits = [];
      if (day.warn_actual) bits.push("confirmed (act)");
      if (day.warn_est) bits.push("planned (est)");
      sub =
        `Below your safety amount of ${money(thr)} on ${bits.join(" and ")} balance. ` +
        sub;
    }
    $("#day-expand-sub").textContent = sub;

    // Optional alert block under day header
    let warnEl = panel.querySelector(".day-expand-warn");
    if (!warnEl) {
      warnEl = document.createElement("div");
      warnEl.className = "day-expand-warn";
      const body = panel.querySelector(".day-expand-body");
      if (body) panel.insertBefore(warnEl, body);
    }
    if (thr > 0 && (day.warn_actual || day.warn_est)) {
      warnEl.className = `day-expand-warn alert ${day.warn_actual ? "alert-danger" : "alert-warning"}`;
      warnEl.style.display = "block";
      warnEl.textContent = day.warn_actual
        ? `Safety warning: confirmed cash is at or below ${money(thr)} on this day.`
        : `Safety warning: planned cash (est) is at or below ${money(thr)} on this day.`;
    } else {
      warnEl.style.display = "none";
      warnEl.textContent = "";
    }

    const tbody = $("#day-expand-table tbody");
    if (!day.items.length) {
      tbody.innerHTML = `<tr><td colspan="5" class="day-expand-empty">Nothing scheduled — add bills, estimates, pay, or a bank balance on Input.</td></tr>`;
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
          const paidChip =
            it.item_type === "bill" && it.is_paid
              ? `<span class="chip chip-success" style="margin-left:0.35rem">paid</span>`
              : "";
          const paidBtn =
            !isViewer() && it.item_type === "bill"
              ? `<button type="button" class="btn btn-ghost btn-sm" data-toggle-paid="${it.id}" title="Mark paid or unpaid">${it.is_paid ? "Unpaid" : "Paid"}</button>`
              : "";
          const monthlyBtn =
            !isViewer() && it.item_type === "actual" && !it.is_income
              ? `<button type="button" class="btn btn-outline btn-sm" data-to-monthly="${it.id}">Make monthly bill</button>`
              : "";
          const actions = isViewer()
            ? ""
            : `<td class="day-actions">
              ${paidBtn}
              ${monthlyBtn}
              <button type="button" class="btn btn-ghost btn-sm" data-edit-item="${it.id}">Edit</button>
              <button type="button" class="btn btn-ghost btn-sm text-danger" data-del-item="${it.id}">Delete</button>
            </td>`;
          return `<tr class="${it.is_paid && it.item_type === "bill" ? "row-paid" : ""}">
            <td>${escapeHtml(it.name)}${paidChip}</td>
            <td><span class="chip chip-${typeChip(it)}">${it.item_type}</span></td>
            ${amountCell}
            <td class="text-muted">${escapeHtml(it.notes || "")}</td>
            ${actions}
          </tr>`;
        })
        .join("");

      tbody.querySelectorAll("[data-toggle-paid]").forEach((btn) => {
        btn.addEventListener("click", async (e) => {
          e.stopPropagation();
          try {
            await api(`/api/items/${btn.dataset.togglePaid}/toggle-paid`, {
              method: "POST",
            });
            await refreshDashboard();
          } catch (ex) {
            alert(ex.message || "Could not update paid status");
          }
        });
      });
      tbody.querySelectorAll("[data-edit-item]").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          const id = Number(btn.dataset.editItem);
          const item = day.items.find((x) => x.id === id);
          if (item) openEditItemModal(item);
        });
      });
      tbody.querySelectorAll("[data-to-monthly]").forEach((btn) => {
        btn.addEventListener("click", async (e) => {
          e.stopPropagation();
          try {
            const data = await api(`/api/items/${btn.dataset.toMonthly}/to-monthly-bill`, {
              method: "POST",
            });
            alert(data.message || "Added as a monthly bill.");
            await refreshDashboard();
            await refreshRecurring().catch(() => {});
          } catch (ex) {
            alert(ex.message || "Could not add monthly bill");
          }
        });
      });
      tbody.querySelectorAll("[data-del-item]").forEach((btn) => {
        btn.addEventListener("click", async (e) => {
          e.stopPropagation();
          const id = Number(btn.dataset.delItem);
          const item = day.items.find((x) => x.id === id);
          const scope = await confirmDeleteItem(item || { frequency: "once" });
          if (!scope) return;
          try {
            await api(`/api/items/${id}?scope=${encodeURIComponent(scope)}`, { method: "DELETE" });
            await refreshDashboard();
            await refreshInput().catch(() => {});
          } catch (ex) {
            alert(ex.message || "Could not delete");
          }
        });
      });
    }
    panel.classList.add("open");
    if (toggle) {
      panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  function closeDayExpand() {
    state.selectedDate = null;
    const panel = $("#day-expand");
    if (panel) panel.classList.remove("open");
    $$(".cal-cell[data-date]").forEach((c) => c.classList.remove("selected"));
  }

  function openEditItemModal(item) {
    const modal = $("#edit-item-modal");
    if (!modal || !item) return;
    $("#edit-item-id").value = item.id;
    $("#edit-item-name").value = item.name || "";
    $("#edit-item-amount").value = item.amount;
    $("#edit-item-date").value = item.due_date;
    $("#edit-item-type").value = item.item_type || "bill";
    $("#edit-item-freq").value = item.frequency || "once";
    $("#edit-item-notes").value = item.notes || "";
    $("#edit-item-category").value = item.category || "";
    const paid = $("#edit-item-paid");
    if (paid) paid.checked = !!item.is_paid;
    const subBox = $("#edit-item-sub");
    if (subBox) subBox.checked = item.is_subscription === true;
    const paidRow = $("#edit-item-paid-row");
    if (paidRow) {
      paidRow.style.display =
        item.item_type === "bill" || item.item_type === "estimate" ? "" : "none";
    }
    const msg = $("#edit-item-msg");
    if (msg) msg.textContent = "";
    const scopeRow = $("#edit-item-scope-row");
    if (scopeRow) {
      const repeating = isRecurringItem(item);
      scopeRow.hidden = !repeating;
      const thisRadio = document.querySelector('input[name="edit-item-scope"][value="this"]');
      if (thisRadio) thisRadio.checked = true;
    }
    modal.hidden = false;
  }

  function closeEditItemModal() {
    const modal = $("#edit-item-modal");
    if (modal) modal.hidden = true;
  }

  async function copyLastMonth() {
    let fromYear = state.year;
    let fromMonth = state.month - 1;
    if (fromMonth < 1) {
      fromMonth = 12;
      fromYear -= 1;
    }
    if (
      !confirm(
        `Copy recurring bills/estimates/paychecks from ${monthName(fromYear, fromMonth)} into ${monthName(state.year, state.month)}?\n\nOne-time items are skipped. Existing matches are not duplicated.`
      )
    ) {
      return;
    }
    try {
      const qs = new URLSearchParams({
        from_year: String(fromYear),
        from_month: String(fromMonth),
        to_year: String(state.year),
        to_month: String(state.month),
        only_recurring: "true",
      });
      const data = await api(`/api/items/copy-month?${qs}`, { method: "POST" });
      alert(data.message || `Copied ${data.created || 0} item(s).`);
      await refreshDashboard();
      await refreshInput().catch(() => {});
    } catch (ex) {
      alert(ex.message || "Copy failed");
    }
  }

  async function downloadBackup() {
    const msg = $("#backup-msg");
    try {
      if (msg) msg.textContent = "Preparing backup…";
      const res = await fetch("/api/backup", {
        headers: { Authorization: `Bearer ${state.token}` },
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.detail || "Backup failed");
      }
      const blob = await res.blob();
      const cd = res.headers.get("content-disposition") || "";
      const match = cd.match(/filename="?([^"]+)"?/i);
      const fname =
        match?.[1] ||
        `household-money-backup-${new Date().toISOString().slice(0, 10)}.db`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = fname;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      if (msg) msg.textContent = "Backup downloaded. Keep the file somewhere safe.";
    } catch (ex) {
      if (msg) msg.textContent = ex.message || "Backup failed";
      alert(ex.message || "Backup failed");
    }
  }

  async function restoreBackup(file) {
    const msg = $("#backup-msg");
    if (!file) return;
    if (
      !confirm(
        "Restore will REPLACE all current budget data with this backup file.\n\nA copy of the current database is saved in the data folder first.\n\nContinue?"
      )
    ) {
      return;
    }
    try {
      if (msg) msg.textContent = "Restoring…";
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch("/api/restore", {
        method: "POST",
        headers: { Authorization: `Bearer ${state.token}` },
        body: fd,
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.detail || "Restore failed");
      }
      const data = await res.json();
      alert(
        (data.message || "Restored.") +
          "\n\nYou will be signed out — sign in again with the passwords from the backup."
      );
      logout(false);
    } catch (ex) {
      if (msg) msg.textContent = ex.message || "Restore failed";
      alert(ex.message || "Restore failed");
    }
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
          labels: ["Income", "Paid", "Still due"],
          datasets: [
            {
              data: [m.month_income, m.month_paid, m.month_still_due],
              backgroundColor: ["#3fb950", "#a371f7", "#d29922"],
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
      tbody.innerHTML = `<tr><td colspan="5" class="text-muted">Nothing upcoming — add bills or pay on Input, or Copy last month.</td></tr>`;
      return;
    }
    tbody.innerHTML = items
      .map((it) => {
        const cls = it.is_income ? "positive" : "negative";
        const sign = it.is_income ? "+" : "−";
        const paid =
          it.item_type === "bill" && it.is_paid
            ? ` <span class="chip chip-success">paid</span>`
            : "";
        const paidBtn =
          !isViewer() && it.item_type === "bill"
            ? `<button type="button" class="btn btn-ghost btn-sm" data-up-paid="${it.id}">${it.is_paid ? "Undo" : "Paid"}</button>`
            : "";
        return `<tr>
          <td>${it.due_date}</td>
          <td>${escapeHtml(it.name)}${paid}</td>
          <td><span class="chip chip-${typeChip(it)}">${it.item_type}</span></td>
          <td class="num ${cls}">${sign}${money(it.amount)}</td>
          <td>${paidBtn}</td>
        </tr>`;
      })
      .join("");
    tbody.querySelectorAll("[data-up-paid]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await api(`/api/items/${btn.dataset.upPaid}/toggle-paid`, {
            method: "POST",
          });
          await refreshDashboard();
        } catch (ex) {
          alert(ex.message || "Could not update");
        }
      });
    });
  }

  function typeChip(it) {
    const t = typeof it === "string" ? it : (it && it.item_type) || "";
    const income = t === "paycheck" || (typeof it === "object" && it && it.is_income);
    if (t === "paycheck" || (t === "actual" && income)) return "success";
    if (t === "actual") return "actual";
    if (t === "estimate") return "warning";
    if (t === "balance") return "brand";
    if (t === "bill") return "info";
    return "brand";
  }

  function pillClass(it) {
    if (it.item_type === "actual" && it.is_income) return "pill-paycheck";
    return `pill-${it.item_type}`;
  }

  function monthlyFromNet(net, freq) {
    const n = Number(net) || 0;
    if (freq === "weekly") return round2((n * 52) / 12);
    if (freq === "biweekly") return round2((n * 26) / 12);
    if (freq === "semimonthly") return round2(n * 2);
    return round2(n);
  }

  function updatePaystubMonthly() {
    const el = $("#ps-monthly");
    if (!el) return;
    el.textContent = money(monthlyFromNet($("#ps-net")?.value, $("#ps-freq")?.value));
  }

  function fillPaystubForm(p, extra = {}) {
    if (!p) return;
    if ($("#ps-employer")) $("#ps-employer").value = p.employer || extra.employer || "";
    if ($("#ps-who")) {
      $("#ps-who").value = p.employee_name || p.employee_label || extra.employee_label || "";
    }
    if ($("#ps-net") && (p.net_pay || extra.net_pay)) {
      $("#ps-net").value = p.net_pay || extra.net_pay;
    }
    if ($("#ps-gross")) $("#ps-gross").value = p.gross_pay || extra.gross_pay || 0;
    if ($("#ps-date") && (p.pay_date || extra.last_pay_date)) {
      $("#ps-date").value = p.pay_date || extra.last_pay_date;
    }
    const freq = p.frequency_guess || p.frequency || extra.frequency;
    if ($("#ps-freq") && freq && ["weekly", "biweekly", "semimonthly", "monthly"].includes(freq)) {
      $("#ps-freq").value = freq;
    }
    const conf = $("#paystub-confidence");
    if (conf) {
      conf.textContent = p.confidence
        ? `Parsed with ${p.confidence} confidence. Check net pay and pay date.`
        : "Check these numbers, then apply.";
    }
    const box = $("#paystub-deductions");
    if (box) {
      const rows = [
        ["Federal tax", p.federal_tax],
        ["State tax", p.state_tax],
        ["Social Security", p.social_security],
        ["Medicare", p.medicare],
        ["Retirement", p.retirement],
        ["Health", p.health_insurance],
      ].filter(([, v]) => v != null && Number(v) > 0);
      box.innerHTML = rows
        .map(
          ([k, v]) =>
            `<div class="stat"><div class="stat-label">${escapeHtml(k)}</div><div class="stat-value">${money(v)}</div></div>`
        )
        .join("");
    }
    updatePaystubMonthly();
  }

  async function refreshPaystub() {
    updatePaystubMonthly();
    const box = $("#jobs-list");
    if (!box) return;
    let jobs = [];
    try {
      jobs = await api("/api/jobs");
    } catch (_) {
      box.innerHTML = `<div class="empty"><h3>Could not load jobs</h3></div>`;
      return;
    }
    if (!jobs.length) {
      box.innerHTML = `<div class="empty"><h3>No saved jobs yet</h3><p>Apply a pay stub with “Save as job profile” checked.</p></div>`;
      return;
    }
    box.innerHTML = jobs
      .map((j) => {
        const title = [j.employee_label, j.employer].filter(Boolean).join(" · ") || "Job";
        const next = (j.next_pay_dates || []).slice(0, 3).join(", ") || "—";
        const actions = isViewer()
          ? ""
          : `<div class="goal-actions">
            <button class="btn btn-outline btn-sm" type="button" data-job-use="${j.id}">Use these numbers</button>
            <button class="btn btn-primary btn-sm" type="button" data-job-cal="${j.id}">Put pay on calendar</button>
            <button class="btn btn-ghost btn-sm" type="button" data-job-del="${j.id}">Delete</button>
          </div>`;
        return `<div class="goal-card">
          <h3>${escapeHtml(title)}</h3>
          <div class="goal-meta">
            <div>Net <strong>${money(j.net_pay)}</strong> · ${escapeHtml(j.frequency)}</div>
            <div>About <strong>${money(j.monthly_net_estimate)}</strong>/mo take-home</div>
            <div>Last pay: ${j.last_pay_date || "—"}</div>
            <div>Next: ${escapeHtml(next)}</div>
          </div>
          ${actions}
        </div>`;
      })
      .join("");
    box.querySelectorAll("[data-job-del]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!confirm("Remove this saved job?")) return;
        await api(`/api/jobs/${btn.dataset.jobDel}`, { method: "DELETE" });
        await refreshPaystub();
      });
    });
    box.querySelectorAll("[data-job-cal]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          const res = await api(`/api/jobs/${btn.dataset.jobCal}/to-calendar`, { method: "POST" });
          alert(res.message || "Added to the calendar.");
          await refreshDashboard().catch(() => {});
          await refreshRecurring().catch(() => {});
        } catch (ex) {
          alert(ex.message);
        }
      });
    });
    box.querySelectorAll("[data-job-use]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const job = jobs.find((x) => String(x.id) === String(btn.dataset.jobUse));
        if (job) fillPaystubForm(job, job);
      });
    });
  }

  async function refreshRecurring() {
    const data = await api("/api/recurring");
    const box = $("#recurring-list");
    if (!box) return;
    const items = data.items || [];
    if (!items.length) {
      box.innerHTML = `<div class="empty"><h3>No repeating bills yet</h3><p>Add mortgage, car, electric, water here. For water, change This month when the bill is different — later months stay the usual amount.</p></div>`;
      return;
    }
    const viewer = isViewer();
    box.innerHTML = `
      <div class="table-wrap">
        <table class="data">
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th>Due day</th>
              <th class="num">This month $</th>
              <th class="num">Usual $</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            ${items
              .map((r) => {
                const thisAmt = r.this_month_amount != null ? r.this_month_amount : "";
                const thisCell = r.this_month_id
                  ? `<input class="input-money" data-rec-this="${r.this_month_id}" type="number" min="0.01" step="0.01" value="${thisAmt}" style="width:6.5rem" title="${r.this_month_date || ""}" />`
                  : `<span class="text-muted">—</span>`;
                const actions = viewer
                  ? ""
                  : `${
                      r.this_month_id
                        ? `<button class="btn btn-outline btn-sm" type="button" data-rec-save-this="${r.this_month_id}">This month</button> `
                        : ""
                    }<button class="btn btn-primary btn-sm" type="button" data-rec-save-later="${r.next_id}">Usual</button>
                    <button class="btn btn-ghost btn-sm" type="button" data-rec-stop="${r.next_id}">Stop</button>`;
                return `<tr data-rec-row="${r.next_id}" data-this-id="${r.this_month_id || ""}" data-this-date="${r.this_month_date || ""}">
                  <td>${
                    viewer
                      ? escapeHtml(r.name)
                      : `<input type="text" data-rec-name="${r.next_id}" value="${escapeAttr(r.name)}" maxlength="120" style="min-width:10rem" />`
                  }</td>
                  <td><span class="chip chip-${typeChip(r)}">${escapeHtml(r.item_type)}</span></td>
                  <td>${
                    viewer
                      ? r.due_day
                      : `<input type="number" data-rec-day="${r.next_id}" min="1" max="28" value="${r.due_day}" style="width:3.5rem" />`
                  }</td>
                  <td class="num">${thisCell}</td>
                  <td class="num">${
                    viewer
                      ? money(r.typical_amount)
                      : `<input class="input-money" data-rec-typical="${r.next_id}" type="number" min="0.01" step="0.01" value="${r.typical_amount}" style="width:6.5rem" />`
                  }</td>
                  <td class="day-actions">${actions}</td>
                </tr>`;
              })
              .join("")}
          </tbody>
        </table>
      </div>
      <p class="form-hint" style="margin-top:0.65rem">This month = water/electric this cycle only. Usual = later months. Stop ends the repeat from the next date.</p>`;
    box.querySelectorAll("[data-rec-save-this]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = btn.dataset.recSaveThis;
        const tr = btn.closest("tr");
        const input = box.querySelector(`[data-rec-this="${id}"]`);
        const amt = parseFloat(input && input.value);
        if (!amt || amt <= 0) return;
        const payload = { amount: amt };
        const thisDate = (tr && tr.dataset.thisDate) || "";
        const dayEl = tr && tr.querySelector("[data-rec-day]");
        const dueDay = parseInt(dayEl && dayEl.value, 10);
        if (thisDate && dueDay) {
          const parts = String(thisDate).split("-");
          const last = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10), 0).getDate();
          const day = Math.min(Math.max(dueDay, 1), last);
          payload.due_date = `${parts[0]}-${parts[1]}-${String(day).padStart(2, "0")}`;
        }
        try {
          await api(`/api/items/${id}?scope=this`, { method: "PATCH", json: payload });
          await refreshRecurring();
          await refreshDashboard().catch(() => {});
        } catch (ex) {
          alert(ex.message);
        }
      });
    });
    box.querySelectorAll("[data-rec-save-later]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = btn.dataset.recSaveLater;
        const rec = items.find((x) => String(x.next_id) === String(id));
        const nameEl = box.querySelector(`[data-rec-name="${id}"]`);
        const typicalEl = box.querySelector(`[data-rec-typical="${id}"]`);
        const dayEl = box.querySelector(`[data-rec-day="${id}"]`);
        const name = (nameEl && nameEl.value.trim()) || (rec && rec.name) || "";
        const typical = parseFloat(typicalEl && typicalEl.value);
        const dueDay = parseInt(dayEl && dayEl.value, 10);
        const base = rec && rec.next_date ? rec.next_date : isoDate();
        const parts = String(base).split("-");
        const y = parseInt(parts[0], 10);
        const m = parseInt(parts[1], 10);
        const last = new Date(y, m, 0).getDate();
        const day = Math.min(Math.max(dueDay || 1, 1), last);
        const due = `${parts[0]}-${parts[1]}-${String(day).padStart(2, "0")}`;
        try {
          await api(`/api/items/${id}?scope=future`, {
            method: "PATCH",
            json: { name, amount: typical, due_date: due },
          });
          await refreshRecurring();
          await refreshDashboard().catch(() => {});
        } catch (ex) {
          alert(ex.message);
        }
      });
    });
    box.querySelectorAll("[data-rec-stop]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!confirm("Stop this repeating bill from the next date onward? Past months stay.")) return;
        await api(`/api/items/${btn.dataset.recStop}?scope=future`, { method: "DELETE" });
        await refreshRecurring();
        await refreshDashboard().catch(() => {});
      });
    });
  }

  // ── Input ───────────────────────────────────────────────────

  async function refreshInput() {
    await loadNames();
    const q = `year=${state.year}&month=${state.month}`;
    const items = await api(`/api/items?${q}`);
    const tbody = $("#items-table tbody");
    if (!tbody) return;
    if (!items.length) {
      tbody.innerHTML = `<tr><td colspan="5" class="text-muted">No items this month yet — add one above, use Copy last month on Home, or import a statement.</td></tr>`;
      return;
    }
    tbody.innerHTML = items
      .map((it) => {
        const cls = it.is_income ? "positive" : "negative";
        const sign = it.is_income ? "+" : "−";
        const paid =
          it.item_type === "bill" && it.is_paid
            ? ` <span class="chip chip-success">paid</span>`
            : "";
        const paidBtn =
          !isViewer() && it.item_type === "bill"
            ? `<button class="btn btn-ghost btn-sm" data-toggle-paid="${it.id}" type="button">${it.is_paid ? "Unpaid" : "Paid"}</button>`
            : "";
        const actions = isViewer()
          ? "<td></td>"
          : `<td class="day-actions">
            ${paidBtn}
            <button class="btn btn-ghost btn-sm" data-edit="${it.id}" type="button">Edit</button>
            <button class="btn btn-ghost btn-sm" data-del="${it.id}" type="button">Delete</button>
          </td>`;
        return `<tr>
          <td>${it.due_date}</td>
          <td>${escapeHtml(it.name)}${paid}</td>
          <td><span class="chip chip-${typeChip(it)}">${it.item_type}</span></td>
          <td class="num ${cls}">${sign}${money(it.amount)}</td>
          ${actions}
        </tr>`;
      })
      .join("");

    tbody.querySelectorAll("[data-del]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = Number(btn.dataset.del);
        const item = items.find((x) => x.id === id);
        const scope = await confirmDeleteItem(item || { frequency: "once" });
        if (!scope) return;
        await api(`/api/items/${id}?scope=${encodeURIComponent(scope)}`, { method: "DELETE" });
        await refreshInput();
        await refreshDashboard();
      });
    });
    tbody.querySelectorAll("[data-edit]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = Number(btn.dataset.edit);
        const item = items.find((x) => x.id === id);
        if (item) openEditItemModal(item);
      });
    });
    tbody.querySelectorAll("[data-toggle-paid]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await api(`/api/items/${btn.dataset.togglePaid}/toggle-paid`, {
            method: "POST",
          });
          await refreshInput();
          await refreshDashboard();
        } catch (ex) {
          alert(ex.message || "Could not update");
        }
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

  const SUB_CHIPS = [
    "Apple (iCloud / App Store)",
    "Netflix",
    "Spotify",
    "YouTube Premium",
    "Amazon Prime",
    "Disney+",
    "Hulu",
    "iCloud+",
    "Adobe",
    "Microsoft 365",
    "Gym / membership",
  ];

  async function refreshSubs() {
    const data = await api("/api/subscriptions");
    state.subs = data;
    const sum = $("#subs-summary");
    if (sum) {
      sum.innerHTML = `
        <div class="stat"><div class="stat-label">Per month</div><div class="stat-value">${money(data.monthly_total)}</div><div class="stat-hint">${data.count} service${data.count === 1 ? "" : "s"}</div></div>
        <div class="stat"><div class="stat-label">Per year</div><div class="stat-value" style="color:var(--brand-light)">${money(data.yearly_total)}</div><div class="stat-hint">If they keep billing</div></div>`;
    }
    const chips = $("#subs-chips");
    if (chips && !chips.dataset.ready) {
      chips.innerHTML = SUB_CHIPS.map(
        (n) => `<button type="button" class="btn btn-ghost btn-sm" data-sub-chip="${escapeAttr(n)}">${escapeHtml(n)}</button>`
      ).join("");
      chips.dataset.ready = "1";
      chips.querySelectorAll("[data-sub-chip]").forEach((btn) => {
        btn.addEventListener("click", () => {
          if ($("#sub-name")) $("#sub-name").value = btn.dataset.subChip;
        });
      });
    }
    const list = $("#subs-list");
    if (!list) return;
    if (!data.items.length) {
      list.innerHTML = `<div class="empty"><h3>No subscriptions spotted yet</h3><p>Add Apple, Netflix, or a gym. Importing a statement also picks up Apple.com/bill and similar charges.</p></div>`;
      return;
    }
    const viewer = isViewer();
    list.innerHTML = `
      <div class="table-wrap subs-table-wrap">
        <table class="data">
          <thead>
            <tr>
              <th>Service</th>
              <th>Repeats</th>
              <th>Next</th>
              <th class="num">Each time</th>
              <th class="num">/mo</th>
              <th class="num">/year</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            ${data.items
              .map((s) => {
                const freqLabel =
                  s.display_frequency === "yearly"
                    ? "Yearly"
                    : s.display_frequency === "weekly"
                      ? "Weekly"
                      : s.display_frequency === "monthly"
                        ? "Monthly"
                        : "Once";
                const guess = s.guessed
                  ? `<div class="subs-guess">Seen on statements — not a repeating bill yet</div>`
                  : "";
                let actions = "";
                if (!viewer) {
                  if (s.guessed) {
                    actions += `<button class="btn btn-outline btn-sm" type="button" data-sub-repeat="${s.item_id}" data-name="${escapeAttr(s.name)}" data-amt="${s.amount}">Repeat monthly</button> `;
                  }
                  actions += `<button class="btn btn-ghost btn-sm" type="button" data-sub-hide="${escapeAttr(s.name)}">Not a sub</button>`;
                }
                return `<tr>
                  <td>${escapeHtml(s.name)}${guess}</td>
                  <td>${freqLabel}${s.repeating ? "" : ""}</td>
                  <td>${s.next_date || "—"}</td>
                  <td class="num">${money(s.amount)}</td>
                  <td class="num">${money(s.monthly)}</td>
                  <td class="num">${money(s.yearly)}</td>
                  <td class="day-actions">${actions}</td>
                </tr>`;
              })
              .join("")}
          </tbody>
        </table>
      </div>`;
    list.querySelectorAll("[data-sub-hide]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await api(
          `/api/subscriptions/ignore?name=${encodeURIComponent(btn.dataset.subHide)}`,
          { method: "POST" }
        );
        await refreshSubs();
        await refreshDashboard().catch(() => {});
      });
    });
    list.querySelectorAll("[data-sub-repeat]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const due = isoDate();
        try {
          const res = await api("/api/subscriptions", {
            method: "POST",
            json: {
              name: btn.dataset.name,
              amount: parseFloat(btn.dataset.amt),
              due_date: due,
              frequency: "monthly",
            },
          });
          alert(res.message || "Added as a monthly bill.");
          await refreshSubs();
          await refreshDashboard();
        } catch (ex) {
          alert(ex.message || "Could not add");
        }
      });
    });
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
        const months = g.months_to_target;
        const splitAmt = g.suggested_monthly;
        const planAmt = g.monthly_contribution || splitAmt || 0;
        const suggest = splitAmt
          ? `<div>To hit <strong>${g.target_date}</strong>: about <strong>${money(splitAmt)}</strong>/mo for <strong>${months}</strong> month${months === 1 ? "" : "s"}</div>`
          : g.target_date
            ? ""
            : `<div class="text-muted">Add a target date to split the rest into monthly savings</div>`;
        const eta = g.eta_date
          ? `<div>If you keep ${money(g.monthly_contribution || 0)}/mo: <strong>${g.eta_date}</strong></div>`
          : "";
        const thisMo = g.saved_this_month || 0;
        const logDefault = planAmt || 50;
        const hist = (g.saves || []).slice(0, 8);
        const histHtml = hist.length
          ? `<table class="data" style="margin-top:0.65rem"><thead><tr><th>Month</th><th class="num">Saved</th></tr></thead><tbody>${hist
              .map(
                (s) =>
                  `<tr><td>${String(s.saved_on).slice(0, 7)}</td><td class="num">${money(s.amount)}</td></tr>`
              )
              .join("")}</tbody></table>`
          : `<p class="form-hint" style="margin-top:0.5rem">No monthly log yet — record what you actually put away.</p>`;
        return `
        <div class="goal-card">
          ${badge}
          <h3>${escapeHtml(g.name)}</h3>
          <div class="progress"><div class="progress-bar ${barCls}" style="width:${Math.min(g.percent, 100)}%"></div></div>
          <div class="goal-meta">
            <div><strong>${money(g.current_amount)}</strong> of ${money(g.target_amount)} · ${g.percent}%</div>
            <div>Still need <strong>${money(g.remaining)}</strong></div>
            ${suggest}
            ${g.monthly_contribution ? `<div>Your plan: <strong>${money(g.monthly_contribution)}</strong>/mo</div>` : ""}
            ${eta}
            <div>This month logged: <strong>${money(thisMo)}</strong>${planAmt ? ` of ${money(planAmt)} planned` : ""}</div>
            ${g.notes ? `<div class="text-muted">${escapeHtml(g.notes)}</div>` : ""}
          </div>
          ${
            isViewer()
              ? histHtml
              : `<div class="goal-actions" style="flex-wrap:wrap;align-items:center">
            <input class="input-money" data-goal-log-amt="${g.id}" type="number" min="0.01" step="0.01" value="${logDefault}" style="width:7rem" title="Amount you saved this month" />
            <button class="btn btn-primary btn-sm" type="button" data-goal-log="${g.id}">I saved this month</button>
            ${
              splitAmt
                ? `<button class="btn btn-outline btn-sm" type="button" data-goal-split="${g.id}" data-amt="${splitAmt}">Use ${money(splitAmt)}/mo split</button>`
                : ""
            }
            <button class="btn btn-outline btn-sm" type="button" data-goal-cal="${g.id}">Put this month on calendar</button>
            <button class="btn btn-ghost btn-sm" type="button" data-goal-del="${g.id}">Delete</button>
          </div>
          ${histHtml}`
          }
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
    box.querySelectorAll("[data-goal-log]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = btn.dataset.goalLog;
        const inp = box.querySelector(`[data-goal-log-amt="${id}"]`);
        const add = parseFloat(inp && inp.value);
        if (!add || add <= 0) {
          alert("Enter how much you saved this month.");
          return;
        }
        try {
          await api(`/api/goals/${id}/saves`, {
            method: "POST",
            json: { amount: add },
          });
          await refreshGoals();
          await refreshDashboard().catch(() => {});
        } catch (ex) {
          alert(ex.message);
        }
      });
    });
    box.querySelectorAll("[data-goal-split]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const amt = parseFloat(btn.dataset.amt);
        if (!amt || amt <= 0) return;
        await api(`/api/goals/${btn.dataset.goalSplit}`, {
          method: "PATCH",
          json: { monthly_contribution: amt },
        });
        await refreshGoals();
      });
    });
    box.querySelectorAll("[data-goal-cal]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          const data = await api(
            `/api/goals/${btn.dataset.goalCal}/to-calendar?year=${state.year}&month=${state.month}`,
            { method: "POST" }
          );
          alert(data.message || "Added to the calendar.");
          await refreshDashboard();
          await refreshGoals();
        } catch (ex) {
          alert(ex.message || "Could not add to calendar");
        }
      });
    });
  }

  function round2(n) {
    return Math.round(Number(n) * 100) / 100;
  }

  async function refreshCards() {
    const data = await api("/api/cards");
    const sum = $("#cards-summary");
    if (sum) {
      sum.innerHTML = `
        <div class="stat"><div class="stat-label">Card balances</div><div class="stat-value negative">${money(data.total_balance || 0)}</div><div class="stat-hint">${(data.cards || []).length} card${(data.cards || []).length === 1 ? "" : "s"}</div></div>
        <div class="stat"><div class="stat-label">Min payments / mo</div><div class="stat-value">${money(data.total_min || 0)}</div><div class="stat-hint">Feeds Debt plan</div></div>`;
    }
    const list = $("#cards-list");
    if (list) {
      if (!(data.cards || []).length) {
        list.innerHTML = `<div class="empty"><h3>No cards yet</h3><p>Upload a credit-card PDF to pull balance, APR, and minimum payment. Checking PDFs still go under Import.</p></div>`;
      } else {
        list.innerHTML = data.cards
          .map((c) => {
            const due = c.due_date ? `Due ${c.due_date}` : "No due date yet";
            const stmt = c.statement_date ? `Statement ${c.statement_date}` : "";
            const last4 = c.last4 ? `…${escapeHtml(c.last4)}` : "";
            const actions = isViewer()
              ? ""
              : `<div class="goal-actions">
                  <button class="btn btn-outline btn-sm" type="button" data-card-edit="${c.id}">Edit</button>
                  <button class="btn btn-outline btn-sm" type="button" data-card-min="${c.id}">Put pay on calendar</button>
                  <button class="btn btn-ghost btn-sm" type="button" data-go-debts="1">Open Debt plan</button>
                </div>`;
            const dueVal = c.due_date || "";
            return `<div class="goal-card">
              <h3>${escapeHtml(c.name)} ${last4}</h3>
              <div class="goal-meta">
                <div>Balance <strong class="negative">${money(c.balance)}</strong> · APR <strong>${Number(c.apr || 0).toFixed(2)}%</strong></div>
                <div>I pay <strong>${money(c.min_payment)}</strong> / mo · ${due}</div>
                <div class="text-muted">${stmt}${c.last_interest ? ` · interest charged ${money(c.last_interest)}` : ""} · ${c.txn_count || 0} charges stored</div>
              </div>
              ${actions}
              <form class="card-edit-form" data-card-form="${c.id}" hidden style="margin-top:0.85rem">
                <div class="form-row">
                  <div class="form-group">
                    <label>Name</label>
                    <input name="name" type="text" required maxlength="120" value="${escapeAttr(c.name)}" />
                  </div>
                  <div class="form-group">
                    <label>Last 4</label>
                    <input name="last4" type="text" maxlength="4" value="${escapeAttr(c.last4 || "")}" />
                  </div>
                </div>
                <div class="form-row">
                  <div class="form-group">
                    <label>Balance ($)</label>
                    <input name="balance" class="input-money" type="number" min="0" step="0.01" value="${c.balance}" />
                  </div>
                  <div class="form-group">
                    <label>APR (%)</label>
                    <input name="apr" class="input-money" type="number" min="0" max="80" step="0.01" value="${c.apr || 0}" />
                  </div>
                </div>
                <div class="form-row">
                  <div class="form-group">
                    <label>What I pay / mo ($)</label>
                    <input name="min_payment" class="input-money" type="number" min="0" step="0.01" value="${c.min_payment || 0}" />
                  </div>
                  <div class="form-group">
                    <label>Due date</label>
                    <input name="due_date" type="date" value="${dueVal}" />
                  </div>
                </div>
                <button class="btn btn-primary btn-sm" type="submit">Save card</button>
                <button class="btn btn-ghost btn-sm" type="button" data-card-edit-cancel="${c.id}">Cancel</button>
                <button class="btn btn-danger btn-sm" type="button" data-card-del="${c.id}">Delete card</button>
                <span class="form-hint" data-card-edit-msg></span>
              </form>
            </div>`;
          })
          .join("");
        list.querySelectorAll("[data-card-min]").forEach((btn) => {
          btn.addEventListener("click", async () => {
            try {
              const res = await api(`/api/cards/${btn.dataset.cardMin}/min-to-calendar`, {
                method: "POST",
              });
              alert(res.message || "Added to calendar.");
              await refreshDashboard().catch(() => {});
            } catch (ex) {
              alert(ex.message);
            }
          });
        });
        list.querySelectorAll("[data-go-debts]").forEach((btn) => {
          btn.addEventListener("click", () => setView("debts"));
        });
        list.querySelectorAll("[data-card-edit]").forEach((btn) => {
          btn.addEventListener("click", () => {
            const form = list.querySelector(`[data-card-form="${btn.dataset.cardEdit}"]`);
            if (form) form.hidden = !form.hidden;
          });
        });
        list.querySelectorAll("[data-card-edit-cancel]").forEach((btn) => {
          btn.addEventListener("click", () => {
            const form = list.querySelector(`[data-card-form="${btn.dataset.cardEditCancel}"]`);
            if (form) form.hidden = true;
          });
        });
        list.querySelectorAll("[data-card-form]").forEach((form) => {
          form.addEventListener("submit", async (e) => {
            e.preventDefault();
            const id = form.dataset.cardForm;
            const msg = form.querySelector("[data-card-edit-msg]");
            const fd = new FormData(form);
            const due = (fd.get("due_date") || "").toString().trim();
            try {
              await api(`/api/debts/${id}`, {
                method: "PATCH",
                json: {
                  name: String(fd.get("name") || "").trim(),
                  last4: String(fd.get("last4") || "").trim(),
                  balance: parseFloat(fd.get("balance")) || 0,
                  apr: parseFloat(fd.get("apr")) || 0,
                  min_payment: parseFloat(fd.get("min_payment")) || 0,
                  due_date: due || null,
                },
              });
              if (msg) msg.textContent = "Saved. Debt plan and calendar min bill updated.";
              await refreshCards();
              await refreshDebts().catch(() => {});
              await refreshDashboard().catch(() => {});
            } catch (ex) {
              if (msg) msg.textContent = ex.message;
            }
          });
        });
        list.querySelectorAll("[data-card-del]").forEach((btn) => {
          btn.addEventListener("click", async () => {
            if (!confirm("Delete this card from the tracker? Calendar bills are not auto-deleted.")) return;
            await api(`/api/debts/${btn.dataset.cardDel}`, { method: "DELETE" });
            await refreshCards();
            await refreshDebts().catch(() => {});
          });
        });
      }
    }
    const recBox = $("#cards-recurring");
    if (recBox) {
      state.cardRecurring = data.recurring || [];
      renderCardRecurring();
    }
  }

  function renderCardRecurring() {
    const recBox = $("#cards-recurring");
    if (!recBox) return;
    const rec = state.cardRecurring || [];
    if (!rec.length) {
      recBox.innerHTML = `<div class="empty"><h3>No repeating card charges spotted yet</h3><p>After a couple of statements, Apple, Netflix, and similar names show up here.</p></div>`;
      return;
    }
    const q = (state.cardRecurringQ || "").trim().toLowerCase();
    const kind = state.cardRecurringKind || "active";
    const filtered = rec.filter((r) => {
      if (kind === "active" && r.hidden) return false;
      if (kind === "hidden" && !r.hidden) return false;
      if (kind === "subs" && !r.looks_like_subscription) return false;
      if (kind === "months" && !(r.months >= 2)) return false;
      if (kind === "calendar" && !r.on_calendar) return false;
      if (q) {
        const blob = `${r.merchant} ${r.card_name || ""} ${r.last_description || ""}`.toLowerCase();
        if (!blob.includes(q)) return false;
      }
      return true;
    });
    recBox.innerHTML = `<h2>Possible recurring charges</h2>
      <p class="lead">From card statements. Hide grocery noise. Put real subscriptions on the calendar.</p>
      <div class="form-row" style="margin-bottom:0.75rem;max-width:720px">
        <div class="form-group">
          <label for="card-rec-q">Filter</label>
          <input id="card-rec-q" type="search" placeholder="Amazon, Apple…" value="${escapeAttr(state.cardRecurringQ || "")}" />
        </div>
        <div class="form-group">
          <label for="card-rec-kind">Show</label>
          <select id="card-rec-kind">
            <option value="active" ${kind === "active" ? "selected" : ""}>Active (not hidden)</option>
            <option value="subs" ${kind === "subs" ? "selected" : ""}>Looks like a subscription</option>
            <option value="months" ${kind === "months" ? "selected" : ""}>Seen in 2+ months</option>
            <option value="calendar" ${kind === "calendar" ? "selected" : ""}>On the calendar</option>
            <option value="hidden" ${kind === "hidden" ? "selected" : ""}>Hidden / not a charge</option>
            <option value="all" ${kind === "all" ? "selected" : ""}>All</option>
          </select>
        </div>
      </div>
      <div class="table-wrap"><table class="data"><thead><tr>
        <th>Merchant</th><th>Card</th><th>Times</th><th class="num">Typical</th><th>Last seen</th><th></th>
      </tr></thead><tbody>
      ${
        filtered.length
          ? filtered
              .map((r) => {
                const tag = r.looks_like_subscription
                  ? `<span class="chip chip-warning">Looks like a sub</span>`
                  : "";
                const onCal = r.on_calendar
                  ? `<span class="chip chip-success">On calendar</span>`
                  : "";
                const hidden = r.hidden ? `<span class="text-muted">Hidden</span>` : "";
                let actions = "";
                if (!isViewer()) {
                  if (!r.on_calendar && !r.hidden) {
                    actions += `<button class="btn btn-outline btn-sm" type="button" data-rec-cal="${escapeAttr(r.merchant)}" data-amt="${r.typical_amount}">Put on calendar</button> `;
                  }
                  if (r.on_calendar) {
                    actions += `<button class="btn btn-ghost btn-sm" type="button" data-rec-uncal="${escapeAttr(r.merchant)}">Remove from calendar</button> `;
                  }
                  if (r.hidden) {
                    actions += `<button class="btn btn-ghost btn-sm" type="button" data-rec-watch="${escapeAttr(r.key || r.merchant)}">Show again</button>`;
                  } else {
                    actions += `<button class="btn btn-ghost btn-sm" type="button" data-rec-hide="${escapeAttr(r.key || r.merchant)}">Not a charge</button>`;
                  }
                }
                return `<tr>
                <td>${escapeHtml(r.merchant)} ${tag} ${onCal} ${hidden}</td>
                <td>${escapeHtml(r.card_name || "")}</td>
                <td>${r.count} / ${r.months} mo</td>
                <td class="num">${money(r.typical_amount)}</td>
                <td>${r.last_date || "—"}</td>
                <td class="day-actions">${actions}</td>
              </tr>`;
              })
              .join("")
          : `<tr><td colspan="6" class="text-muted">Nothing matches this filter.</td></tr>`
      }
      </tbody></table></div>`;
    const qEl = $("#card-rec-q");
    const kEl = $("#card-rec-kind");
    if (qEl) {
      qEl.addEventListener("input", () => {
        state.cardRecurringQ = qEl.value;
        renderCardRecurring();
        const again = $("#card-rec-q");
        if (again) {
          again.focus();
          const v = again.value;
          again.setSelectionRange(v.length, v.length);
        }
      });
    }
    if (kEl) {
      kEl.addEventListener("change", () => {
        state.cardRecurringKind = kEl.value;
        renderCardRecurring();
      });
    }
    recBox.querySelectorAll("[data-rec-cal]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          const res = await api(
            `/api/cards/recurring/to-calendar?merchant=${encodeURIComponent(btn.dataset.recCal)}&amount=${encodeURIComponent(btn.dataset.amt)}&year=${state.year}&month=${state.month}`,
            { method: "POST" }
          );
          alert(res.message || "Added.");
          await refreshCards();
          await refreshDashboard().catch(() => {});
          await refreshSubs().catch(() => {});
        } catch (ex) {
          alert(ex.message);
        }
      });
    });
    recBox.querySelectorAll("[data-rec-uncal]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await api(
          `/api/cards/recurring/remove-calendar?merchant=${encodeURIComponent(btn.dataset.recUncal)}`,
          { method: "POST" }
        );
        await refreshCards();
        await refreshDashboard().catch(() => {});
      });
    });
    recBox.querySelectorAll("[data-rec-hide]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await api(
          `/api/cards/recurring/mark?key=${encodeURIComponent(btn.dataset.recHide)}&status=ignore`,
          { method: "POST" }
        );
        await refreshCards();
      });
    });
    recBox.querySelectorAll("[data-rec-watch]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await api(
          `/api/cards/recurring/mark?key=${encodeURIComponent(btn.dataset.recWatch)}&status=watch`,
          { method: "POST" }
        );
        await refreshCards();
      });
    });
  }

  function renderCardPreview(data) {
    state.cardPreview = data;
    const box = $("#card-preview-box");
    const stats = $("#card-preview-stats");
    const tbody = $("#card-preview-txns tbody");
    if (!box) return;
    box.style.display = "block";
    const s = data.summary || {};
    const match = data.matched_debt_name
      ? `Will update <strong>${escapeHtml(data.matched_debt_name)}</strong>. Edit APR and auto-pay below before you save.`
      : "Will create a new card in Debt plan. Edit APR and auto-pay below if the PDF left them blank.";
    const matchEl = $("#card-preview-match");
    if (matchEl) matchEl.innerHTML = match;
    if (stats) {
      stats.innerHTML = `
        <div class="stat"><div class="stat-label">From PDF</div><div class="stat-value">${escapeHtml(s.card_name || "Card")}${s.last4 ? " …" + escapeHtml(s.last4) : ""}</div><div class="stat-hint">${(data.transactions || []).length} charge${(data.transactions || []).length === 1 ? "" : "s"}</div></div>
        <div class="stat"><div class="stat-label">Statement min</div><div class="stat-value">${s.min_payment != null ? money(s.min_payment) : "—"}</div><div class="stat-hint">${s.due_date ? "Due " + s.due_date : "Edit due date below"}</div></div>
        <div class="stat"><div class="stat-label">PDF APR</div><div class="stat-value">${s.apr != null ? Number(s.apr).toFixed(2) + "%" : "Not found"}</div><div class="stat-hint">${s.apr != null ? "You can still change it" : "Type it from the statement"}</div></div>
        <div class="stat"><div class="stat-label">Interest charged</div><div class="stat-value">${s.interest_charged != null ? money(s.interest_charged) : "—"}</div><div class="stat-hint">This statement</div></div>`;
    }
    const stmtMin = s.min_payment != null ? Number(s.min_payment) : Number(data.matched_min_payment) || 0;
    const aprVal =
      s.apr != null && Number(s.apr) > 0
        ? Number(s.apr)
        : Number(data.matched_apr) > 0
          ? Number(data.matched_apr)
          : "";
    const payDefault =
      Number(data.matched_min_payment) > stmtMin
        ? Number(data.matched_min_payment)
        : stmtMin;
    if ($("#card-edit-balance")) {
      $("#card-edit-balance").value =
        s.new_balance != null && s.new_balance !== "" ? Number(s.new_balance) : "";
    }
    if ($("#card-edit-apr")) $("#card-edit-apr").value = aprVal;
    if ($("#card-edit-stmt-min")) $("#card-edit-stmt-min").value = stmtMin || "";
    if ($("#card-edit-pay")) $("#card-edit-pay").value = payDefault || "";
    if ($("#card-edit-due")) $("#card-edit-due").value = s.due_date || "";
    const minHint = $("#card-stmt-min-hint");
    if (minHint) {
      minHint.textContent = stmtMin
        ? `PDF minimum ${money(stmtMin)} — auto-pay can be higher`
        : "Type the statement minimum if it was blank";
    }
    if (tbody) {
      const rows = data.transactions || [];
      tbody.innerHTML = rows.length
        ? rows
            .map(
              (t) => `<tr>
                <td>${t.date || "—"}</td>
                <td>${escapeHtml(t.description)}</td>
                <td class="num ${t.is_credit ? "positive" : "negative"}">${t.is_credit ? "+" : "−"}${money(t.amount)}</td>
                <td>${t.is_credit ? "Payment / credit" : escapeHtml(t.category || "")}</td>
              </tr>`
            )
            .join("")
        : `<tr><td colspan="4" class="text-muted">No individual charges parsed — totals above can still be saved.</td></tr>`;
    }
  }

  // ── Debts ───────────────────────────────────────────────────

  let spendCatChart = null;
  let spendCardChart = null;

  async function refreshSpend() {
    const data = await api("/api/cards/spend");
    const sum = $("#spend-summary");
    if (sum) {
      sum.innerHTML = `
        <div class="stat"><div class="stat-label">Card spend</div><div class="stat-value negative">${money(data.total || 0)}</div><div class="stat-hint">${data.count || 0} charges · payments left out</div></div>
        <div class="stat"><div class="stat-label">Dining / coffee</div><div class="stat-value">${money(data.dining_total || 0)}</div><div class="stat-hint">${data.dining_count || 0} charges across all cards</div></div>
        <div class="stat"><div class="stat-label">Cards in mix</div><div class="stat-value">${(data.by_card || []).length}</div><div class="stat-hint">From uploaded statements</div></div>`;
    }
    const catBody = $("#spend-cat-table tbody");
    if (catBody) {
      const rows = data.by_category || [];
      catBody.innerHTML = rows.length
        ? rows
            .map(
              (c) => `<tr>
                <td>${escapeHtml(c.category)}</td>
                <td class="num">${c.count}</td>
                <td class="num">${money(c.amount)}</td>
                <td class="num">${c.pct}%</td>
              </tr>`
            )
            .join("")
        : `<tr><td colspan="4" class="text-muted">Upload card PDFs under Cards first.</td></tr>`;
    }
    const cardBody = $("#spend-card-table tbody");
    if (cardBody) {
      const rows = data.by_card || [];
      cardBody.innerHTML = rows.length
        ? rows
            .map(
              (c) => `<tr>
                <td>${escapeHtml(c.name)}${c.last4 ? ` …${escapeHtml(c.last4)}` : ""}</td>
                <td class="num">${c.count}</td>
                <td class="num">${money(c.amount)}</td>
                <td class="num">${c.pct}%</td>
              </tr>`
            )
            .join("")
        : `<tr><td colspan="4" class="text-muted">No card charges yet.</td></tr>`;
    }
    const merchBody = $("#spend-merch-table tbody");
    if (merchBody) {
      const rows = data.merchants || [];
      merchBody.innerHTML = rows.length
        ? rows
            .map(
              (m) => `<tr>
                <td>${escapeHtml(m.merchant)}</td>
                <td>${escapeHtml(m.category)}</td>
                <td>${escapeHtml((m.cards || []).join(", "))}</td>
                <td class="num">${m.count}</td>
                <td class="num">${money(m.amount)}</td>
              </tr>`
            )
            .join("")
        : `<tr><td colspan="5" class="text-muted">No merchants yet.</td></tr>`;
    }
    if (typeof Chart !== "undefined") {
      const catLabels = (data.by_category || []).map((c) => c.category);
      const catVals = (data.by_category || []).map((c) => c.amount);
      const cardLabels = (data.by_card || []).map((c) => c.name);
      const cardVals = (data.by_card || []).map((c) => c.amount);
      const palette = ["#58a6ff", "#3fb950", "#d29922", "#a371f7", "#f85149", "#79c0ff", "#ea60d8", "#8b949e"];
      const catEl = document.getElementById("chart-spend-cat");
      const cardEl = document.getElementById("chart-spend-card");
      if (spendCatChart) spendCatChart.destroy();
      if (spendCardChart) spendCardChart.destroy();
      if (catEl && catLabels.length) {
        spendCatChart = new Chart(catEl, {
          type: "doughnut",
          data: {
            labels: catLabels,
            datasets: [{ data: catVals, backgroundColor: catLabels.map((_, i) => palette[i % palette.length]) }],
          },
          options: { plugins: { legend: { position: "bottom", labels: { color: "#8b949e", boxWidth: 12 } } } },
        });
      }
      if (cardEl && cardLabels.length) {
        spendCardChart = new Chart(cardEl, {
          type: "doughnut",
          data: {
            labels: cardLabels,
            datasets: [{ data: cardVals, backgroundColor: cardLabels.map((_, i) => palette[i % palette.length]) }],
          },
          options: { plugins: { legend: { position: "bottom", labels: { color: "#8b949e", boxWidth: 12 } } } },
        });
      }
    }
  }

  async function refreshDebts() {
    const [debts, hh] = await Promise.all([
      api("/api/debts"),
      api("/api/household").catch(() => state.household),
    ]);
    if (hh) state.household = hh;
    const hint = $("#debt-profile-hint");
    if (hint) {
      const age = hh && hh.primary_age;
      const st = hh && (hh.state || "").trim();
      if (!age || !st) {
        hint.style.display = "block";
        hint.innerHTML =
          `Add <strong>age</strong> and <strong>US state</strong> under Household. ` +
          `Debt payoff and later benefits tips work better with that context ` +
          `(stays on this PC — not tax advice). ` +
          `<button type="button" class="btn btn-outline btn-sm" id="debt-go-profile" style="margin-left:0.5rem">Open Household</button>`;
        const go = $("#debt-go-profile");
        if (go) go.addEventListener("click", () => setView("settings"));
      } else {
        hint.style.display = "none";
        hint.innerHTML = "";
      }
    }
    const tbody = $("#debts-table tbody");
    if (!debts.length) {
      tbody.innerHTML = `<tr><td colspan="5" class="text-muted">No debts listed — add cards or loans above to build a plan.</td></tr>`;
    } else {
      tbody.innerHTML = debts
        .map(
          (d) => `<tr>
          <td>${escapeHtml(d.name)}${d.last4 ? ` <span class="text-muted">…${escapeHtml(d.last4)}</span>` : ""}</td>
          <td class="num">${money(d.balance)}</td>
          <td class="num">${Number(d.apr).toFixed(2)}%</td>
          <td class="num">${money(d.min_payment)}</td>
          <td>${isViewer() ? "" : `<button class="btn btn-ghost btn-sm" type="button" data-debt-del="${d.id}">Delete</button>`}</td>
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
    await renderDebtPresets();
  }

  async function renderDebtPresets() {
    const el = $("#debt-presets");
    if (!el) return;
    let data;
    try {
      data = await api("/api/debts/plans");
    } catch (_) {
      el.innerHTML = "";
      return;
    }
    const plans = data.plans || [];
    if (!plans.length) {
      el.innerHTML = "";
      return;
    }
    el.innerHTML = `<h2 style="margin:0 0 0.65rem">Ready-made plans</h2>
      <p class="lead">Same cards, different extra amounts. Extra is on top of all minimums. Pick what fits now; you can switch when pay is steadier. Tap a plan for the month-by-month.</p>
      <div class="plan-presets">
        ${plans
          .map((p) => {
            const order = (p.payoff_order || []).map(escapeHtml).join(" → ") || "—";
            return `<button type="button" class="plan-preset" data-plan-id="${escapeAttr(p.id)}" data-strategy="${escapeAttr(p.strategy)}" data-extra="${p.extra_monthly}">
              <div class="section-label">${escapeHtml(p.title)}</div>
              <div class="plan-preset-free">${escapeHtml(p.debt_free_label)}</div>
              <div class="text-secondary" style="font-size:0.82rem;margin-top:0.35rem">${p.months} mo · interest ${money(p.total_interest)}</div>
              <p class="form-hint" style="margin:0.45rem 0 0">${escapeHtml(p.blurb)}</p>
              <div class="text-muted" style="font-size:0.75rem;margin-top:0.4rem">First: ${order}</div>
            </button>`;
          })
          .join("")}
      </div>`;
    el.querySelectorAll("[data-plan-id]").forEach((btn) => {
      btn.addEventListener("click", () => {
        if ($("#plan-strategy")) $("#plan-strategy").value = btn.dataset.strategy;
        if ($("#plan-extra")) $("#plan-extra").value = btn.dataset.extra;
        runDebtPlan();
      });
    });
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
      const notes = (plan.planning_notes || [])
        .map((n) => `<li>${escapeHtml(n)}</li>`)
        .join("");
      const notesBlock = notes
        ? `<div class="card" style="margin-bottom:1rem;padding:1rem">
            <h3 class="card-title" style="margin:0 0 0.5rem">Age &amp; state context</h3>
            <ul class="planning-notes" style="margin:0;padding-left:1.15rem;color:var(--text-secondary);font-size:0.88rem;line-height:1.45">${notes}</ul>
          </div>`
        : "";
      box.innerHTML = `
        <div class="alert alert-brand" style="margin-bottom:1rem">${escapeHtml(plan.strategy_blurb)}</div>
        ${notesBlock}
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
            ${
              isViewer()
                ? ""
                : `<button class="btn btn-outline btn-sm" type="button" data-inv-upd="${r.id}" data-val="${r.current_value}">Update $</button>
            <button class="btn btn-ghost btn-sm" type="button" data-inv-del="${r.id}">Delete</button>`
            }
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
    state.household = hh;
    $("#hh-name").value = hh.name;
    $("#hh-balance").value = hh.starting_balance;
    if ($("#hh-threshold")) {
      $("#hh-threshold").value =
        hh.safety_threshold != null ? hh.safety_threshold : 0;
    }
    if ($("#hh-primary-age")) {
      $("#hh-primary-age").value =
        hh.primary_age != null && hh.primary_age > 0 ? hh.primary_age : "";
    }
    if ($("#hh-partner-age")) {
      $("#hh-partner-age").value =
        hh.partner_age != null && hh.partner_age > 0 ? hh.partner_age : "";
    }
    if ($("#hh-state")) {
      $("#hh-state").value = (hh.state || "").toUpperCase();
    }
    if ($("#hh-idle")) {
      const idle = String(hh.idle_minutes || DEFAULT_IDLE_MIN);
      $("#hh-idle").value = ["10", "20", "30", "60", "120"].includes(idle) ? idle : "30";
    }
    const rescueStatus = $("#rescue-status");
    if (rescueStatus) {
      rescueStatus.textContent = hh.has_recovery_key
        ? "A rescue code is already set. If you lost the paper, make a new one (the old one stops working)."
        : "You do not have a rescue code yet. Make one now and write it down.";
    }
    await refreshBackupStatus();
    const list = $("#members-list");
    const meName = (state.user && (state.user.username || "")).toLowerCase();
    await refreshUpdatePanel();
    if (list) {
      list.innerHTML = members
        .map((m) => {
          const isMe = (m.username || "").toLowerCase() === meName;
          const delBtn = isMe
            ? `<span class="text-muted" style="font-size:0.75rem">you</span>`
            : isViewer()
              ? ""
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

  async function refreshBackupStatus() {
    const el = $("#backup-local-status");
    if (!el) return;
    try {
      const st = await api("/api/backup/status");
      if (st.last_backup) {
        el.textContent = st.backup_this_month
          ? `A copy was saved this month (${st.last_backup}). Folder: data/backups.`
          : `Last copy: ${st.last_backup}. Save a new one this month.`;
      } else {
        el.textContent = "No copy saved yet on this computer.";
      }
    } catch (_) {
      el.textContent = "";
    }
  }

  function setUpdateBusy(busy) {
    const checkBtn = $("#btn-update-check");
    const applyBtn = $("#btn-update-apply");
    if (checkBtn) checkBtn.disabled = busy;
    if (applyBtn && busy) applyBtn.disabled = true;
  }

  async function refreshUpdatePanel() {
    const currentEl = $("#update-current");
    const msgEl = $("#update-msg");
    const applyBtn = $("#btn-update-apply");
    if (!currentEl || !msgEl) return;
    try {
      const st = await api("/api/update/status");
      currentEl.innerHTML = `This computer has version <strong class="text-primary">${escapeHtml(st.current || "unknown")}</strong>.`;
      msgEl.textContent = st.message || "";
      msgEl.classList.remove("is-error", "is-ready", "is-ok");
      if (!st.check_ok) msgEl.classList.add("is-error");
      else if (st.update_available) msgEl.classList.add("is-ready");
      else msgEl.classList.add("is-ok");
      if (applyBtn) {
        applyBtn.disabled = !st.update_available || !st.can_update;
        if (!st.can_update) {
          applyBtn.title = "Ask the person who set up this app to tap Update now.";
        } else {
          applyBtn.title = st.update_available
            ? "Install the newer version. Your budget stays here."
            : "No newer version right now.";
        }
      }
    } catch (ex) {
      currentEl.textContent = "Could not read the version on this computer.";
      msgEl.textContent = ex.message || "Try Check for a newer version.";
      msgEl.classList.add("is-error");
      if (applyBtn) applyBtn.disabled = true;
    }
  }

  async function waitForAppBack(timeoutMs = 90000) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      await new Promise((r) => setTimeout(r, 1500));
      try {
        const res = await fetch("/api/version", { cache: "no-store" });
        if (res.ok) return true;
      } catch (_) {}
    }
    return false;
  }

  async function runAppUpdate() {
    const msgEl = $("#update-msg");
    const applyBtn = $("#btn-update-apply");
    if (
      !confirm(
        "Update Household Money on this computer?\n\nYour bills, passwords, and budget stay here.\nThe page will pause for about a minute, then come back."
      )
    ) {
      return;
    }
    setUpdateBusy(true);
    if (msgEl) {
      msgEl.classList.remove("is-error", "is-ready", "is-ok");
      msgEl.textContent = "Downloading the update. Please leave this page open…";
    }
    try {
      const result = await api("/api/update/apply", { method: "POST" });
      if (msgEl) msgEl.textContent = result.message || "Update installed. Waiting for the app to come back…";
      if (result.restarting) {
        const back = await waitForAppBack();
        if (back) {
          window.location.reload();
          return;
        }
        if (msgEl) {
          msgEl.classList.add("is-error");
          msgEl.textContent =
            "The update finished, but this page did not come back by itself. Close this tab, open the app the same way you usually do, then sign in again.";
        }
      } else {
        await refreshUpdatePanel();
      }
    } catch (ex) {
      if (msgEl) {
        msgEl.classList.add("is-error");
        msgEl.textContent = ex.message || "The update did not finish. Nothing was erased. Try again.";
      }
    } finally {
      setUpdateBusy(false);
      if (applyBtn && msgEl && msgEl.classList.contains("is-error")) {
        applyBtn.disabled = false;
      }
    }
  }

  // ── Import ──────────────────────────────────────────────────

  const DEFAULT_IMPORT_CATS = [
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
  ];

  function importCategoryOptions(selected) {
    const cats = state.importCategories.length
      ? state.importCategories
      : DEFAULT_IMPORT_CATS;
    return cats
      .map(
        (c) =>
          `<option value="${escapeAttr(c)}" ${c === selected ? "selected" : ""}>${escapeHtml(c)}</option>`
      )
      .join("");
  }

  function updateImportSelectedCount() {
    const el = $("#import-selected-count");
    if (!el) return;
    const n = state.importRows.filter((r) => r.selected && r.date && r.amount > 0).length;
    const total = state.importRows.length;
    const dups = state.importRows.filter((r) => r.possible_duplicate).length;
    if (!total) {
      el.textContent = "";
      return;
    }
    el.textContent = dups
      ? `${n} of ${total} selected · ${dups} possible duplicate(s)`
      : `${n} of ${total} selected`;
  }

  function isCreditCardRow(r) {
    const cat = (r.category || "").toLowerCase();
    if (cat.includes("credit card") || cat === "debt payment") return true;
    const d = (r.description || "").toLowerCase();
    return (
      d.includes("payment to chase card") ||
      d.includes("credit crd") ||
      d.includes("crcardpmt") ||
      d.includes("citi autopay") ||
      d.includes("card ending") ||
      d.includes("capital one") ||
      d.includes("synchrony")
    );
  }

  function suggestCardName(description) {
    const d = String(description || "");
    const end = d.match(/card ending\s*(?:in\s*)?(\d{4})/i);
    if (end) {
      let brand = "Card";
      if (/chase/i.test(d)) brand = "Chase";
      else if (/citi/i.test(d)) brand = "Citi";
      else if (/capital one/i.test(d)) brand = "Capital One";
      return `${brand} Card …${end[1]}`;
    }
    if (/chase credit crd|chase credit card/i.test(d)) return "Chase Credit Card";
    if (/citi autopay|citi card/i.test(d)) return "Citi Card";
    if (/capital one/i.test(d)) return "Capital One";
    if (/synchrony/i.test(d)) return "Synchrony";
    if (/usaa/i.test(d) && /cc|payment/i.test(d)) return "USAA Credit Card";
    if (/amex|american express/i.test(d)) return "Amex";
    if (/discover/i.test(d)) return "Discover";
    return d.split(/\s+/).slice(0, 4).join(" ").slice(0, 80) || "Credit card";
  }

  function rebuildImportDebtsFromSelection() {
    const prev = {};
    (state.importDebts || []).forEach((d) => {
      prev[d.key] = d;
    });
    const map = new Map();
    state.importRows.forEach((r) => {
      if (!r.selected || !r.date || !(r.amount > 0)) return;
      if (!isCreditCardRow(r)) return;
      const name = suggestCardName(r.description);
      const key = name.toLowerCase();
      if (!map.has(key)) {
        const old = prev[key];
        map.set(key, {
          key,
          name: old?.name || name,
          apr: old?.apr ?? "",
          balance: old?.balance ?? "",
          min_payment: old?.min_payment ?? "",
        });
      }
    });
    state.importDebts = [...map.values()];
    renderImportDebtPanel();
  }

  function renderImportDebtPanel() {
    const panel = $("#import-debt-panel");
    const tbody = $("#import-debt-table tbody");
    if (!panel || !tbody) return;
    if (!state.importDebts.length) {
      panel.style.display = "none";
      tbody.innerHTML = "";
      return;
    }
    panel.style.display = "block";
    tbody.innerHTML = state.importDebts
      .map(
        (d, i) => `<tr data-debt-idx="${i}">
          <td><input type="text" data-debt-name="${i}" value="${escapeAttr(d.name)}" style="width:100%;background:var(--bg-dark-2);border:1px solid var(--border-hover);border-radius:var(--radius);color:var(--text-primary);padding:0.35rem 0.5rem;font-size:0.85rem" /></td>
          <td class="num"><input class="input-money" type="number" min="0" max="100" step="0.01" placeholder="22.9" data-debt-apr="${i}" value="${escapeAttr(d.apr)}" style="width:5.5rem" /></td>
          <td class="num"><input class="input-money" type="number" min="0" step="0.01" placeholder="optional" data-debt-bal="${i}" value="${escapeAttr(d.balance)}" style="width:7rem" /></td>
          <td class="num"><input class="input-money" type="number" min="0" step="0.01" placeholder="optional" data-debt-min="${i}" value="${escapeAttr(d.min_payment)}" style="width:7rem" /></td>
        </tr>`
      )
      .join("");

    const bind = (sel, field) => {
      tbody.querySelectorAll(sel).forEach((inp) => {
        inp.addEventListener("input", () => {
          const i = Number(inp.dataset[field === "name" ? "debtName" : field === "apr" ? "debtApr" : field === "balance" ? "debtBal" : "debtMin"]);
          // dataset keys from data-debt-name etc.
        });
      });
    };
    tbody.querySelectorAll("[data-debt-name]").forEach((inp) => {
      inp.addEventListener("input", () => {
        const i = Number(inp.dataset.debtName);
        if (state.importDebts[i]) state.importDebts[i].name = inp.value;
      });
    });
    tbody.querySelectorAll("[data-debt-apr]").forEach((inp) => {
      inp.addEventListener("input", () => {
        const i = Number(inp.dataset.debtApr);
        if (state.importDebts[i]) state.importDebts[i].apr = inp.value;
      });
    });
    tbody.querySelectorAll("[data-debt-bal]").forEach((inp) => {
      inp.addEventListener("input", () => {
        const i = Number(inp.dataset.debtBal);
        if (state.importDebts[i]) state.importDebts[i].balance = inp.value;
      });
    });
    tbody.querySelectorAll("[data-debt-min]").forEach((inp) => {
      inp.addEventListener("input", () => {
        const i = Number(inp.dataset.debtMin);
        if (state.importDebts[i]) state.importDebts[i].min_payment = inp.value;
      });
    });
  }

  function renderImportTable() {
    const tbody = $("#import-table tbody");
    const toolbar = $("#import-toolbar");
    if (!tbody) return;
    if (!state.importRows.length) {
      if (toolbar) toolbar.style.display = "none";
      tbody.innerHTML = `<tr><td colspan="8" class="text-muted">Preview a checking statement, then Preview the credit-card file — both stay in this list.</td></tr>`;
      updateImportSelectedCount();
      return;
    }
    if (toolbar) toolbar.style.display = "flex";
    tbody.innerHTML = state.importRows
      .map((r, i) => {
        const cls = r.is_income ? "positive" : "negative";
        const missing = !r.date || !(r.amount > 0);
        const off = !r.selected || missing ? "import-off" : "";
        const dup = r.possible_duplicate ? "import-dup" : "";
        const note = r.possible_duplicate
          ? `<span class="chip chip-warning" title="Same date, amount, and similar name already in your budget">Possible duplicate</span>`
          : missing
            ? `<span class="text-muted">Skipped</span>`
            : "";
        return `<tr class="${off} ${dup}" data-import-idx="${i}">
          <td>
            <input class="import-check" type="checkbox" data-import-check="${i}"
              ${r.selected && !missing ? "checked" : ""} ${missing ? "disabled" : ""} />
          </td>
          <td>${r.date || "— missing"}</td>
          <td class="text-muted" style="font-size:0.78rem">${escapeHtml(r.source || "")}</td>
          <td>${escapeHtml(r.description)}</td>
          <td class="num ${cls}">${money(r.amount)}</td>
          <td>${r.is_income ? "In" : "Out"}</td>
          <td>
            <select class="import-cat" data-import-cat="${i}" ${missing ? "disabled" : ""}>
              ${importCategoryOptions(r.category || (r.is_income ? "Income" : "Other"))}
            </select>
          </td>
          <td>${note}</td>
        </tr>`;
      })
      .join("");

    tbody.querySelectorAll("[data-import-check]").forEach((box) => {
      box.addEventListener("change", () => {
        const i = Number(box.dataset.importCheck);
        if (state.importRows[i]) {
          state.importRows[i].selected = box.checked;
          renderImportTable();
          rebuildImportDebtsFromSelection();
        }
      });
    });
    tbody.querySelectorAll("[data-import-cat]").forEach((sel) => {
      sel.addEventListener("change", () => {
        const i = Number(sel.dataset.importCat);
        if (state.importRows[i]) {
          state.importRows[i].category = sel.value;
          if (sel.value === "Income") state.importRows[i].is_income = true;
          rebuildImportDebtsFromSelection();
        }
      });
    });
    updateImportSelectedCount();
    rebuildImportDebtsFromSelection();
  }

  function setImportSelection(mode) {
    state.importRows.forEach((r) => {
      if (!r.date || !(r.amount > 0)) {
        r.selected = false;
        return;
      }
      if (mode === "all") r.selected = true;
      else if (mode === "none") r.selected = false;
      else if (mode === "income") r.selected = !!r.is_income;
      else if (mode === "expenses") r.selected = !r.is_income;
      else if (mode === "skip-dups") {
        if (r.possible_duplicate) r.selected = false;
      }
    });
    renderImportTable();
    rebuildImportDebtsFromSelection();
  }

  function importRowKey(r) {
    return `${r.date || ""}|${Number(r.amount || 0).toFixed(2)}|${(r.description || "").trim().toLowerCase().slice(0, 80)}`;
  }

  async function previewOneFile(file, bank) {
    const fd = new FormData();
    fd.append("file", file);
    const qs = `commit=false&bank=${encodeURIComponent(bank)}`;
    const res = await fetch(`/api/import/statement?${qs}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${state.token}` },
      body: fd,
    });
    if (!res.ok) {
      const j = await res.json().catch(() => ({}));
      let detail = j.detail || "Import failed";
      if (Array.isArray(detail)) {
        detail = detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
      }
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return res.json();
  }

  async function runImportPreview() {
    const input = $("#statement-file");
    const files = input && input.files ? [...input.files] : [];
    if (!files.length) {
      $("#import-msg").textContent = "Choose one or more CSV/PDF files first (checking and card can both go in).";
      return;
    }
    const msgEl = $("#import-msg");
    if (msgEl) {
      msgEl.textContent = files.length > 1 ? `Reading ${files.length} files…` : "Reading file…";
      msgEl.style.color = "";
    }
    const bank = $("#import-bank")?.value || "auto";
    const existingKeys = new Set(state.importRows.map(importRowKey));
    let added = 0;
    let skippedDup = 0;
    const labels = [];
    for (const file of files) {
      const data = await previewOneFile(file, bank);
      if (data.categories && data.categories.length) {
        state.importCategories = data.categories;
      }
      const label = data.bank_label || "Import";
      const source = `${label} · ${file.name}`;
      labels.push(source);
      const incoming = (data.rows || []).map((r) => ({
        date: r.date,
        description: r.description,
        amount: r.amount,
        is_income: !!r.is_income,
        category: r.category || (r.is_income ? "Income" : "Other"),
        selected: r.selected === true && !!r.date && r.amount > 0,
        possible_duplicate: !!r.possible_duplicate,
        raw: r.raw || "",
        source,
      }));
      for (const row of incoming) {
        const key = importRowKey(row);
        if (existingKeys.has(key)) {
          skippedDup += 1;
          continue;
        }
        existingKeys.add(key);
        state.importRows.push(row);
        added += 1;
      }
    }
    state.importBankLabel = labels[labels.length - 1] || state.importBankLabel || "Import";
    if (input) input.value = "";
    const parts = [`Added ${added} row(s) from ${files.length} file(s).`];
    if (skippedDup) parts.push(`${skippedDup} already in this list were skipped.`);
    parts.push("Preview another file to add it, then Import selected. This does not erase the calendar.");
    if (msgEl) msgEl.textContent = parts.join(" ");
    const badge = $("#import-bank-badge");
    if (badge) {
      const sources = [...new Set(state.importRows.map((r) => r.source).filter(Boolean))];
      badge.innerHTML = sources.length
        ? `In the list: <strong class="text-primary">${escapeHtml(sources.join(" · "))}</strong>`
        : "";
    }
    renderImportTable();
  }

  function clearImportList() {
    state.importRows = [];
    state.importDebts = [];
    const input = $("#statement-file");
    if (input) input.value = "";
    const badge = $("#import-bank-badge");
    if (badge) badge.innerHTML = "";
    const msgEl = $("#import-msg");
    if (msgEl) {
      msgEl.textContent = "Preview list cleared. Calendar items already saved were not deleted.";
      msgEl.style.color = "";
    }
    renderImportTable();
  }

  async function runImportSelected() {
    if (!state.importRows.length) {
      throw new Error(
        "No transactions were found in that file. Chase PDFs from chase.com (not a phone photo) work best. You can also download CSV: Account → See all activity → Download. If the preview table is empty, there is nothing to import yet."
      );
    }
    const dated = state.importRows.filter((r) => r.date && r.amount > 0);
    const selected = dated.filter((r) => r.selected);
    if (!dated.length) {
      throw new Error(
        "The PDF opened, but no row has both a date and an amount. This layout may be a scanned image or a credit-card PDF we could not read. Try Chase CSV, or add the charges by hand on Money in / out."
      );
    }
    if (!selected.length) {
      throw new Error(
        "No rows are checked. Tick the boxes on the left (or tap Select all), then Import selected. Possible duplicates start unchecked on purpose."
      );
    }
    const msgEl = $("#import-msg");
    if (msgEl) {
      msgEl.textContent = `Saving ${selected.length} selected row(s)…`;
      msgEl.style.color = "";
    }

    // Capture debt fields from panel (APR etc.)
    const debts = (state.importDebts || [])
      .map((d) => {
        const apr = parseFloat(d.apr);
        const balance = parseFloat(d.balance);
        const min_payment = parseFloat(d.min_payment);
        return {
          name: (d.name || "").trim(),
          apr: Number.isFinite(apr) ? apr : 0,
          balance: Number.isFinite(balance) ? balance : 0,
          min_payment: Number.isFinite(min_payment) ? min_payment : 0,
          update_existing: true,
        };
      })
      .filter((d) => d.name && (d.apr > 0 || d.balance > 0 || d.min_payment > 0));

    const payload = {
      bank_label: state.importBankLabel || "Import",
      rows: selected.map((r) => ({
        date: r.date,
        description: r.description,
        amount: r.amount,
        is_income: r.category === "Income" ? true : !!r.is_income,
        category: r.category || "Other",
        item_type: r.category === "Income" || r.is_income ? "paycheck" : "actual",
        source: r.source || state.importBankLabel || "Import",
      })),
      debts,
    };
    const data = await api("/api/import/commit", {
      method: "POST",
      json: payload,
    });
    if (msgEl) {
      msgEl.textContent = data.message || `Saved ${data.imported}`;
      msgEl.style.color = "var(--success)";
    }
    const jump = data.last_date || data.first_date;
    if (jump) {
      const d = new Date(String(jump) + "T12:00:00");
      if (!Number.isNaN(d.getTime())) {
        state.year = d.getFullYear();
        state.month = d.getMonth() + 1;
      }
    }
    let extra = "";
    if (data.debts_created || data.debts_updated) {
      extra =
        `\n\nDebt plan: ${data.debts_created || 0} card(s) added, ` +
        `${data.debts_updated || 0} updated with APR/balance. Open Debt plan to run paydown.`;
    }
    const savedKeys = new Set(selected.map(importRowKey));
    state.importRows = state.importRows.filter((r) => !savedKeys.has(importRowKey(r)));
    renderImportTable();
    const leftover = state.importRows.length;
    const stayMsg = leftover
      ? ` ${leftover} other preview row(s) are still here.`
      : " Preview another statement (checking or card) to add it — it will not replace what you just saved.";
    if (msgEl) {
      msgEl.textContent = (data.message || `Saved ${data.imported}`) + extra + stayMsg;
    }
    alert(
      `${data.message || `Saved ${data.imported} item(s).`}${extra}\n\n` +
        `Those stay on the calendar. You can Preview the other statement next (checking + card both keep).`
    );
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

    const forgotBtn = $("#btn-forgot");
    const recoverForm = $("#recover-form");
    if (forgotBtn && recoverForm) {
      forgotBtn.addEventListener("click", () => {
        recoverForm.hidden = !recoverForm.hidden;
      });
    }
    if (recoverForm) {
      recoverForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const msg = $("#recover-msg");
        if (msg) msg.textContent = "Checking the rescue code…";
        try {
          const res = await fetch("/api/recover", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              rescue_code: $("#recover-code").value,
              new_password: $("#recover-pass").value,
              username: $("#recover-user").value.trim() || null,
            }),
          });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) {
            throw new Error(data.detail || "Could not reset the password");
          }
          if (msg) msg.textContent = data.message || "Password reset. Sign in above.";
          if ($("#password")) $("#password").value = "";
          if ($("#username") && data.username) $("#username").value = data.username;
        } catch (ex) {
          if (msg) msg.textContent = ex.message || "Could not reset the password";
        }
      });
    }

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

    const printBtn = $("#btn-print-month");
    if (printBtn) {
      printBtn.addEventListener("click", () => printMonthOverview());
    }
    const copyMonthBtn = $("#btn-copy-month");
    if (copyMonthBtn) {
      copyMonthBtn.addEventListener("click", () => copyLastMonth());
    }

    const editForm = $("#edit-item-form");
    if (editForm) {
      editForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const msg = $("#edit-item-msg");
        const id = $("#edit-item-id").value;
        try {
          const itemType = $("#edit-item-type").value;
          const scope = editScopeValue();
          await api(`/api/items/${id}?scope=${encodeURIComponent(scope)}`, {
            method: "PATCH",
            json: {
              name: $("#edit-item-name").value.trim(),
              amount: parseFloat($("#edit-item-amount").value),
              due_date: $("#edit-item-date").value,
              item_type: itemType,
              frequency: itemType === "balance" ? "once" : $("#edit-item-freq").value,
              notes: $("#edit-item-notes").value,
              category: $("#edit-item-category").value,
              is_income: itemType === "paycheck",
              is_paid: !!$("#edit-item-paid")?.checked,
              is_subscription: !!$("#edit-item-sub")?.checked,
            },
          });
          if (msg) msg.textContent = "Saved.";
          closeEditItemModal();
          await refreshDashboard();
          await refreshInput().catch(() => {});
        } catch (ex) {
          if (msg) msg.textContent = ex.message;
          else alert(ex.message);
        }
      });
    }
    const editCancel = $("#edit-item-cancel");
    if (editCancel) editCancel.addEventListener("click", () => closeEditItemModal());
    const editModal = $("#edit-item-modal");
    if (editModal) {
      editModal.addEventListener("click", (e) => {
        if (e.target === editModal) closeEditItemModal();
      });
    }

    const backupBtn = $("#btn-backup");
    if (backupBtn) backupBtn.addEventListener("click", () => downloadBackup());
    const backupLocalBtn = $("#btn-backup-local");
    if (backupLocalBtn) {
      backupLocalBtn.addEventListener("click", async () => {
        const msg = $("#backup-msg");
        try {
          const res = await api("/api/backup/local", { method: "POST" });
          if (msg) msg.textContent = res.message || "Saved on this computer.";
          await refreshBackupStatus();
          await renderHomeNotes();
        } catch (ex) {
          if (msg) msg.textContent = ex.message || "Could not save a copy.";
        }
      });
    }
    const rescueNewBtn = $("#btn-rescue-new");
    if (rescueNewBtn) {
      rescueNewBtn.addEventListener("click", async () => {
        if (
          !confirm(
            "Make a new rescue code?\n\nWrite the next code down. The old code will stop working. Your budget is not erased."
          )
        ) {
          return;
        }
        const out = $("#rescue-settings-code");
        const msg = $("#rescue-settings-msg");
        try {
          const res = await api("/api/household/rescue-code", { method: "POST" });
          if (out) out.textContent = res.rescue_code || "";
          if (msg) msg.textContent = "Write this down now. It will not be shown again.";
          const st = $("#rescue-status");
          if (st) st.textContent = "A rescue code is set. Keep the paper somewhere safe.";
          await renderHomeNotes();
        } catch (ex) {
          if (msg) msg.textContent = ex.message || "Could not make a rescue code.";
        }
      });
    }
    const rescueOk = $("#rescue-code-ok");
    if (rescueOk) {
      rescueOk.addEventListener("click", async () => {
        showPasswordGate(false);
        showApp(true);
        await refreshAll();
      });
    }
    const restoreFile = $("#restore-file");
    if (restoreFile) {
      restoreFile.addEventListener("change", async () => {
        const f = restoreFile.files?.[0];
        if (f) await restoreBackup(f);
        restoreFile.value = "";
      });
    }

    $("#item-name").addEventListener("change", toggleCustomName);

    function updateItemFreqHint() {
      const hint = $("#item-freq-hint");
      const freqEl = $("#item-freq");
      const typeEl = $("#item-type");
      if (!hint || !freqEl) return;
      const itemType = typeEl ? typeEl.value : "bill";
      if (itemType === "balance") {
        freqEl.value = "once";
        freqEl.disabled = true;
        hint.textContent = "Bank balance is always one time (the day you checked).";
        return;
      }
      freqEl.disabled = false;
      const f = freqEl.value;
      if (f === "monthly") {
        hint.textContent =
          "Same day each month (like rent). Later months fill in by themselves.";
      } else if (f === "yearly") {
        hint.textContent =
          "Once a year (Amazon Prime, some Apple plans). Next year fills in by itself.";
      } else if (f === "biweekly") {
        hint.textContent =
          "Every 2 weeks (like many paychecks). Later months fill in by themselves.";
      } else {
        hint.textContent = "Only the date you pick — nothing repeats.";
      }
    }
    $("#item-type").addEventListener("change", () => {
      const t = $("#item-type").value;
      const freq = $("#item-freq");
      if (t === "paycheck" && freq && freq.value === "once") {
        freq.value = "biweekly";
      }
      if ((t === "bill" || t === "estimate") && freq && freq.value === "once") {
        freq.value = "monthly";
      }
      updateItemFreqHint();
    });
    const itemFreq = $("#item-freq");
    if (itemFreq) itemFreq.addEventListener("change", updateItemFreqHint);
    updateItemFreqHint();

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
        const freq = itemType === "balance" ? "once" : $("#item-freq").value;
        await api("/api/items", {
          method: "POST",
          json: {
            name: itemType === "balance" ? name || "Bank balance" : name,
            item_type: itemType,
            amount: parseFloat($("#item-amount").value),
            is_income: itemType === "paycheck",
            due_date: $("#item-date").value,
            frequency: freq,
            notes: $("#item-notes").value,
            category: itemType === "balance" ? "Balance" : $("#item-category").value,
            retain_name: $("#item-retain").checked,
            is_subscription: !!$("#item-sub")?.checked,
          },
        });
        if (itemType === "balance") {
          msg.textContent =
            "Bank balance saved — calendar act/est restart from that date.";
        } else if (freq === "monthly") {
          msg.textContent = "Saved. It will keep showing up on that day each month.";
        } else if (freq === "biweekly") {
          msg.textContent = "Saved. It will keep showing up every 2 weeks.";
        } else {
          msg.textContent = "Saved.";
        }
        $("#item-amount").value = "";
        $("#item-notes").value = "";
        await refreshInput();
        await refreshDashboard();
      } catch (ex) {
        msg.textContent = ex.message;
      }
    });

    const btnUpdateCheck = $("#btn-update-check");
    const btnUpdateApply = $("#btn-update-apply");
    if (btnUpdateCheck) {
      btnUpdateCheck.addEventListener("click", async () => {
        setUpdateBusy(true);
        const msgEl = $("#update-msg");
        if (msgEl) {
          msgEl.classList.remove("is-error", "is-ready", "is-ok");
          msgEl.textContent = "Checking for a newer version…";
        }
        try {
          await refreshUpdatePanel();
        } finally {
          setUpdateBusy(false);
        }
      });
    }
    if (btnUpdateApply) {
      btnUpdateApply.addEventListener("click", () => runAppUpdate());
    }

    $("#settings-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const msg = $("#settings-msg");
      try {
        const thrRaw = $("#hh-threshold") ? parseFloat($("#hh-threshold").value) : 0;
        const ageRaw = $("#hh-primary-age")
          ? parseInt($("#hh-primary-age").value, 10)
          : 0;
        const partnerRaw = $("#hh-partner-age")
          ? parseInt($("#hh-partner-age").value, 10)
          : 0;
        await api("/api/household", {
          method: "PATCH",
          json: {
            name: $("#hh-name").value.trim(),
            starting_balance: parseFloat($("#hh-balance").value),
            safety_threshold: Number.isFinite(thrRaw) ? Math.max(thrRaw, 0) : 0,
            // 0 clears age
            primary_age: Number.isFinite(ageRaw) ? ageRaw : 0,
            partner_age: Number.isFinite(partnerRaw) ? partnerRaw : 0,
            state: $("#hh-state") ? $("#hh-state").value : "",
            idle_minutes: $("#hh-idle") ? parseInt($("#hh-idle").value, 10) : DEFAULT_IDLE_MIN,
          },
        });
        if ($("#hh-idle")) applyIdleMinutes(parseInt($("#hh-idle").value, 10));
        msg.textContent = "Saved.";
        await refreshDashboard();
      } catch (ex) {
        msg.textContent = ex.message;
      }
    });

    $("#btn-preview-import").addEventListener("click", async () => {
      try {
        await runImportPreview();
      } catch (ex) {
        $("#import-msg").textContent = ex.message;
      }
    });
    const clearImport = $("#btn-import-clear");
    if (clearImport) {
      clearImport.addEventListener("click", () => clearImportList());
    }
    $("#btn-commit-import").addEventListener("click", async () => {
      try {
        await runImportSelected();
      } catch (ex) {
        $("#import-msg").textContent = ex.message;
        alert(ex.message || "Import failed");
      }
    });
    const impAll = $("#btn-import-all");
    const impNone = $("#btn-import-none");
    const impInc = $("#btn-import-income");
    const impExp = $("#btn-import-expenses");
    if (impAll) impAll.addEventListener("click", () => setImportSelection("all"));
    if (impNone) impNone.addEventListener("click", () => setImportSelection("none"));
    if (impInc) impInc.addEventListener("click", () => setImportSelection("income"));
    if (impExp) impExp.addEventListener("click", () => setImportSelection("expenses"));
    const impSkip = $("#btn-import-skip-dups");
    if (impSkip) impSkip.addEventListener("click", () => setImportSelection("skip-dups"));

    const closeBtn = $("#day-expand-close");
    if (closeBtn) closeBtn.addEventListener("click", () => closeDayExpand());

    function updateGoalSplitHint() {
      const el = $("#goal-split-hint");
      if (!el) return;
      const target = parseFloat($("#goal-target")?.value) || 0;
      const current = parseFloat($("#goal-current")?.value) || 0;
      const dateStr = $("#goal-date")?.value;
      if (!dateStr || target <= 0) {
        el.textContent =
          "Set a target date to see the monthly split. Leave monthly at 0 to use that split. Log a different amount each month on the goal card.";
        return;
      }
      const remaining = Math.max(target - current, 0);
      const t = new Date(`${dateStr}T12:00:00`);
      const now = new Date();
      let months = (t.getFullYear() - now.getFullYear()) * 12 + (t.getMonth() - now.getMonth());
      months = Math.max(months, 1);
      if (remaining <= 0) {
        el.textContent = "Already at the target.";
        return;
      }
      const split = remaining / months;
      el.textContent = `Split: about ${money(split)}/mo for ${months} month${months === 1 ? "" : "s"} to hit that date. Leave monthly at 0 to use this. You can still log a different amount each month.`;
    }
    ["goal-target", "goal-current", "goal-date"].forEach((id) => {
      const n = document.getElementById(id);
      if (n) n.addEventListener("input", updateGoalSplitHint);
      if (n) n.addEventListener("change", updateGoalSplitHint);
    });

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

    const parseStub = $("#btn-parse-paystub");
    if (parseStub) {
      parseStub.addEventListener("click", async () => {
        const file = $("#paystub-file")?.files?.[0];
        const msg = $("#paystub-parse-msg");
        if (!file) {
          if (msg) msg.textContent = "Choose a PDF first.";
          return;
        }
        if (msg) msg.textContent = "Reading pay stub…";
        try {
          const fd = new FormData();
          fd.append("file", file);
          const res = await fetch("/api/paystub/parse", {
            method: "POST",
            headers: { Authorization: `Bearer ${state.token}` },
            body: fd,
          });
          if (!res.ok) {
            const j = await res.json().catch(() => ({}));
            throw new Error(j.detail || "Could not read PDF");
          }
          const data = await res.json();
          fillPaystubForm(data.parsed || {});
          if (msg) msg.textContent = data.message || "Check the numbers, then apply.";
        } catch (ex) {
          if (msg) msg.textContent = ex.message || "Could not read PDF";
        }
      });
    }
    const psNet = $("#ps-net");
    const psFreq = $("#ps-freq");
    if (psNet) psNet.addEventListener("input", updatePaystubMonthly);
    if (psFreq) psFreq.addEventListener("change", updatePaystubMonthly);
    const psForm = $("#paystub-apply-form");
    if (psForm) {
      psForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const msg = $("#paystub-apply-msg");
        try {
          const data = await api("/api/paystub/apply", {
            method: "POST",
            json: {
              employer: $("#ps-employer")?.value.trim() || "Paycheck",
              employee_label: $("#ps-who")?.value.trim() || "",
              net_pay: parseFloat($("#ps-net").value),
              gross_pay: parseFloat($("#ps-gross")?.value) || 0,
              pay_date: $("#ps-date").value,
              frequency: $("#ps-freq")?.value || "biweekly",
              create_paycheck: !!$("#ps-create")?.checked,
              save_job_profile: !!$("#ps-save-job")?.checked,
              schedule_future: parseInt($("#ps-future")?.value || "0", 10),
              notes: $("#ps-notes")?.value || "",
            },
          });
          if (msg) msg.textContent = data.message || "Saved.";
          await refreshPaystub();
          await refreshDashboard();
        } catch (ex) {
          if (msg) msg.textContent = ex.message;
        }
      });
    }

    const subsForm = $("#subs-form");
    if (subsForm) {
      const subDate = $("#sub-date");
      if (subDate && !subDate.value) subDate.value = isoDate();
      subsForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const msg = $("#subs-form-msg");
        try {
          const data = await api("/api/subscriptions", {
            method: "POST",
            json: {
              name: $("#sub-name").value.trim(),
              amount: parseFloat($("#sub-amount").value),
              due_date: $("#sub-date").value,
              frequency: $("#sub-freq").value || "monthly",
            },
          });
          if (msg) msg.textContent = data.message || "Saved.";
          $("#sub-name").value = "";
          $("#sub-amount").value = "";
          await refreshSubs();
          await refreshDashboard().catch(() => {});
        } catch (ex) {
          if (msg) msg.textContent = ex.message;
        }
      });
    }

    const cardMan = $("#card-manual-form");
    if (cardMan) {
      cardMan.addEventListener("submit", async (e) => {
        e.preventDefault();
        const msg = $("#card-man-msg");
        const due = ($("#card-man-due")?.value || "").trim();
        try {
          const data = await api("/api/debts", {
            method: "POST",
            json: {
              name: $("#card-man-name").value.trim(),
              last4: ($("#card-man-last4")?.value || "").trim(),
              balance: parseFloat($("#card-man-balance").value),
              apr: parseFloat($("#card-man-apr")?.value) || 0,
              min_payment: parseFloat($("#card-man-pay")?.value) || 0,
              due_date: due || null,
              notes: ($("#card-man-notes")?.value || "").trim(),
              kind: "card",
              put_min_on_calendar: !!$("#card-man-cal")?.checked,
            },
          });
          if (msg) msg.textContent = `Saved ${data.name || "card"}.`;
          cardMan.reset();
          if ($("#card-man-apr")) $("#card-man-apr").value = "0";
          if ($("#card-man-cal")) $("#card-man-cal").checked = true;
          await refreshCards();
          await refreshDebts().catch(() => {});
          await refreshDashboard().catch(() => {});
        } catch (ex) {
          if (msg) msg.textContent = ex.message;
        }
      });
    }

    const cardPrev = $("#btn-card-preview");
    if (cardPrev) {
      cardPrev.addEventListener("click", async () => {
        const file = $("#card-stmt-file")?.files?.[0];
        const msg = $("#card-preview-msg");
        if (!file) {
          if (msg) msg.textContent = "Choose a credit-card PDF first.";
          return;
        }
        if (msg) msg.textContent = "Reading statement…";
        try {
          const fd = new FormData();
          fd.append("file", file);
          const res = await fetch("/api/cards/preview", {
            method: "POST",
            headers: { Authorization: `Bearer ${state.token}` },
            body: fd,
          });
          if (!res.ok) {
            const j = await res.json().catch(() => ({}));
            throw new Error(j.detail || "Could not read PDF");
          }
          const data = await res.json();
          renderCardPreview(data);
          if (msg) msg.textContent = data.message || "Check the totals, then save.";
        } catch (ex) {
          if (msg) msg.textContent = ex.message;
        }
      });
    }
    const cardApply = $("#btn-card-apply");
    if (cardApply) {
      cardApply.addEventListener("click", async () => {
        const p = state.cardPreview;
        const msg = $("#card-apply-msg");
        if (!p || !p.summary) {
          if (msg) msg.textContent = "Read a statement first.";
          return;
        }
        const s = p.summary;
        const stmtMin = parseFloat($("#card-edit-stmt-min")?.value);
        const pay = parseFloat($("#card-edit-pay")?.value);
        const monthlyPay = Number.isFinite(pay) && pay > 0 ? pay : Number.isFinite(stmtMin) ? stmtMin : 0;
        try {
          const data = await api("/api/cards/apply", {
            method: "POST",
            json: {
              debt_id: p.matched_debt_id || null,
              name: s.card_name || "Chase card",
              last4: s.last4 || "",
              new_balance: parseFloat($("#card-edit-balance")?.value) || 0,
              apr: parseFloat($("#card-edit-apr")?.value) || 0,
              min_payment: monthlyPay,
              due_date: $("#card-edit-due")?.value || s.due_date || null,
              statement_date: s.statement_date || null,
              last_interest: Number(s.interest_charged) || 0,
              transactions: (p.transactions || []).map((t) => ({
                date: t.date,
                description: t.description,
                amount: t.amount,
                is_credit: !!t.is_credit,
                category: t.category || "",
              })),
              put_min_on_calendar: !!$("#card-put-min")?.checked,
            },
          });
          if (msg) msg.textContent = data.message || "Saved.";
          state.cardPreview = null;
          const box = $("#card-preview-box");
          if (box) box.style.display = "none";
          const file = $("#card-stmt-file");
          if (file) file.value = "";
          await refreshCards();
          await refreshDebts().catch(() => {});
          await refreshDashboard().catch(() => {});
        } catch (ex) {
          if (msg) msg.textContent = ex.message;
        }
      });
    }

    const recAdd = $("#recurring-add-form");
    if (recAdd) {
      recAdd.addEventListener("submit", async (e) => {
        e.preventDefault();
        const msg = $("#rec-add-msg");
        const freq = $("#rec-add-freq")?.value || "monthly";
        const t = new Date();
        let dueStr = ($("#rec-add-start")?.value || "").trim();
        if (freq === "monthly") {
          const day = parseInt($("#rec-add-day").value, 10) || 1;
          const last = new Date(t.getFullYear(), t.getMonth() + 1, 0).getDate();
          const d = Math.min(Math.max(day, 1), last);
          const due = new Date(t.getFullYear(), t.getMonth(), d);
          dueStr = `${due.getFullYear()}-${String(due.getMonth() + 1).padStart(2, "0")}-${String(due.getDate()).padStart(2, "0")}`;
        } else if (!dueStr) {
          dueStr = isoDate(t);
        }
        try {
          await api("/api/items", {
            method: "POST",
            json: {
              name: $("#rec-add-name").value.trim(),
              item_type: $("#rec-add-type").value || "bill",
              amount: parseFloat($("#rec-add-amount").value),
              due_date: dueStr,
              frequency: freq,
              is_income: ($("#rec-add-type").value || "") === "paycheck",
              retain_name: true,
            },
          });
          if (msg) msg.textContent = "Added.";
          $("#rec-add-name").value = "";
          $("#rec-add-amount").value = "";
          await refreshRecurring();
          await refreshDashboard().catch(() => {});
        } catch (ex) {
          if (msg) msg.textContent = ex.message;
        }
      });
    }

    $("#btn-run-plan").addEventListener("click", () => runDebtPlan());
    const debtCalBtn = $("#btn-debt-cal");
    if (debtCalBtn) {
      debtCalBtn.addEventListener("click", async () => {
        const extra = parseFloat($("#plan-extra")?.value);
        if (!extra || extra <= 0) {
          alert("Enter an extra monthly payment first (above).");
          return;
        }
        try {
          const data = await api(
            `/api/debts/extra-to-calendar?extra_monthly=${encodeURIComponent(extra)}&year=${state.year}&month=${state.month}`,
            { method: "POST" }
          );
          alert(data.message || "Added to the calendar.");
          await refreshDashboard();
        } catch (ex) {
          alert(ex.message || "Could not add to calendar");
        }
      });
    }

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
          const res = await api("/api/me/password", {
            method: "POST",
            json: {
              current_password: $("#set-pw-current").value,
              new_password: n1,
            },
          });
          if (res && res.rescue_code) {
            if (msg) {
              msg.textContent =
                "Password updated. Write this rescue code down — it will not be shown again: " +
                res.rescue_code;
            }
            const out = $("#rescue-settings-code");
            if (out) out.textContent = res.rescue_code;
          } else if (msg) {
            msg.textContent =
              (res && res.message) || "Password updated. Other devices were signed out.";
          }
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
