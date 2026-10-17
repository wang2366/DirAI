// Status badges for www/index.html, injected by html_server.py (owner only).
(function () {
  const css = `.rv-badge{display:inline-block;margin-left:8px;padding:1px 8px;border-radius:10px;font:600 11px system-ui;color:#fff;vertical-align:middle}
  .rv-working{background:#b26b00}.rv-queued{background:#7b1fa2}.rv-unread{background:#0b63ce}.rv-read{background:#2e7d32}.rv-closed{background:#666}.rv-asking{background:#c62828}
  .rv-rep{margin-left:6px;font:600 11px system-ui;opacity:.75;vertical-align:middle}
  #rv-summary{margin:.5rem 0;font:13px system-ui}
  .rv-ctx{display:inline-block;margin-left:6px;padding:1px 7px;border-radius:10px;font:600 11px system-ui;vertical-align:middle;
    border:1px solid currentColor}.rv-ctx.warn{color:#b26b00}.rv-ctx.high{color:#c62828}
  .rv-card{display:inline-block;margin-left:6px;padding:1px 7px;border-radius:10px;font:600 11px system-ui;vertical-align:middle;color:#c62828;border:1px solid currentColor}`;
  document.head.insertAdjacentHTML("beforeend", "<style>" + css + "</style>");
  const order = {unread: 0, working: 1, queued: 2, read: 3, closed: 4};
  const LABEL = {closed: "TaskDone"};   // shown name for a stored status
  const rows = [...document.querySelectorAll("#rows tr")];
  const tbody = document.getElementById("rows");
  // ../a/b/index.html  ->  a/b
  const pageOf = tr => decodeURI(tr.querySelector("a").getAttribute("href")).replace(/^\.\.\//, "")
    .replace(/\/?index\.html$/, "");

  function update() {
    fetch("/_review/all").then(r => r.json()).then(all => {
      const counts = {};
      rows.forEach(tr => {
        const st = (all[pageOf(tr)] || {}).status;
        tr.dataset.rv = st ? order[st] : 9;
        let b = tr.querySelector(".rv-badge");
        if (!st) { if (b) b.remove(); return; }
        counts[st] = (counts[st] || 0) + 1;
        if (!b) { b = document.createElement("span"); tr.querySelector("a").after(b); }
        const asking = (all[pageOf(tr)] || {}).asking;   // its run waits for an answer in the page chat
        b.className = "rv-badge rv-" + (asking ? "asking" : st); b.textContent = asking ? "needs you" : LABEL[st] || st;
        const every = (all[pageOf(tr)] || {}).repeat;
        let r = tr.querySelector(".rv-rep");
        if (every) {
          if (!r) { r = document.createElement("span"); r.className = "rv-rep"; b.after(r); }
          r.textContent = "🔁 " + {hour: "hourly", day: "daily", week: "weekly"}[every];
          r.title = "The assistant gets this page's repeated message every " + every;
        } else if (r) r.remove();
        // the page's summary card is missing or incomplete (pages an assistant has worked on)
        const card = (all[pageOf(tr)] || {}).card;
        let k = tr.querySelector(".rv-card");
        if (card) {
          if (!k) { k = document.createElement("span"); k.className = "rv-card"; b.after(k); }
          k.textContent = "card ✗";
          k.title = "This page's summary card is missing or incomplete; open the page to see what";
        } else if (k) k.remove();
        // big session context: suggest Compact (warn/high levels match review.py)
        const ctx = (all[pageOf(tr)] || {}).context;
        let c = tr.querySelector(".rv-ctx");
        if (ctx >= 150000) {
          if (!c) { c = document.createElement("span"); b.after(c); }
          c.className = "rv-ctx " + (ctx >= 300000 ? "high" : "warn");
          c.textContent = Math.round(ctx / 1000) + "K context";
          c.title = "This page's assistant session resends this many tokens with every message; open it and press Compact";
        } else if (c) c.remove();
      });
      // order by status until the owner sorts a column themselves
      if (!tbody.dataset.userSort)
        rows.slice().sort((a, b) => a.dataset.rv - b.dataset.rv).forEach(tr => tbody.appendChild(tr));
      let s = document.getElementById("rv-summary");
      if (!s) { s = document.createElement("div"); s.id = "rv-summary"; document.querySelector(".meta").after(s); }
      s.textContent = "AI assistant: " + (["unread", "working", "queued", "read", "closed"]
        .filter(k => counts[k]).map(k => counts[k] + " " + (LABEL[k] || k)).join(" · ") || "none yet");
    });
  }
  update();
  setInterval(update, 5000);

  // Claude plan usage (owner only), with the % at which new assistant runs are held back
  document.head.insertAdjacentHTML("beforeend", `<style>
  #rv-usage{display:flex;flex-wrap:wrap;gap:6px 18px;margin:.4rem 0;font:13px system-ui;align-items:center}
  #rv-usage .u{display:flex;align-items:center;gap:6px}
  #rv-usage .bar{position:relative;width:140px;height:8px;border-radius:4px;background:rgba(128,128,128,.25)}
  #rv-usage .fill{position:absolute;left:0;top:0;bottom:0;border-radius:4px;background:#2e7d32}
  #rv-usage .warn .fill{background:#b26b00} #rv-usage .over .fill{background:#c62828}
  /* the stop level: a range input laid over the bar, its thumb a marker you drag */
  #rv-usage input[type=range]{position:absolute;left:-7px;width:calc(100% + 14px);top:-6px;height:20px;margin:0;padding:0;border:0;box-sizing:border-box;
    background:none;-webkit-appearance:none;appearance:none;cursor:ew-resize}
  #rv-usage input[type=range]::-webkit-slider-runnable-track{background:none;height:20px}
  #rv-usage input[type=range]::-moz-range-track{background:none}
  #rv-usage input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:14px;height:20px;border:0;
    background:linear-gradient(90deg,transparent 5px,currentColor 5px,currentColor 9px,transparent 9px)}
  #rv-usage input[type=range]::-moz-range-thumb{width:14px;height:20px;border:0;border-radius:0;
    background:linear-gradient(90deg,transparent 5px,currentColor 5px,currentColor 9px,transparent 9px)}
  #rv-usage input[type=range]:focus-visible{outline:2px solid #0b63ce;outline-offset:2px;border-radius:4px}
  #rv-usage .lvl{font-variant-numeric:tabular-nums}
  #rv-usage .dim{opacity:.65}</style>`);
  const when = t => {
    const d = new Date(t * 1000), soon = d - Date.now() < 20 * 3600e3;
    return soon ? d.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})
                : d.toLocaleString([], {weekday: "short", hour: "2-digit", minute: "2-digit"});
  };
  let dragging = false;   // a stop slider is being moved: don't redraw the row under it
  function usage() {
    if (dragging) return;
    fetch("/_review/usage").then(r => r.json()).then(u => {
      if (dragging) return;
      let el = document.getElementById("rv-usage");
      if (!el) { el = document.createElement("div"); el.id = "rv-usage"; document.querySelector(".meta").after(el); }
      if (u.error && !u.session) { el.innerHTML = '<span class="dim">Claude usage: unavailable (' + u.error.replace(/[&<>]/g, "") + ")</span>"; return; }
      const cls = (pct, stop) => pct >= stop ? "over" : pct >= 0.8 * stop ? "warn" : "";
      const meter = (name, label) => {
        const w = u[name]; if (!w) return "";
        const stop = u.stop[name];
        return `<span class="u ${cls(w.percent, stop)}" data-name="${name}" data-pct="${w.percent}"><b>${label}</b>
          <span class="bar"><span class="fill" style="width:${Math.min(w.percent, 100)}%"></span>
          <input type="range" min="1" max="100" step="1" value="${stop}" aria-label="${label} limit: pause new assistant runs at this percent"
            title="Drag: new assistant runs wait at this level until the ${label.toLowerCase()} limit resets"></span>
          ${Math.round(w.percent)}%<span class="dim">${w.resets ? " · resets " + when(w.resets) : ""} · pause at <span class="lvl">${stop}%</span></span></span>`;
      };
      el.innerHTML = "<span><b>Claude usage</b></span>" + meter("session", "5-hour") + meter("weekly", "Weekly") +
        (u.stale ? `<span class="dim" title="${u.error.replace(/[&<>"]/g, "")}">(last reading, ${when(u.checked)}; update refused)</span>` : "");
      el.querySelectorAll(".u").forEach(m => {
        const input = m.querySelector("input");
        input.addEventListener("pointerdown", () => { dragging = true; });
        ["pointerup", "pointercancel", "blur"].forEach(ev => input.addEventListener(ev, () => { dragging = false; }));
        input.addEventListener("input", () => {     // live: the label and the colour follow the marker
          m.querySelector(".lvl").textContent = input.value + "%";
          m.className = "u " + cls(+m.dataset.pct, +input.value);
        });
        input.addEventListener("change", () => {    // released (or a key press): save it
          dragging = false;
          fetch("/_review/usage_stop", {method: "POST", headers: {"Content-Type": "application/json", "X-Review": "1"},
            body: JSON.stringify({name: m.dataset.name, percent: +input.value})}).then(usage);
        });
      });
    }).catch(() => {});
  }
  usage();
  setInterval(usage, 60000);

  // CPU and memory of the machine serving this tree, and DirAI's own share (server + assistant runs)
  const gb = b => (b / 1073741824).toFixed(b >= 10 * 1073741824 ? 0 : 1) + " GB";
  const mb = b => b >= 1073741824 ? gb(b) : Math.round(b / 1048576) + " MB";
  function load() {
    fetch("/_review/load").then(r => r.json()).then(l => {
      let el = document.getElementById("rv-load");
      if (!el) { el = document.createElement("div"); el.id = "rv-load";
                 (document.getElementById("rv-usage") || document.querySelector(".meta")).after(el); }
      el.style.cssText = "display:flex;flex-wrap:wrap;gap:6px 18px;margin:.4rem 0;font:13px system-ui;align-items:center";
      if (l.error) { el.innerHTML = '<span style="opacity:.65">Server load: unavailable (' + l.error.replace(/[&<>]/g, "") + ")</span>"; return; }
      const memPct = 100 * l.mem_used / l.mem_total;
      const meter = (label, pct, text, title) => {
        const color = pct >= 90 ? "#c62828" : pct >= 70 ? "#b26b00" : "#2e7d32";
        return `<span style="display:flex;align-items:center;gap:6px" title="${title}"><b>${label}</b>
          <span style="position:relative;width:110px;height:8px;border-radius:4px;background:rgba(128,128,128,.25);overflow:hidden">
          <span style="position:absolute;left:0;top:0;bottom:0;width:${Math.min(pct, 100)}%;background:${color}"></span></span>${text}</span>`;
      };
      el.innerHTML = `<span><b>Server</b> ${l.host.replace(/[&<>]/g, "")}</span>` +
        meter("CPU", l.cpu_percent, Math.round(l.cpu_percent) + "%" +
              `<span style="opacity:.65"> of ${l.cpus} CPUs${l.load1 != null ? " · load " + l.load1 : ""}</span>`,
              "Whole machine, all users") +
        meter("Memory", memPct, `${gb(l.mem_used)} / ${gb(l.mem_total)}`, "Whole machine, all users") +
        `<span style="opacity:.65" title="This server and everything it started (assistant runs, list rebuilds); CPU in % of one CPU">DirAI: ${Math.round(l.dirai.cpu_percent)}% CPU · ${mb(l.dirai.rss)} · ${l.dirai.procs} processes</span>`;
    }).catch(() => {});
  }
  load();
  setInterval(load, 10000);

  // Tree-wide permission mode for the assistant's next runs (www/dirai.json "permissions")
  const MODES = {allowlist: ["Allow list", "Only allowed actions run; the rest are refused and listed in the page chat, to allow for the next run"],
                 ask: ["Ask in chat", "An action that isn't allowed waits for your Allow / Deny in the page chat, and the run carries on"]};
  function perms() {
    fetch("/_review/permissions").then(r => r.json()).then(p => {
      let el = document.getElementById("rv-perm");
      if (!el) { el = document.createElement("div"); el.id = "rv-perm";
                 (document.getElementById("rv-load") || document.getElementById("rv-usage") || document.querySelector(".meta")).after(el); }
      el.style.cssText = "display:flex;flex-wrap:wrap;gap:6px 10px;margin:.4rem 0;font:13px system-ui;align-items:center";
      el.innerHTML = "<b>Assistant permissions</b>" + p.modes.map(m =>
        `<button data-mode="${m}" title="${MODES[m][1]}" style="padding:2px 10px;border-radius:12px;cursor:pointer;font:13px system-ui;` +
        (m === p.mode ? "background:#0b63ce;color:#fff;border:1px solid #0b63ce" : "background:transparent;color:inherit;border:1px solid #999") +
        `">${MODES[m][0]}</button>`).join("") + '<span style="opacity:.65">applies from each page\'s next run</span>';
      el.querySelectorAll("button").forEach(b => b.onclick = () => fetch("/_review/permissions", {method: "POST",
        headers: {"Content-Type": "application/json", "X-Review": "1"}, body: JSON.stringify({mode: b.dataset.mode})}).then(perms));
    }).catch(() => {});
  }
  setTimeout(perms, 300);   // after the usage and load rows, so it lands below them
})();
