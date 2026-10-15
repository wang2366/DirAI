// Status badges for www/index.html, injected by html_server.py (owner only).
(function () {
  const css = `.rv-badge{display:inline-block;margin-left:8px;padding:1px 8px;border-radius:10px;font:600 11px system-ui;color:#fff;vertical-align:middle}
  .rv-working{background:#b26b00}.rv-queued{background:#7b1fa2}.rv-unread{background:#0b63ce}.rv-read{background:#2e7d32}.rv-closed{background:#666}
  #rv-summary{margin:.5rem 0;font:13px system-ui}
  .rv-ctx{display:inline-block;margin-left:6px;padding:1px 7px;border-radius:10px;font:600 11px system-ui;vertical-align:middle;
    border:1px solid currentColor}.rv-ctx.warn{color:#b26b00}.rv-ctx.high{color:#c62828}`;
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
        b.className = "rv-badge rv-" + st; b.textContent = LABEL[st] || st;
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
  #rv-usage .bar{position:relative;width:110px;height:8px;border-radius:4px;background:rgba(128,128,128,.25);overflow:hidden}
  #rv-usage .fill{position:absolute;left:0;top:0;bottom:0;background:#2e7d32}
  #rv-usage .warn .fill{background:#b26b00} #rv-usage .over .fill{background:#c62828}
  #rv-usage .stop{position:absolute;top:0;bottom:0;width:2px;background:currentColor;opacity:.6}
  #rv-usage .dim{opacity:.65}</style>`);
  const when = t => {
    const d = new Date(t * 1000), soon = d - Date.now() < 20 * 3600e3;
    return soon ? d.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})
                : d.toLocaleString([], {weekday: "short", hour: "2-digit", minute: "2-digit"});
  };
  function usage() {
    fetch("/_review/usage").then(r => r.json()).then(u => {
      let el = document.getElementById("rv-usage");
      if (!el) { el = document.createElement("div"); el.id = "rv-usage"; document.querySelector(".meta").after(el); }
      if (u.error && !u.session) { el.innerHTML = '<span class="dim">Claude usage: unavailable (' + u.error.replace(/[&<>]/g, "") + ")</span>"; return; }
      const meter = (name, label) => {
        const w = u[name]; if (!w) return "";
        const stop = u.stop[name], cls = w.percent >= stop ? "over" : w.percent >= 0.8 * stop ? "warn" : "";
        return `<span class="u ${cls}" title="new assistant runs wait at ${stop}% until this resets"><b>${label}</b>
          <span class="bar"><span class="fill" style="width:${Math.min(w.percent, 100)}%"></span><span class="stop" style="left:${stop}%"></span></span>
          ${Math.round(w.percent)}%<span class="dim">${w.resets ? " · resets " + when(w.resets) : ""}</span></span>`;
      };
      el.innerHTML = "<span><b>Claude usage</b></span>" + meter("session", "5-hour") + meter("weekly", "Weekly") +
        `<span class="dim">assistant pauses at ${u.stop.session}% / ${u.stop.weekly}%</span>` +
        (u.stale ? `<span class="dim" title="${u.error.replace(/[&<>"]/g, "")}">(last reading, ${when(u.checked)}; update refused)</span>` : "");
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
})();
