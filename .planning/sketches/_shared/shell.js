// Frame D from sketch 001, shared by sketches 002-004.
// Shell.mount(el, { detail(e, box), pages: { key: {label, group, badge, render(box)} }, select, page })
(function () {
  const D = DATA, F = fmt;

  const auditRow = (e, cls = "row clickable") => `<div class="${cls}${e.preview ? " preview" : ""}" data-ts="${e.ts}">
    <span class="time">${F.time(e.ts)}</span>${F.appico(e.app)}
    <div class="grow"><div class="title">${F.title(e)}</div>
      <div class="sub"><span class="mono">${e.tool}</span>${e.receipt ? " · receipt" : ""}${e.undone_by ? " · undone" : ""}</div></div>
    ${e.preview ? `<span class="chip">preview</span>` : F.tierChip(e.tier)}</div>`;

  const healthRows = () => [
    ["ok", "Daemon", "Running as ren.lav.macos-apps-mcp, pid 4121"],
    ["ok", "Full Disk Access", "Granted"],
    ["ok", "EventKit", "Calendar and Reminders: full access"],
    ["bad", "Automation → Photos", "Denied"],
    ["warn", "Automation → Safari", "Not asked yet"],
    ["ok", "Outbound", "Send enabled for: mail"],
    ["ok", "Mail backups", "18.4 MB in 23 receipts (oldest 2026-08-11)"],
  ].map(([d, t, s]) => `<div class="row"><span class="dot ${d}"></span><div class="grow"><div class="title">${t}</div><div class="sub">${s}</div></div></div>`).join("");

  const deploymentRows = () => {
    const v = D.server;
    return [["Version", `${v.version} · built ${v.build}`], ["Mode", `${v.mode}, pid ${v.pid}, up ${v.uptime}`], ["Listens on", `${v.bind} (loopback only)`], ["Grant identity", v.responsible]]
      .map(([k, x]) => `<div class="row"><div class="grow"><div class="title">${k}</div></div><span class="muted">${x}</span></div>`).join("");
  };

  const adapterRow = (a) => {
    const pill = a.grant === "granted" ? "" : `<span class="chip ${a.grant === "denied" ? "danger" : ""}">${a.grant}</span>`;
    return `<div class="row">${F.appico(a.name)}<div class="grow"><div class="title">${a.name}</div>
      <div class="sub">${a.permission} · ${a.tools} tools</div></div>${pill}
      <label class="switch"><input type="checkbox" ${a.enabled ? "checked" : ""} onchange="toast('${a.name} ' + (this.checked ? 'on' : 'off') + ' — applies after restart (sketch 004)')"><span></span></label></div>`;
  };

  const usageRows = () => [["mail_search", 812], ["events", 301], ["reminders", 260], ["mail", 244], ["mail_body", 190], ["notes", 71], ["create_reminder", 38], ["move_mail", 21]]
    .map(([t, n]) => `<div class="row"><span class="mono" style="width:140px">${t}</span><div class="grow"><div class="usage-bar" style="width:${(n / 812) * 100}%"></div></div><span class="muted" style="width:40px;text-align:right">${n}</span></div>`).join("");

  const header = (e) => `<button class="btn link b-back" style="margin-bottom:8px">‹ Back</button>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">${F.appico(e.app)}${e.preview ? `<span class="chip">preview</span>` : F.tierChip(e.tier)}<span class="muted">${F.day(e.ts)} ${F.time(e.ts)}</span></div>
    <h2>${F.title(e)}</h2>`;

  const defaultPages = {
    health: { label: "Health", group: "System", badge: `<span class="dot warn"></span>`, render: (b) => b.innerHTML = `<h1>Health</h1><p class="lede">What <span class="mono">doctor</span> reports right now.</p><div class="group">${healthRows()}</div><div class="group-title">Deployment</div><div class="group">${deploymentRows()}</div>` },
    adapters: { label: "Adapters", group: "System", badge: `${D.adapters.filter((a) => a.enabled).length}/${D.adapters.length}`, render: (b) => b.innerHTML = `<h1>Adapters</h1><p class="lede">Turn an app off and its tools disappear after the daemon restarts.</p><div class="group">${D.adapters.map(adapterRow).join("")}</div>` },
    usage: { label: "Usage", group: "System", render: (b) => b.innerHTML = `<h1>Usage</h1><p class="lede">Calls per tool since the log started.</p><div class="group">${usageRows()}</div>` },
  };

  function mount(shell, opts) {
    const pages = { ...defaultPages, ...(opts.pages || {}) };
    const q = (x) => shell.querySelector(x), qa = (x) => [...shell.querySelectorAll(x)];
    const apps = [...new Set(D.audit.map((e) => e.app))];
    const count = (f) => D.audit.filter((e) => !e.preview && f(e)).length;
    const groups = [...new Set(Object.values(pages).map((p) => p.group))];
    const pageNav = (g) => Object.entries(pages).filter(([, p]) => p.group === g)
      .map(([k, p]) => `<button class="nav-item" data-page="${k}">${p.label}<span class="count">${p.badge || ""}</span></button>`).join("");
    shell.innerHTML = `<aside class="sidebar">
        <h6>Writes</h6>
        <button class="nav-item active" data-filter="all">All writes<span class="count">${count(() => true)}</span></button>
        <button class="nav-item" data-filter="receipt">Batches with receipts<span class="count">${count((e) => e.receipt)}</span></button>
        <button class="nav-item" data-filter="outbound">Sent off this Mac<span class="count">${count((e) => e.tier === "outbound")}</span></button>
        ${groups.includes("Review") ? pageNav("Review") : ""}
        <h6>Apps</h6>
        ${apps.map((a) => `<button class="nav-item" data-filter="app:${a}">${F.appico(a)}${a}<span class="count">${count((e) => e.app === a)}</span></button>`).join("")}
        <h6>System</h6>${pageNav("System")}
        <div class="muted" style="font-size:var(--text-xs);padding:var(--space-4) var(--space-2)">v0.14.0 · 127.0.0.1 only</div>
      </aside>
      <div class="b-list"><div class="search"><input placeholder="Filter" aria-label="Filter writes"><label><input type="checkbox" class="show-previews" checked>Previews</label></div><div class="b-rows"></div></div>
      <div class="b-detail"><div class="b-empty">Select a write</div></div>
      <div class="b-page"></div>`;

    let filter = "all", query = "", sel = null, previews = true;
    // A search also finds the batch that touched a message ("where did my email go?").
    const targetText = (e) => { const r = e.receipt && D.receipts[e.receipt]; return r ? r.targets.map((t) => t.summary).join(" ") : ""; };
    const match = (e) =>
      (previews || !e.preview) &&
      !(filter === "receipt" && !e.receipt) && !(filter === "outbound" && e.tier !== "outbound") &&
      !(filter.startsWith("app:") && e.app !== filter.slice(4)) &&
      (!query || (F.title(e) + e.tool + targetText(e)).toLowerCase().includes(query));
    function render() {
      let html = "", day = "";
      for (const e of D.audit.filter(match)) {
        const d = F.day(e.ts);
        if (d !== day) { html += `<div class="day">${d}</div>`; day = d; }
        html += auditRow(e, "row clickable" + (sel === e.ts ? " selected" : ""));
      }
      q(".b-rows").innerHTML = html || `<div class="b-empty" style="height:200px">No writes match</div>`;
      qa(".b-rows .row").forEach((r) => r.onclick = () => select(r.dataset.ts));
    }
    function select(ts) {
      sel = ts;
      shell.classList.remove("system-open");
      shell.classList.add("detail-open");
      render();
      const box = q(".b-detail");
      opts.detail(D.audit.find((x) => x.ts === ts), box, { query });
      box.scrollTop = 0;
    }
    const activate = (btn) => qa(".sidebar .nav-item").forEach((x) => x.classList.toggle("active", x === btn));
    function openPage(k) {
      activate(q(`[data-page="${k}"]`));
      q(".b-page").innerHTML = "";
      pages[k].render(q(".b-page"), { select, activate: (f) => q(`[data-filter="${f}"]`).click() });
      shell.classList.add("system-open");
    }
    qa("[data-filter]").forEach((b) => b.onclick = () => { filter = b.dataset.filter; shell.classList.remove("system-open"); activate(b); render(); });
    qa("[data-page]").forEach((b) => b.onclick = () => openPage(b.dataset.page));
    q(".search input").oninput = (ev) => { query = ev.target.value.toLowerCase(); render(); };
    q(".show-previews").onchange = (ev) => { previews = ev.target.checked; render(); };
    shell.addEventListener("click", (ev) => { if (ev.target.closest(".b-back")) shell.classList.remove("detail-open"); });
    render();
    if (opts.select) select(opts.select);
    if (opts.page) openPage(opts.page);
    return { select, openPage, refresh: () => { render(); if (sel) opts.detail(D.audit.find((x) => x.ts === sel), q(".b-detail"), { query }); } };
  }

  window.Shell = { mount, auditRow, header, healthRows, adapterRow, usageRows, deploymentRows };
})();
