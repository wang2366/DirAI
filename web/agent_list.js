// Status badges for www/index.html, injected by server.py (owner only).
(function () {
  const css = `.rv-badge{display:inline-block;margin-left:8px;padding:1px 8px;border-radius:10px;font:600 11px system-ui;color:#fff;vertical-align:middle}
  .rv-working{background:#b26b00}.rv-queued{background:#7b1fa2}.rv-unread{background:#0b63ce}.rv-read{background:#2e7d32}.rv-closed{background:#666}.rv-asking{background:#c62828}
  .rv-tog{cursor:pointer}.rv-tog:hover{outline:2px solid #0003}
  .rv-rep{margin-left:6px;font:600 11px system-ui;opacity:.75;vertical-align:middle}
  #rv-summary{margin:.5rem 0;font:13px system-ui}
  .rv-ctx{display:inline-block;margin-left:6px;padding:1px 7px;border-radius:10px;font:600 11px system-ui;vertical-align:middle;
    border:1px solid currentColor}.rv-ctx.warn{color:#b26b00}.rv-ctx.high{color:#c62828}
  .rv-card{display:inline-block;margin-left:6px;padding:1px 7px;border-radius:10px;font:600 11px system-ui;vertical-align:middle;color:#c62828;border:1px solid currentColor}`;
  document.head.insertAdjacentHTML("beforeend", "<style>" + css + "</style>");
  const LABEL = {closed: "TaskDone"};   // shown name for a stored status
  const tbody = document.getElementById("rows");
  // ../a/b/index.html  ->  a/b
  const agentOf = tr => decodeURI(tr.querySelector("a").getAttribute("href")).replace(/^\.\.\//, "")
    .replace(/\/?index\.html$/, "");
  // One table for every agent. This server's rows are the ones agent_list.py wrote (data-agent); each shown
  // remote tree's rows are the same <tr>s taken from that tree's own list (data-tree too; see syncRemote),
  // so the columns, sorting, filter, badges and stars below are one code path for both.
  tbody.querySelectorAll("tr").forEach(tr => { tr.dataset.agent = agentOf(tr); tr.dataset.label = tr.querySelector("a").textContent; });
  const allRows = () => [...tbody.querySelectorAll("tr")];
  let localAll = {};          // this server's /_review/all
  const remoteRec = {};       // "tree id|dir" -> that agent's record in /_review/remotes (status, fav, …)
  const info = tr => (tr.dataset.tree ? remoteRec[tr.dataset.tree + "|" + tr.dataset.agent] : localAll[tr.dataset.agent]) || {};

  tbody.addEventListener("click", e => {
    const b = e.target.closest(".rv-tog"), tr = b && b.closest("tr");
    if (!tr) return;
    fetch("/_review/status", {method: "POST", headers: {"Content-Type": "application/json", "X-Review": "1"},
      body: JSON.stringify({agent: tr.dataset.agent, status: info(tr).status === "unread" ? "read" : "unread"})})
      .then(update).catch(() => {});
  });

  function update() {
    fetch("/_review/all").then(r => r.json()).then(all => { localAll = all; paint(); });
  }
  // the page's own sort (Modified, newest first, unless the owner chose another column), "needs you" rows pinned on top
  function arrange() { if (window.diraiResort) window.diraiResort(); }
  function paint() {
    const counts = {};
    allRows().forEach(tr => {
      const s = info(tr), st = s.status;
      if (s.asking || s.denied) tr.dataset.pin = "1"; else delete tr.dataset.pin;
      let b = tr.querySelector(".rv-badge");
      if (!st) { if (b) b.remove(); return; }
      if (!tr.classList.contains("rv-off")) counts[st] = (counts[st] || 0) + 1;
      if (!b) { b = document.createElement("span"); tr.querySelector("a").after(b); }
      const asking = s.asking || s.denied;   // its run waits for an answer, or refused actions wait for a decision, in the agent's chat
      b.className = "rv-badge rv-" + (asking ? "asking" : st); b.textContent = asking ? "needs you" : LABEL[st] || st;
      const inbox = s.inbox;   // messages waiting for its run to end
      if (inbox) b.textContent += " +" + inbox, b.title = inbox + " queued message" + (inbox === 1 ? "" : "s") + " waiting for this agent";
      else b.removeAttribute("title");
      // unread / read badges of this server's rows switch on a click (a remote tree's status can't be set through Machines)
      const tog = !asking && !tr.dataset.tree && (st === "unread" || st === "read");
      b.classList.toggle("rv-tog", tog);
      if (tog && !b.title) b.title = "click: mark read / unread";
      if (s.denied && !s.asking) b.title = s.denied + " refused action" + (s.denied === 1 ? "" : "s") + " to review" + (b.title ? "; " + b.title : "");
      // its own soonest scheduled message (agents.all_status; paused ones don't count)
      const next = s.schedule, nsched = s.schedules || 0;
      let r = tr.querySelector(".rv-rep");
      if (next) {
        if (!r) { r = document.createElement("span"); r.className = "rv-rep"; b.after(r); }
        r.textContent = "⏰ " + next;
        r.title = "This agent's next scheduled message (" + nsched + " scheduled; see its panel)";
      } else if (r) r.remove();
      // the agent's summary card is missing or incomplete (agents that have run)
      const card = s.card;
      let k = tr.querySelector(".rv-card");
      if (card) {
        if (!k) { k = document.createElement("span"); k.className = "rv-card"; b.after(k); }
        k.textContent = "card ✗";
        k.title = "This agent's summary card is missing or incomplete; open the agent to see what";
      } else if (k) k.remove();
      // big session context: suggest Compact (warn/high levels match agents.py)
      const ctx = s.context;
      let c = tr.querySelector(".rv-ctx");
      if (ctx >= 150000) {
        if (!c) { c = document.createElement("span"); b.after(c); }
        c.className = "rv-ctx " + (ctx >= 300000 ? "high" : "warn");
        c.textContent = Math.round(ctx / 1000) + "K context";
        c.title = "This agent's session resends this many tokens with every message; open it and press Compact";
      } else if (c) c.remove();
    });
    arrange();
    changed();
    let s = document.getElementById("rv-summary");
    if (!s) { s = document.createElement("div"); s.id = "rv-summary"; document.querySelector(".meta").after(s); }
    s.textContent = "Agents: " + (["unread", "working", "queued", "read", "closed"]
      .filter(k => counts[k]).map(k => counts[k] + " " + (LABEL[k] || k)).join(" · ") || "none yet");
  }
  update();
  setInterval(update, 5000);

  // Favorites: a star on each row (saved in www/favorites.json) and Favorites / All tabs above the filter
  document.head.insertAdjacentHTML("beforeend", `<style>
  #rv-tabs{display:flex;gap:4px;margin:1rem 0 -.5rem;border-bottom:1px solid var(--line,#e5e5ea)}
  #rv-tabs button{padding:6px 14px;border:0;border-bottom:2px solid transparent;margin-bottom:-1px;background:none;
    color:inherit;font:600 14px system-ui;cursor:pointer;opacity:.65}
  #rv-tabs button.on{border-bottom-color:#0b63ce;opacity:1}
  .rv-star{border:0;background:none;padding:0 6px 0 0;font-size:16px;line-height:1;cursor:pointer;color:#999;vertical-align:baseline}
  .rv-star.on{color:#e0a800} .rv-star:hover{color:#e0a800}
  #rows.rv-favonly tr:not(.rv-fav),#rows tr.rv-off{display:none}
  #rv-nofav{display:none;padding:1rem .5rem;color:var(--muted,#6e6e73);font:14px system-ui}</style>`);
  let favs = new Set();
  // from the Machines section (below): whether this server's own agents are unticked
  let localHidden = false;
  const tabs = document.createElement("div");
  tabs.id = "rv-tabs";
  tabs.innerHTML = '<button data-tab="fav">★ Favorites</button><button data-tab="all">All</button>';
  document.getElementById("q").before(tabs);
  tbody.closest("table").insertAdjacentHTML("afterend",
    '<div id="rv-nofav">No favorites yet: click the ☆ beside an agent to add it.</div>');
  const nofav = document.getElementById("rv-nofav");
  // Favorites and All are this table, filtered; any other tab is a view another script adds (addView, below,
  // used by agent_tree.js): it replaces the table while its tab is on
  const views = {};
  const onChange = [];        // called after the rows or their statuses changed
  const changed = () => onChange.forEach(f => f());
  let tab = "fav";
  try { tab = localStorage.getItem("dirai-agent-tab") || "fav"; } catch (e) {}
  // a remote tree's agent is starred in that tree's own list (its favorites.json), this server's in ours
  const isFav = tr => tr.dataset.tree ? !!info(tr).fav : favs.has(tr.dataset.agent);
  function star(tr) {
    const on = !tr.classList.contains("rv-fav");
    if (tr.dataset.tree) {
      info(tr).fav = on; drawFavs();
      return remoteAct({op: "call", tree: tr.dataset.tree, path: "favorite", data: {agent: tr.dataset.agent, on}});
    }
    fetch("/_review/favorite", {method: "POST", headers: {"Content-Type": "application/json", "X-Review": "1"},
        body: JSON.stringify({agent: tr.dataset.agent, on})})
      .then(r => r.json()).then(res => { if (res.favorites) { favs = new Set(res.favorites); drawFavs(); } })
      .catch(() => {});
  }
  function drawFavs() {
    tbody.classList.toggle("rv-favonly", tab === "fav");
    tbody.closest("table").hidden = !!views[tab];
    tabs.querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.tab === tab));
    Object.keys(views).forEach(k => views[k](k === tab));
    let n = 0, nAll = 0;
    allRows().forEach(tr => {
      const on = isFav(tr);
      if (!tr.classList.contains("rv-off")) { nAll++; n += on; }
      tr.classList.toggle("rv-fav", on);
      let s = tr.querySelector(".rv-star");
      if (!s) {
        s = document.createElement("button");
        s.className = "rv-star";
        s.onclick = () => star(tr);
        tr.querySelector("a").before(s);
      }
      s.classList.toggle("on", on);
      s.textContent = on ? "★" : "☆";
      s.title = on ? "Remove from favorites" : "Add to favorites";
    });
    tabs.querySelector('[data-tab="all"]').textContent = "All (" + nAll + ")";
    tabs.querySelector('[data-tab="fav"]').textContent = "★ Favorites (" + n + ")";
    nofav.style.display = tab === "fav" && !n ? "block" : "none";
    changed();
  }
  const pickTab = b => b.onclick = () => {
    tab = b.dataset.tab;
    try { localStorage.setItem("dirai-agent-tab", tab); } catch (e) {}
    drawFavs();
  };
  tabs.querySelectorAll("button").forEach(pickTab);
  drawFavs();
  fetch("/_review/favorites").then(r => r.json()).then(f => { favs = new Set(f); drawFavs(); }).catch(() => {});

  // Claude plan usage (owner only), with the % at which new agent runs are held back
  document.head.insertAdjacentHTML("beforeend", `<style>
  .rv-usage{display:flex;flex-wrap:wrap;gap:6px 18px;margin:.4rem 0;font:13px system-ui;align-items:center}
  .rv-usage .u{display:flex;align-items:center;gap:6px}
  .rv-usage .bar{position:relative;width:140px;height:8px;border-radius:4px;background:rgba(128,128,128,.25)}
  .rv-usage .fill{position:absolute;left:0;top:0;bottom:0;border-radius:4px;background:#2e7d32}
  .rv-usage .warn .fill{background:#b26b00} .rv-usage .over .fill{background:#c62828}
  /* the stop level: a range input laid over the bar, its thumb a marker you drag */
  .rv-usage input[type=range]{position:absolute;left:-7px;width:calc(100% + 14px);top:-6px;height:20px;margin:0;padding:0;border:0;box-sizing:border-box;
    background:none;-webkit-appearance:none;appearance:none;cursor:ew-resize}
  .rv-usage input[type=range]::-webkit-slider-runnable-track{background:none;height:20px}
  .rv-usage input[type=range]::-moz-range-track{background:none}
  .rv-usage input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:14px;height:20px;border:0;
    background:linear-gradient(90deg,transparent 5px,currentColor 5px,currentColor 9px,transparent 9px)}
  .rv-usage input[type=range]::-moz-range-thumb{width:14px;height:20px;border:0;border-radius:0;
    background:linear-gradient(90deg,transparent 5px,currentColor 5px,currentColor 9px,transparent 9px)}
  .rv-usage input[type=range]:focus-visible{outline:2px solid #0b63ce;outline-offset:2px;border-radius:4px}
  .rv-usage .lvl{font-variant-numeric:tabular-nums}
  .rv-usage .auto{padding:0 8px;border-radius:10px;cursor:pointer;font:600 11px system-ui;border:1px solid #888;background:none;color:inherit}
  .rv-usage .auto.on{background:#0b63ce;border-color:#0b63ce;color:#fff}
  .rv-usage .dim{opacity:.65} .rv-usage .short{display:none}
  .rv-usage .eng{padding:1px 10px;border-radius:11px;cursor:pointer;font:600 12px system-ui;border:1px solid;color:#fff}
  .rv-usage .eng.claude{background:#2f9e5b;border-color:#2f9e5b} .rv-usage .eng.codex{background:#2a6fdb;border-color:#2a6fdb}
  .rv-usage .trend{padding:0 8px;border-radius:10px;cursor:pointer;font:600 11px system-ui;border:1px solid #888;background:none;color:inherit}
  .rv-trend{flex-basis:100%;display:none;gap:4px 18px;flex-wrap:wrap;font:11px system-ui}
  .rv-trend.open{display:flex} .rv-trend svg{width:340px;height:86px;overflow:visible}
  .rv-trend .ln{fill:none;stroke:#2a6fdb;stroke-width:2} .rv-trend .pz{fill:none;stroke:#c62828;stroke-dasharray:5 4}
  .rv-trend .pr{stroke:#2a6fdb;stroke-dasharray:3 3} .rv-trend .bx{fill:none;stroke:rgba(128,128,128,.6)}</style>`);
  const when = (t, brief) => {
    const d = new Date(t * 1000), soon = d - Date.now() < 20 * 3600e3;
    return soon ? d.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})
         : brief ? d.toLocaleString([], {weekday: "short", hour: "numeric"})        // "Thu 9 PM": the Machines box's short line
                 : d.toLocaleString([], {weekday: "short", hour: "2-digit", minute: "2-digit"});
  };
  // small line charts of the two windows (history in ~/.config/dirai/usage_history.jsonl), with the pause level and a projection
  function trend(box, u, io) {
    io.history().then(h => {
      const W = 300, H = 56, now = Date.now() / 1000;
      const chart = (key, rkey, label, len, pause) => {
        const w = u[key]; if (!w || !w.resets) return "";
        const v = key[0], t0 = w.resets - len;
        const x = t => 20 + W * Math.min(1, Math.max(0, (t - t0) / len)), y = p => 14 + H - H * Math.min(p, 100) / 100;
        const mine = h.samples.filter(r => r.t >= t0 && r[v] != null && Math.abs(r[rkey] - w.resets) < 300);   // the reset time jitters by a second or so
        // no samples yet: still draw the chart, with just the current reading
        const note = mine.length ? "" : " · no history yet (a sample is kept each time the value changes)";
        // projection: the slope over the last 6 hours (the last hour for the 5-hour window), carried to the reset
        const span = key === "session" ? 3600 : 6 * 3600, recent = mine.filter(r => r.t >= now - span);
        let said = `now ${Math.round(w.percent)}%${note}`, proj = "";
        if (recent.length > 1) {
          const rate = (w.percent - recent[0][v]) / Math.max(1, now - recent[0].t);
          if (rate > 0) {
            const hit = now + (100 - w.percent) / rate, end = Math.min(100, w.percent + rate * (w.resets - now));
            proj = `<line class="pr" x1="${x(now)}" y1="${y(w.percent)}" x2="${x(Math.min(hit, w.resets))}" y2="${y(end)}"/>`;
            said += hit < w.resets ? ` · at this pace 100% ${when(hit)} (${Math.round((w.resets - hit) / 3600)} h early)`
                                   : ` · at this pace ${Math.round(end)}% at reset`;
          } else said += " · flat at the recent pace";
        }
        return `<svg viewBox="0 0 340 ${H + 30}"><text x="20" y="9" font-weight="bold" fill="currentColor">${label}</text>
          <rect class="bx" x="20" y="14" width="${W}" height="${H}"/>${pause}
          <polyline class="ln" points="${mine.map(r => x(r.t) + "," + y(r[v])).join(" ")} ${x(now)},${y(w.percent)}"/>${proj}
          <circle cx="${x(now)}" cy="${y(w.percent)}" r="3" fill="#2a6fdb"/>
          <text x="20" y="${H + 28}" fill="currentColor">${said}</text></svg>`;
      };
      const st = u.stop;
      let wp = `<path class="pz" d="M20,${y0(st.weekly)} h${W}"/>`;   // by hand: flat; Auto: n/7 on day n
      if (st.weekly_auto) {
        const d = [];
        for (let n = 1; n <= 7; n++) d.push(`${n === 1 ? "M" : "L"}${20 + W * (n - 1) / 7},${y0(100 * n / 7)} L${20 + W * n / 7},${y0(100 * n / 7)}`);
        wp = `<path class="pz" d="${d.join(" ")}"/>`;
      }
      function y0(p) { return 14 + H - H * Math.min(p, 100) / 100; }
      box.innerHTML = chart("session", "sr", "5-hour window", 5 * 3600, `<path class="pz" d="M20,${y0(st.session)} h${W}"/>`) +
                      chart("weekly", "wr", "Weekly window", 7 * 86400, wp) +
                      '<span class="dim" style="flex-basis:100%">line: usage · dashed red: pause level · dotted: projection at the recent pace</span>';
    }).catch(e => { box.innerHTML = '<span class="dim">Chart unavailable: ' + String(e && e.message || e).replace(/[&<>]/g, "") + "</span>"; });
  }
  let dragging = false;   // a stop slider is being moved: don't redraw the row under it
  // a pause level just saved by a slider: the next reading may still carry the old one (a remote machine's
  // comes through the Machines poll, seconds later), and a redraw from it made the marker jump back (100 -> 88
  // -> 100 -> 88). Until a reading shows the saved level (30 s at most), the widget is drawn with it.
  // io.key ("" this server, else the tree id) -> {name, percent, at}
  const held = {};
  function heldPatch(key, u) {
    const b = held[key];
    if (!b || !u || Date.now() - b.at > 30000) { delete held[key]; return u; }
    const cx = u.engine === "codex", stop = (cx ? u.codex && u.codex.stop : u.stop) || {};
    if (Math.round(stop[b.name] ?? 100) === b.percent) { delete held[key]; return u; }
    const v = JSON.parse(JSON.stringify(u));
    if (cx) v.codex.stop = Object.assign({}, v.codex.stop, {[b.name]: b.percent});
    else { v.stop[b.name] = b.percent; if (b.name === "weekly") v.stop.weekly_auto = null; }   // a dragged weekly level turns Auto off
    return v;
  }
  const hold = (key, body) => { if (body.name) held[key] = {name: body.name, percent: Math.round(body.percent), at: Date.now()}; };
  // One machine's usage widget, drawn into el: the 5-hour and weekly bars with resets, the pause-level
  // sliders, Auto and Chart. u: that machine's /_review/usage. io: how to reach its server,
  //   {key: for the chart's open state, save(body): Promise of /_review/usage_stop's answer,
  //    history(): Promise of /_review/usage_history, after(): redraw once saved}
  // This server's widget talks to /_review/* (localIO); a remote machine's goes through op "call" (remoteIO).
  // The widget's title is the machine's engine switch (codex_engine.py): "Claude usage ⇄" / "Codex usage ⇄".
  // Only the owner's click changes it; the machine's queue (held messages too) then goes to the other engine.
  // Shown only when the server reports an engine and Codex is installed there (or already in use).
  const ENG_TIP = {claude: "This machine's agents run on Claude Code. Click to switch them all to Codex: held and new messages go to Codex from now on.",
                   codex: "This machine's agents run on Codex. Click to switch them all back to Claude Code: held and new messages go to Claude from now on."};
  const engChip = (u, cur) => u.engine && (cur === "codex" || (u.codex && u.codex.installed))
    ? `<button class="eng ${cur}" title="${ENG_TIP[cur]}">${cur === "codex" ? "Codex" : "Claude"} usage ⇄</button>`
    : `<b>${cur === "codex" ? "Codex" : "Claude"} usage</b>`;
  // a message under the widget, in page text (selectable), or none
  function usageNote(el, msg) {
    let n = el.nextElementSibling && el.nextElementSibling.classList.contains("rv-stopnote") ? el.nextElementSibling : null;
    if (!msg) { if (n) n.remove(); return; }
    if (!n) { n = document.createElement("div"); n.className = "rv-stopnote"; el.after(n); }
    n.style.cssText = "margin:.2rem 0;padding:4px 8px;border-radius:6px;background:#ffe0e0;color:#1d1d1f;font:13px system-ui";
    n.textContent = msg;
  }
  function wireEngine(el, u, io) {
    const b = el.querySelector(".eng");
    if (!b || !io.engine) return;
    b.onclick = () => {
      const to = u.engine === "codex" ? "claude" : "codex";
      b.disabled = true;
      io.engine(to).then(res => {
        b.disabled = false;
        if (res.error) return usageNote(el, res.error === "old"
          ? "Not switched: that server is still running older DirAI code. Restart it (or Update its machine), then try again."
          : "Not switched: " + res.error);
        usageNote(el, null);
        io.after();
      }).catch(() => { b.disabled = false; });
    };
  }
  // The machine on Codex: one bar per limit window Codex reported in its last run (the windows depend on
  // the plan: Free one 30-day window, Plus 5-hour and weekly...), each with its pause slider.
  function codexWidget(el, u, io) {
    const c = u.codex || {}, ws = c.windows || [], stops = c.stop || {};
    const cls = (pct, stop) => pct >= stop ? "over" : pct >= 0.8 * stop ? "warn" : "";
    const meter = w => {
      const stop = w.name in stops ? stops[w.name] : 100, label = String(w.label).replace(/[&<>"]/g, "");
      return `<span class="u ${cls(w.percent, stop)}" data-name="${w.name}" data-pct="${w.percent}"><b>${label}</b>
        <span class="bar"><span class="fill" style="width:${Math.min(w.percent, 100)}%"></span>
        <input type="range" min="1" max="100" step="1" value="${Math.round(stop)}" aria-label="${label} limit: pause new agent runs at this percent"
          title="Drag: new agent runs wait at this level until the ${label.toLowerCase()} limit resets"></span>
        ${Math.round(w.percent)}%<span class="dim">${w.resets ? ` · <span class="long">resets ${when(w.resets)}</span><span class="short">${when(w.resets, true)}</span>` : ""
          } · pause<span class="long"> at</span> <span class="lvl">${Math.round(stop)}%</span></span></span>`;
    };
    const esc = s => String(s).replace(/[&<>"]/g, "");
    const about = [c.plan ? "plan: " + esc(c.plan) : "", c.model ? esc(c.model) : "",
                   c.checked ? "as of the last Codex run, " + when(c.checked) : ""].filter(Boolean).join(" · ");
    el.innerHTML = `<span>${engChip(u, "codex")}${about ? ` <span class="dim">${about}</span>` : ""}</span>` +
      (c.error ? `<span class="dim">Codex usage: unavailable (${esc(c.error)})</span>`
       : ws.length ? ws.map(meter).join("")
       : '<span class="dim">no reading yet: Codex reports its limits in its session log, shown after the first Codex run</span>') +
      (c.credits && c.credits.has_credits ? '<span class="dim">this plan has credits: past the limit Codex may spend them; the pause level stops runs first</span>' : "") +
      (c.logged_in === false ? '<span class="dim">Codex isn\'t signed in here: run `codex login` in a terminal</span>' : "");
    wireEngine(el, u, io);
    const save = body => io.save(body).then(res => {
      if (!res.error) { usageNote(el, null); hold(io.key, body); return io.after(); }
      usageNote(el, res.error === "old" ? "Not saved: that server is still running older DirAI code. Restart it (or Update its machine), then try again."
                                       : "Not saved: " + res.error);
    }).catch(() => {});
    el.querySelectorAll(".u").forEach(m => {
      const input = m.querySelector("input");
      if (!input) return;
      input.addEventListener("pointerdown", () => { dragging = true; });
      ["pointerup", "pointercancel", "blur"].forEach(ev => input.addEventListener(ev, () => { dragging = false; }));
      input.addEventListener("input", () => {
        m.querySelector(".lvl").textContent = input.value + "%";
        m.className = "u " + cls(+m.dataset.pct, +input.value);
      });
      input.addEventListener("change", () => { dragging = false; save({name: m.dataset.name, percent: +input.value}); });
    });
  }
  function usageWidget(el, u, io) {
    el.classList.add("rv-usage");
    if (!u) { el.innerHTML = ""; return; }      // a server too old to report it
    u = heldPatch(io.key, u);
    if (u.engine === "codex") return codexWidget(el, u, io);
    if (u.error && !u.session) {
      el.innerHTML = engChip(u, "claude") + ' <span class="dim">Claude usage: unavailable (' + u.error.replace(/[&<>]/g, "") + ")</span>";
      return wireEngine(el, u, io);
    }
    const cls = (pct, stop) => pct >= stop ? "over" : pct >= 0.8 * stop ? "warn" : "";
    const auto = u.stop.weekly_auto;   // weekly level follows the day of the week: n/7 on day n
    const meter = (name, label) => {
      const w = u[name]; if (!w) return "";
      const stop = u.stop[name], paced = name === "weekly" && auto;
      // an old reading whose window has reset since: its % says nothing about now
      if (u.stale && w.resets && w.resets * 1000 < Date.now())
        return `<span class="u" data-name="${name}"><b>${label}</b> <span class="dim">unknown: reset since the last reading</span></span>`;
      // the text after the %: in full outside the Machines box; inside it (a narrow column) the .long parts are
      // hidden and .short shown, so each window fits one line, and the full text is the tooltip
      const day = paced && auto.day ? ` (day ${auto.day} of 7${auto.day < 7 ? ", " + Math.round(100 * (auto.day + 1) / 7) + "% from " + when(auto.until) : ""})` : "";
      const full = (w.resets ? "resets " + when(w.resets) + " · " : "") + "pause at " + Math.round(stop) + "%" + day;
      return `<span class="u ${cls(w.percent, stop)}" data-name="${name}" data-pct="${w.percent}"><b>${label}</b>
        <span class="bar"><span class="fill" style="width:${Math.min(w.percent, 100)}%"></span>
        <input type="range" min="1" max="100" step="1" value="${Math.round(stop)}" aria-label="${label} limit: pause new agent runs at this percent"
          title="Drag: new agent runs wait at this level until the ${label.toLowerCase()} limit resets"></span>
        ${Math.round(w.percent)}%<span class="dim" title="${full}">${w.resets ? ` · <span class="long">resets ${when(w.resets)}</span><span class="short">${when(w.resets, true)}</span>` : ""
          } · pause<span class="long"> at</span> <span class="lvl">${Math.round(stop)}%</span><span class="long">${day}</span></span></span>`;
    };
    const okey = "rv-trend:" + io.key, open = sessionStorage.getItem(okey) === "1";
    // Auto (the weekly pause level) sits next to Chart by the title; not shown when the weekly window is unknown
    const wk = u.weekly, autoBtn = !wk || (u.stale && wk.resets && wk.resets * 1000 < Date.now()) ? "" :
      ` <button class="auto${auto ? " on" : ""}" title="Weekly pause level. ${auto ? "On: it rises by a seventh each day of the week (day n: n/7 of the limit), so the week's usage is spread out. Click to set it by hand instead."
        : "Off: it is set by hand. Click to let it follow the day of the week (day n: n/7 of the limit)."}">Auto</button>`;
    // Chart and Auto sit by the title, so in the Machines box (a column) they share one line
    el.innerHTML = `<span>${engChip(u, "claude")} <button class="trend" title="Show or hide the usage over the current windows, with the pause level and a projection">${open ? "Hide chart" : "Chart"}</button>${autoBtn}</span>` +
      meter("session", "5-hour") + meter("weekly", "Weekly") +
      `<div class="rv-trend${open ? " open" : ""}"></div>` +
      (u.stale ? `<span class="dim">(old reading: ${String(u.error).replace(/^\w+Error: /, "").replace(/[&<>"]/g, "")})</span>` : "");
    const save = body => io.save(body).then(res => {
        let n = el.nextElementSibling && el.nextElementSibling.classList.contains("rv-stopnote") ? el.nextElementSibling : null;
        if (!res.error) { if (n) n.remove(); hold(io.key, body); return io.after(); }
        if (!n) { n = document.createElement("div"); n.className = "rv-stopnote"; el.after(n); }
        n.style.cssText = "margin:.2rem 0;padding:4px 8px;border-radius:6px;background:#ffe0e0;color:#1d1d1f;font:13px system-ui";
        n.textContent = res.error === "old"
          ? "Not saved: that server is still running older DirAI code. Restart it (or Update its machine), then try again."
          : "Not saved: " + res.error;
      }).catch(() => {});
    const box = el.querySelector(".rv-trend"), tb = el.querySelector(".trend");
    if (open) trend(box, u, io);
    tb.onclick = () => {
      const on = !box.classList.contains("open");
      box.classList.toggle("open", on); tb.textContent = on ? "Hide chart" : "Chart";
      sessionStorage.setItem(okey, on ? "1" : "0");
      if (on) trend(box, u, io);
    };
    const btn = el.querySelector(".auto");
    if (btn) btn.onclick = () => save({auto: !auto});
    wireEngine(el, u, io);
    el.querySelectorAll(".u").forEach(m => {
      const input = m.querySelector("input");
      if (!input) return;      // a window shown as unknown has no slider
      input.addEventListener("pointerdown", () => { dragging = true; });
      ["pointerup", "pointercancel", "blur"].forEach(ev => input.addEventListener(ev, () => { dragging = false; }));
      input.addEventListener("input", () => {     // live: the label and the colour follow the marker
        m.querySelector(".lvl").textContent = input.value + "%";
        m.className = "u " + cls(+m.dataset.pct, +input.value);
      });
      input.addEventListener("change", () => {    // released (or a key press): save it (weekly: turns Auto off)
        dragging = false;
        save({name: m.dataset.name, percent: +input.value});
      });
    });
  }
  const POSTJ = body => ({method: "POST", headers: {"Content-Type": "application/json", "X-Review": "1"}, body: JSON.stringify(body)});
  const localIO = {key: "",
    save: body => fetch("/_review/usage_stop", POSTJ(body)).then(r => r.ok ? r.json() : {error: r.status === 404 ? "old" : "HTTP " + r.status}),
    engine: to => fetch("/_review/engine", POSTJ({engine: to})).then(r => r.ok ? r.json() : {error: r.status === 404 ? "old" : "HTTP " + r.status}),
    history: () => fetch("/_review/usage_history").then(r => r.ok ? r.json() : Promise.reject(r.status === 404
        ? "this tree's server is still running the old DirAI code. Run \"DirAI restart\" in the tree, then reload." : "HTTP " + r.status)),
    after: () => usage()};
  // a remote tree's server, through this one (op "call", relayed hop by hop); its history kept a minute,
  // as the Machines map redraws every 10 s
  const histCache = {};
  const callTree = (t, path, data) => fetch("/_review/remotes", POSTJ({op: "call", tree: t.id, path, data}))
    .then(r => r.json()).then(res => res.error && /unknown action|not callable/.test(res.error) ? {error: "old"} : res);
  const remoteIO = t => ({key: t.id,
    save: body => callTree(t, "usage_stop", body),
    engine: to => callTree(t, "engine", {engine: to}),
    history: () => {
      const c = histCache[t.id];
      if (c && Date.now() - c.at < 60000) return Promise.resolve(c.h);
      return callTree(t, "usage_history").then(h => h.error ? Promise.reject(h.error === "old"
        ? "that server runs older DirAI code: Update its machine" : h.error) : (histCache[t.id] = {at: Date.now(), h}).h);
    },
    after: () => machines()});
  function usage() {
    if (dragging) return;
    fetch("/_review/usage").then(r => r.json()).then(u => {
      if (dragging) return;
      let el = document.getElementById("rv-usage");
      if (!el) {
        el = document.createElement("div"); el.id = "rv-usage";
        const slot = document.querySelector("#rv-machines .uslot");     // this server's box, when Machines is shown
        if (slot) { slot.innerHTML = ""; slot.appendChild(el); } else document.querySelector(".meta").after(el);
      }
      usageWidget(el, u, localIO);
    }).catch(() => {});
  }
  usage();
  setInterval(usage, 60000);
  // the rows under the title go after the usage and load rows while they are there, else after .meta
  // (the Machines section moves those two into this server's box)
  function headAnchor() {
    const out = ["rv-load", "rv-usage"].map(id => document.getElementById(id)).find(e => e && !e.closest("#rv-machines"));
    return out || document.querySelector(".meta");
  }

  // CPU and memory of a node serving a tree, and DirAI's own share there (server + agent runs): one widget,
  // this server's (localLoad, every 10 s) and each remote node's (in the Machines boxes, from its polls)
  document.head.insertAdjacentHTML("beforeend", `<style>
  .rv-load{display:flex;flex-wrap:wrap;gap:6px 18px;margin:.4rem 0;font:13px system-ui;align-items:center}
  .rv-load .m{display:flex;align-items:center;gap:6px} .rv-load .dim{opacity:.65}
  .rv-load .bar{position:relative;width:110px;height:8px;border-radius:4px;background:rgba(128,128,128,.25);overflow:hidden}
  .rv-load .fill{position:absolute;left:0;top:0;bottom:0}</style>`);
  const gb = b => (b / 1073741824).toFixed(b >= 10 * 1073741824 ? 0 : 1) + " GB";
  const mb = b => b >= 1073741824 ? gb(b) : Math.round(b / 1048576) + " MB";
  function loadWidget(el, l) {
    el.classList.add("rv-load");
    if (!l) { el.innerHTML = ""; return; }       // a server too old to report it
    if (l.error) { el.innerHTML = '<span class="dim">Server load: unavailable (' + String(l.error).replace(/[&<>]/g, "") + ")</span>"; return; }
    const memPct = 100 * l.mem_used / l.mem_total;
    const meter = (label, pct, text, title) => {
      const color = pct >= 90 ? "#c62828" : pct >= 70 ? "#b26b00" : "#2e7d32";
      return `<span class="m" title="${title}"><b>${label}</b><span class="bar"><span class="fill" style="width:${Math.min(pct, 100)}%;background:${color}"></span></span>${text}</span>`;
    };
    el.innerHTML = `<span><b>Server</b> ${String(l.host).replace(/[&<>]/g, "")}</span>` +
      meter("CPU", l.cpu_percent, Math.round(l.cpu_percent) + "%" +
            `<span class="dim"> of ${l.cpus} CPUs${l.load1 != null ? " · load " + l.load1 : ""}</span>`,
            "Whole machine, all users") +
      meter("Memory", memPct, `${gb(l.mem_used)} / ${gb(l.mem_total)}`, "Whole machine, all users") +
      `<span class="dim" title="This server and everything it started (agent runs, list rebuilds); CPU in % of one CPU">DirAI: ${Math.round(l.dirai.cpu_percent)}% CPU · ${mb(l.dirai.rss)} · ${l.dirai.procs} processes</span>`;
  }
  function load() {
    fetch("/_review/load").then(r => r.json()).then(l => {
      let el = document.getElementById("rv-load");
      if (!el) {
        el = document.createElement("div"); el.id = "rv-load";
        const slot = document.querySelector("#rv-machines .lslot");     // this server's box, when Machines is shown
        if (slot) slot.appendChild(el); else headAnchor().after(el);
      }
      loadWidget(el, l);
    }).catch(() => {});
  }
  // U11 (owner, 2026-11-09): the load widget (Server <host>, CPU, Memory, DirAI's share) is no longer shown,
  // here nor in the Machines boxes (lSlots); set SHOW_LOAD to true to bring it back. /_review/load stays.
  const SHOW_LOAD = false;
  if (SHOW_LOAD) { load(); setInterval(load, 10000); }

  // Tree-wide permission mode for the agents' next runs (www/dirai.json "permissions")
  const MODES = {allowlist: ["Allow list", "Only allowed actions run; the rest are refused and listed in the agent's chat, to allow for the next run"],
                 ask: ["Ask in chat", "An action that isn't allowed waits for your Allow / Deny in the agent's chat, and the run carries on"]};
  function perms() {
    fetch("/_review/permissions").then(r => r.json()).then(p => {
      let el = document.getElementById("rv-perm");
      if (!el) { el = document.createElement("div"); el.id = "rv-perm";
                 headAnchor().after(el); }
      el.style.cssText = "display:flex;flex-wrap:wrap;gap:6px 10px;margin:.4rem 0;font:13px system-ui;align-items:center";
      el.innerHTML = "<b>Agent permissions</b>" + p.modes.map(m =>
        `<button data-mode="${m}" title="${MODES[m][1]}" style="padding:2px 10px;border-radius:12px;cursor:pointer;font:13px system-ui;` +
        (m === p.mode ? "background:#0b63ce;color:#fff;border:1px solid #0b63ce" : "background:transparent;color:inherit;border:1px solid #999") +
        `">${MODES[m][0]}</button>`).join("") + '<span style="opacity:.65">applies from each agent\'s next run</span>';
      el.querySelectorAll("button").forEach(b => b.onclick = () => fetch("/_review/permissions", {method: "POST",
        headers: {"Content-Type": "application/json", "X-Review": "1"}, body: JSON.stringify({mode: b.dataset.mode})}).then(perms));
    }).catch(() => {});
  }
  setTimeout(perms, 300);   // after the usage and load rows, so it lands below them

  // Machines: the DirAI servers on machines from this machine's ~/.ssh/config, and through them their
  // own downstream machines (lib/remotes.py). Each tree is a node with its state, show toggle and
  // action; its agents are listed below the table, named machine:tree/folder.
  document.head.insertAdjacentHTML("beforeend", `<style>
  #rv-machines{margin:1rem 0 .5rem;font:13px system-ui} #rv-machines>summary{cursor:pointer;font-weight:600}
  #rv-machines .mrow{display:flex;gap:56px;margin:.5rem 0;align-items:flex-start;position:relative;overflow-x:auto;overflow-y:hidden}
  #rv-machines .mcol{display:flex;flex-direction:column;gap:14px;flex:0 1 300px;min-width:190px}
  #rv-machines div.mcol:first-of-type{flex-basis:330px}   /* this server's column: room for a usage window on one line (svg.arrows comes first) */
  #rv-machines .tnode b{word-break:break-all}
  #rv-machines .mach>.dim,#rv-machines .mbody>.dim{overflow-wrap:anywhere}
  #rv-machines .mbody>summary{list-style:none;cursor:pointer} #rv-machines .mbody>summary::-webkit-details-marker{display:none}
  #rv-machines .mbody>summary h4::before{content:"▸ ";opacity:.6} #rv-machines .mbody[open]>summary h4::before{content:"▾ "}
  #rv-machines .mbody .fold{font-size:12px} #rv-machines .mbody[open] .fold{display:none}
  #rv-machines .arrows{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;overflow:visible}
  #rv-machines .mach{position:relative;z-index:1;background:var(--bg,#fff)}
  #rv-machines .mach{border:1px solid #888;border-radius:8px;padding:6px 8px;min-width:190px}
  #rv-machines .mach.down{border-color:#c62828} #rv-machines .mach h4{margin:0 0 4px;font-size:13px}
  #rv-machines .tnode{border:1px solid #2e7d32;border-radius:6px;padding:4px 6px;margin:4px 0;position:relative}
  #rv-machines .tnode.off{border-style:dashed;border-color:#888} #rv-machines .tnode.bad{border-color:#c62828}
  #rv-machines .tnode.hid{opacity:.5} #rv-machines .tnode input{float:right;width:auto;margin:2px 0 4px 6px;padding:0}
  #rv-machines .st-alive{color:#2e7d32} #rv-machines .st-bad{color:#c62828} #rv-machines .st-off{color:#888}
  #rv-machines .dim{opacity:.65;font-size:12px} #rv-machines .err{color:#c62828;font-size:12px;max-width:260px}
  #rv-machines button{padding:1px 8px;border-radius:4px;border:1px solid #0b63ce;background:#0b63ce;color:#fff;cursor:pointer;font:12px system-ui}
  #rv-machines button.gray{background:none;color:inherit;border-color:#888}
  #rv-machines select{font:12px system-ui;max-width:160px}
  #rv-machines .rv-usage{flex-direction:column;align-items:flex-start;gap:4px;margin:2px 0 6px;font-size:12px}
  #rv-machines .rv-usage .bar{width:40px} #rv-machines .rv-usage .u{flex-wrap:wrap}
  #rv-machines .rv-usage .long{display:none} #rv-machines .rv-usage .short{display:inline}   /* one line per window; full text in the tooltip */
  #rv-machines .rv-trend svg{width:100%;height:auto}
  #rv-machines .rv-usage .auto,#rv-machines .rv-usage .trend{padding:0 8px;border-radius:10px;font:600 11px system-ui;border:1px solid #888;background:none;color:inherit}
  #rv-machines .rv-usage .auto.on{background:#0b63ce;border-color:#0b63ce;color:#fff}
  #rv-machines .mach>.x{position:absolute;top:2px;right:4px;padding:0 5px;border:0;background:none;color:#888;font:16px/1 system-ui;cursor:pointer}
  #rv-machines .mach>.x:hover{color:#c62828}
  #rv-machines .mach h4{padding-right:18px}
  #rv-machines .rv-load{flex-direction:column;align-items:flex-start;gap:3px;margin:2px 0 6px;font-size:12px}
  #rv-machines .rv-load .bar{width:90px}
  #rv-machines .pick{margin-top:6px}
  #rv-machines .ask{font-size:12px;overflow-wrap:anywhere;margin-top:4px;padding:4px 6px;border:1px solid #c62828;border-radius:4px}
  #rv-machines .ask button{margin-top:4px}
  #rv-machines .tnode>.x{float:right;margin-left:4px;padding:0 4px;border:0;background:none;color:#888;font:15px/1 system-ui;cursor:pointer}
  #rv-machines .tnode>.x:hover{color:#c62828} #rv-machines .err{overflow-wrap:anywhere}
  #rv-machines .newtree{margin-top:6px} #rv-machines .newtree summary{cursor:pointer}
  #rv-machines .newtree input{display:block;width:100%;box-sizing:border-box;margin:3px 0;padding:2px 4px;font:12px system-ui}
  #rv-machines .tnode.git{border:1.5px dashed #2563a8;background:#fff8e1} #rv-machines .tnode.git>b{color:#2563a8}
  #rv-machines .ghpick b{color:#c77c1e}</style>`);
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"})[c]);
  const short = p => String(p).replace(/^\/(Users|home)\/[^/]+/, "~");
  const remoteUrl = (t, path) => location.protocol + "//" + location.hostname + ":" + t.fport + path;
  let mOpen = true;
  try { mOpen = localStorage.getItem("dirai-machines") !== "closed"; } catch (e) {}
  // each machine box opens or folds by a click on its title. Unclicked, a box is folded when every server
  // (tree) on it is unticked, open otherwise; a click is kept per machine (key: its via path) in dirai-mach-open
  const machOpen = () => { try { return JSON.parse(localStorage.getItem("dirai-mach-open")) || {}; } catch (e) { return {}; } };
  function machSave(key, open, def) {
    const m = machOpen();
    if (open === def) delete m[key]; else m[key] = open;    // only a choice that differs from the default is kept
    try { localStorage.setItem("dirai-mach-open", JSON.stringify(m)); } catch (e) {}
  }
  // what the Machines box says in page text (selectable, to copy), not in alert/confirm boxes:
  // actMsg: the last action's error, at the top of the box until dismissed; stopAsk: the tree whose Stop…
  // confirm is open under it (kept across the 10 s redraw)
  let actMsg = "", stopAsk = "", forgetAsk = "";
  const hhmm = () => new Date().toTimeString().slice(0, 5);
  function remoteAct(body, btn) {
    if (btn) { btn.disabled = true; btn.textContent += "…"; }
    lastMap = "";      // F3: redraw after an action, so its button comes back
    const where = location.host + ", op " + body.op + (body.tree ? ", tree " + body.tree : "") + (body.host ? ", host " + body.host : "");
    return fetch("/_review/remotes", {method: "POST", headers: {"Content-Type": "application/json", "X-Review": "1"},
      body: JSON.stringify(body)}).then(r => r.json()).then(res => {
        if (res.error) actMsg = hhmm() + " " + where + ": " + res.error;
        else if (body.at) {      // done by a server further down: this one reads it again now and after 8 s
          [2000, 9500].forEach(t => setTimeout(machines, t));
          if (body.op === "enable") pending[body.at + "|" + body.host] = Date.now();
        }
        setTimeout(machines, 300);
      }).catch(e => {    // the server didn't answer with JSON (e.g. an older server without this op): say so
        actMsg = hhmm() + " " + where + ": no answer from this server (" + e + "). Is it running the current DirAI? Try Restart.";
        setTimeout(machines, 300);
      });
  }
  function stopText(t) {
    const ag = t.agents || [], running = ag.filter(a => a.status === "working").map(a => a.dir || "(top)");
    const queued = ag.filter(a => a.status === "queued").length;
    return `Stop the server of ${short(t.root)}${t.node ? " on " + t.node : ""}${t.port ? ":" + t.port : ""}?\n` +
      (running.length ? `• ${running.length} agent run${running.length === 1 ? " is" : "s are"} going (${running.slice(0, 5).join(", ")}${running.length > 5 ? ", …" : ""}): lost, send again later\n`
                      : "• no agent run is going\n") +
      (queued ? `• ${queued} queued message${queued === 1 ? "" : "s"}: kept, sent at the next start\n` : "") +
      "• SLURM jobs agents wait on keep running; their results are picked up at the next start\n" +
      "• threads and sessions are kept\n" +
      "Start it again with Start (where ssh lands) or New tree… with its path and a node (e.g. --job).";
  }
  function forgetText(t) {
    const going = (t.agents || []).filter(a => a.status === "working").length, where = t.machine || "its machine";
    return `Forget ${short(t.root)} on ${where}?\n` +
      (t.state === "alive" || t.state === "not answering"
        ? `• its server is stopped first${going ? ` (${going} agent run${going === 1 ? "" : "s"} going: lost)` : ""}\n` : "") +
      "• it leaves this list and New tree…'s path list (~/.config/dirai/trees there)\n" +
      "• kept: the folder, its www/ and the agents' sessions; New tree… with its path brings it back\n" +
      `To delete the folder too, on ${where}:\n  rm -r ${t.root}`;
  }
  // "Connect from ~/.ssh/config" (that machine's): the Host entries there not linked yet, linked by that
  // machine's own server (at: one of its running trees, "" for this server). When there is nothing to
  // pick, it says why instead of leaving the box without it.
  // Connect clicked for a machine further down: "at|alias" -> when; shown as "connecting …" until that
  // server reports it enabled (or a minute passes), so the old choice doesn't come back meanwhile
  const pending = {};
  function connectPicker(name, hosts, at) {
    // the box's title already names the machine whose ~/.ssh/config this is (2026-11-09, owner)
    let s = `<div class="dim pick" title="${esc(name)}'s ~/.ssh/config">Connect from ~/.ssh/config:</div>`;
    if (at == null) return s + '<div class="dim">once a DirAI server runs there (Start or New tree)</div>';
    if (!hosts) return s + '<div class="dim">its DirAI is too old to list them: Update it</div>';
    const waiting = hosts.filter(h => !h.enabled && Date.now() - (pending[at + "|" + h.alias] || 0) < 60000);
    hosts.filter(h => h.enabled).forEach(h => delete pending[at + "|" + h.alias]);
    if (waiting.length) s += waiting.map(h => `<div class="dim">connecting ${esc(h.alias)}…</div>`).join("");
    const free = hosts.filter(h => !h.enabled && !waiting.includes(h));
    if (!free.length && waiting.length) return s;
    if (!free.length) return s + `<div class="dim">${!hosts.length ? "no Host entries there" : hosts.length === 1 ? "its one host is connected" : "all " + hosts.length + " of its hosts are connected"}</div>`;
    return s + `<select data-at="${esc(at)}">` + free.map(h => `<option>${esc(h.alias)}</option>`).join("") +
      `</select> <button data-op="connect" data-at="${esc(at)}" title="Log in with ssh from ${esc(name)} (key only, no prompts) and list the DirAI servers there">Connect</button>`;
  }
  // Proposal 72 (lib/shares.py): agent repos shared with you, found by gh on this machine. "Connect from
  // GitHub (gh)" under this machine's ssh row; each connected repo is a node in that machine's box (gitNode), read-only.
  // tid: the tree whose server connects it ("" for this server; D8: each machine's trees have their own)
  function ghPicker(sh, tid, label) {
    tid = tid || "";
    let s = `<div class="dim pick ghpick"><b>Connect from GitHub (gh)${label ? " into " + esc(label) : ""}:</b></div>`;
    if (!sh) return "";
    if (!sh.gh) return s + '<div class="dim">gh isn\'t installed here: the Share pill on any of your pages installs it</div>';
    // a repo's name, with its server when that isn't github.com ("<host>/<owner>/<repo>", shares.py)
    const rn = full => { const p = full.split("/"); return p.length === 3 ? `${p[2]} @ ${p[0]}` : p[1]; };
    const opts = sh.shared.map(r => `<option value="${esc(r.full)}">${esc(rn(r.full))} · ${esc(r.owner)} · ${r.agents} agents</option>`)
      .concat(sh.invitations.map(i => `<option value="${esc(i.full)}" data-inv="${i.id}">${esc(rn(i.full))} · invited by ${esc(i.from)} (accept)</option>`));
    // yours too (as its readers see it, e.g. from another machine), unless connected already
    const conn = new Set((sh.connected || []).map(g => g.full));
    const mine = (sh.mine || []).filter(r => !conn.has(r.full));
    opts.push(...mine.map(r => `<option value="${esc(r.full)}">${esc(rn(r.full))} · yours · ${r.agents} agents</option>`));
    const none = sh.me ? `no one else has shared an agent repo with ${esc(sh.me)} yet` +
      (conn.size && !mine.length && (sh.mine || []).length ? " (yours is connected, below)" : "") +
      ((sh.mine || []).length ? "" : "; yours isn't made yet (the Share pill on any of your pages sets it up)") : "searching…";
    if (!opts.length) return s + `<div class="dim">${none}</div>`;
    return s + `<select data-gh="${esc(tid)}">${opts.join("")}</select> <button data-sop="connect" data-stree="${esc(tid)}" title="Clone it into that tree's www/shares/ (read-only) and fetch it every 10 min; an invitation is accepted first">Connect</button>` +
      (sh.shared.length || sh.invitations.length ? "" : `<div class="dim">${esc(none.split(";")[0])}</div>`);
  }
  // a connected repo: drawn like a server inside the machine box whose tree holds the clone (owner,
  // 2026-11-18: "like a server inside the machine", not a machine box of its own); its agents are rows of
  // the list below (syncRemote), not listed here. tid: that tree ("" for this server); into: its path, when
  // the machine has more than one tree
  // The repos connected in one server's tree: inside that server's node, folded by default ("shared repos (N)"),
  // so a machine's box stays as short as before. tid: that tree ("" for this server).
  // off: that tree is unticked, so none of its agents are listed, its repos' included (their ticks wait, disabled)
  function sharesBox(sh, tid, off) {
    const list = (sh && sh.connected) || [];
    if (!sh) return "";
    // the Connect from GitHub row (and its "no one else has shared…" line) is in the fold too
    return `<details class="tshares" data-sid="${esc(tid)}"><summary class="dim">shared repos (${list.length})` +
      `${list.some(g => g.updated) ? " · <b>updated</b>" : ""}</summary>${ghPicker(sh, tid)}${list.map(g => gitNode(g, tid, off)).join("")}</details>`;
  }
  function gitNode(g, tid, off) {
    tid = esc(tid || "");
    return `<div class="tnode git${g.listed === false ? " hid" : ""}" title="${esc(g.full)}: a shared agent repo, cloned into this server's www/shares/">` +
      `<button class="x" data-sop="disconnect" data-stree="${tid}" data-repo="${esc(g.full)}" title="Disconnect: delete the clone (your access stays)">×</button>` +
      `<input type="checkbox" data-slist="${tid}" data-repo="${esc(g.full)}" ${g.listed === false ? "" : "checked"}${off ? " disabled" : ""} title="${off ?
        "Its tree is unticked, so its agents aren't listed, this repo's included: tick the tree to use this box" :
        "Show this repo's agents in this list (unticked: they stay connected and fetched, and agents can still find them as colleagues)"}">` +
      `<a href="${esc((g.web || "https://github.com/" + g.full) + "/tree/HEAD/agents")}" target="_blank" rel="noopener" title="Its agents/ folder on GitHub, in a new tab"><b>${esc(g.owner)}${g.name !== g.owner ? " · " + esc(g.name) : ""}</b></a>${g.host && g.host !== "github.com" ? ` <span class="dim">@ ${esc(g.host)}</span>` : ""}<br>` +
      `<span class="dim">shared · read-only</span><br>` +
      `${g.agents.length} agent${g.agents.length === 1 ? "" : "s"}${g.updated ? ` · <b>${g.updated} updated</b>` : ""} <span class="dim">· fetched ${esc(g.fetched.slice(5, 16).replace("T", " "))}</span>
        <button class="gray" data-sop="fetch" data-stree="${tid}" data-repo="${esc(g.full)}" title="Fetch now">⟳</button></div>`;
  }
  // where a remote machine's usage widget goes (filled by usageWidget after the redraw): the first of its
  // trees that reports usage stands for the machine (usage and pause levels are per machine, not per tree)
  const uSlot = ts => { const t = (ts || []).find(x => x.usage); return t ? `<div data-utree="${esc(t.id)}"></div>` : ""; };
  // and its load widgets: one per node its trees run on (a cluster's trees may sit on a compute node)
  const lSlots = ts => {
    if (!SHOW_LOAD) return "";       // U11: not shown
    const seen = new Set();
    return (ts || []).filter(t => t.load && !seen.has(t.load.host || t.node) && seen.add(t.load.host || t.node))
      .map(t => `<div data-ltree="${esc(t.id)}"></div>`).join("");
  };
  // × in a machine box's corner: Disconnect (at: the tree whose server holds that ssh link, "" for this one)
  const xBtn = (alias, at) => `<button class="x" data-op="disable" data-host="${esc(alias)}" data-at="${esc(at)}"
    title="Disconnect ${esc(alias)}: close the ssh link and stop listing it. Its servers keep running.">×</button>`;
  // DirAI init + start for a new folder on that machine (at: the tree that links it, "" for this server)
  // trees: that machine's known trees (up and down), offered in the path field's dropdown, e.g. to start a
  // stopped one again on another node
  let ntSeq = 0;
  function newTree(alias, at, trees) {
    const id = "rv-nt" + (ntSeq++), known = (trees || []).filter(t => t.root);
    return `<details class="newtree"><summary class="dim">New tree…</summary>
      <input data-path list="${id}" placeholder="~/project (made if missing), or pick a known one" title="Full path on ${esc(alias)}: /… or ~/…; the dropdown lists this machine's trees">
      <datalist id="${id}">${known.map(t => `<option value="${esc(t.root)}">${esc(t.state === "alive" ? "running" : t.state || "")}</option>`).join("")}</datalist>
      <input data-node placeholder="node: empty, a node name or --job" title="Where the server runs: empty = where ssh lands; a node name (e.g. a019); --job = its own sbatch job">
      <button data-op="new" data-host="${esc(alias)}" data-at="${esc(at)}" title="DirAI init and DirAI start there over ssh">Init and start</button></details>`;
  }
  function treeNode(t, rep) {
    const via = rep && listedRoute(rep)[t.id], from = via && via !== t.id && rep.trees.find(x => x.id === via);
    const same = from ? `<div class="dim">same tree as ${esc(routeLabel(from))}: its agents are listed from there</div>` : "";
    const alive = t.state === "alive", bad = t.state === "not answering" || t.stale && !alive;
    const cls = alive ? "" : t.state === "down" ? " off" : bad ? " bad" : " off";
    const asking = (t.agents || []).filter(a => a.asking || a.denied).length;
    const restart = `<button class="gray" data-op="restart" data-tree="${esc(t.id)}" title="DirAI restart there: reloads its server with the current code. Running agent runs are stopped.">Restart</button>`;
    const stop = `<button class="gray stop" data-op="stop" data-tree="${esc(t.id)}" title="DirAI stop there: its server stops; agent runs going on are lost, everything else is kept. Start it again with Start, or New tree… with its path and a node">Stop…</button>`;
    // the server showing this list, reached here through another machine: it can't stop or forget itself
    const own = !!(rep && rep.tree_id && t.tree_id === rep.tree_id);
    const stopB = own ? "" : stop;
    const act = alive && t.fport ? `<a href="${esc(remoteUrl(t, "/www/index.html"))}" target="_blank"><button>Open</button></a> ${restart} ${stopB}`
      : t.state === "down" ? `<button data-op="start" data-tree="${esc(t.id)}" title="Run DirAI start for this tree on its machine (where ssh lands); for another node use New tree… with this path">Start</button>`
      : ["starting", "restarting", "stopping", "forgetting"].includes(t.state) ? `<span class="dim">${esc(t.state)}…</span>`
      : t.state === "not answering" ? `${restart} ${stopB}` : "";
    const forgetX = own ? "" : `<button class="x" data-op="forget" data-tree="${esc(t.id)}" title="Forget…: stop it if it runs and take it off this machine's list of trees. The folder is kept">×</button>`;
    return `<div class="tnode${cls}${t.hidden ? " hid" : ""}" title="${esc(t.root)}">${forgetX}
      <input type="checkbox" data-tree="${esc(t.id)}" ${t.hidden ? "" : "checked"} title="Show this tree's agents in this list">
      <b>${esc(short(t.root))}</b><br><span class="st-${alive ? "alive" : bad ? "bad" : "off"}">${esc(t.state)}${t.stale ? " (stale)" : ""}</span>
      <span class="dim"> · ${esc(t.node || "–")} · ${esc(t.port || "–")}</span><br>
      ${(t.agents || []).length} agent${(t.agents || []).length === 1 ? "" : "s"}${asking ? ` · <b class="st-bad">${asking} needs you</b>` : ""} ${act}
      ${t.error ? `<div class="err">${esc(t.error)}</div>` : ""}${t.note ? `<div class="dim">${esc(t.note)}</div>` : ""}${t.last && !alive ? `<div class="dim">last server ${esc(t.last)}</div>` : ""}${same}${alive ? sharesBox(t.shares, t.id, t.hidden) : ""}${
      stopAsk === t.id ? `<div class="ask">${stopText(t).split("\n").map(l => `<div>${esc(l)}</div>`).join("")}<button data-op="stopyes" data-tree="${esc(t.id)}">Stop</button> <button class="gray" data-op="stopno">Cancel</button></div>` : ""}${
      forgetAsk === t.id ? `<div class="ask">${forgetText(t).split("\n").map(l => `<div>${esc(l)}</div>`).join("")}<button data-op="forgetyes" data-tree="${esc(t.id)}">Forget</button> <button class="gray" data-op="stopno">Cancel</button></div>` : ""}</div>`;
  }
  // a machine's DirAI: Install / Update buttons, and how the last update went (h: one entry of a hosts list)
  function dirai(h, at, rep) {
    if (!h) return "";
    const mine = rep.commit || rep.build || "?";
    // compared with this (top) server's build, also for machines further down
    const behind = h.build ? h.build !== rep.build : h.behind;
    const btn = (label, title) => `<button data-op="update" data-host="${esc(h.alias)}" data-at="${esc(at)}" title="${esc(title)}">${label}</button>`;
    let s = "";
    if (h.state === "updating") s = '<div class="dim">copying DirAI there…</div>';
    // U10: the machine's commit is shown here only (not in the box title), and only when it differs
    else if (h.state === "up" && behind) s = `<div class="dim" title="DirAI there: ${esc(h.commit || "?")}; this server: ${esc(mine)}">DirAI ${esc(h.commit || "?")} differs ${btn("Update",
      "Copy this server's DirAI files to ~/.local/share/dirai there (over ssh, no git), then restart its servers once their agents are idle")}</div>`;
    else if (h.state !== "up" && h.can_update) s = btn("Install / update DirAI",
      "Copy this server's DirAI (" + mine + ") to ~/.local/share/dirai there over ssh, then restart its servers once their agents are idle");
    // U12 (owner, 2026-11-09): a successful copy ("DirAI copied to <dir> (<commit>, <time>)", remotes.py:811)
    // isn't shown; failures, timeouts and new-tree notes still are
    const note = h.note && !/^DirAI copied to /.test(h.note) ? h.note : "";
    return s + (note ? `<div class="dim">${esc(note)}</div>` : "");
  }
  // this (top) server's own DirAI checkout (self_update.py): how far behind its upstream it is, and
  // "Pull, restart when idle" (git pull --ff-only, then a restart once no agent run is going). Only in
  // this server's box, and only when its DirAI is a git checkout with an upstream (a copy has none).
  function pullBox(su) {
    if (!su || !su.pull) return "";
    const ago = su.fetched ? Math.round((Date.now() / 1000 - su.fetched) / 60) : null;
    const n = (k, w) => k + " " + w + (k === 1 ? "" : "s");
    let s = `<div class="dim">DirAI ${esc(su.branch)} @ ${esc(su.commit)}</div>`;
    s += su.behind ? `<div class="st-bad">${esc(su.upstream)}: ${n(su.behind, "new commit")}` +
      (su.ahead ? ` · ${n(su.ahead, "local commit")} not pushed` : "") + "</div>"
      : `<div class="dim">up to date with ${esc(su.upstream)}${su.ahead ? " · " + n(su.ahead, "local commit") + " not pushed" : ""}</div>`;
    s += `<div class="dim">${su.fetching ? "fetching…" : ago == null ? "not fetched yet" : "fetched " + (ago < 1 ? "just now" : ago + " min ago")} ` +
      `<button class="gray" data-pull="check" title="git fetch now">Check now</button></div>`;
    if (su.fetch_error) s += `<div class="err">git fetch: ${esc(su.fetch_error)}</div>`;
    if (su.rewritten) s += `<div class="dim">its history was rewritten (${esc(su.rewritten.old.slice(0, 7))} is now ${esc(su.rewritten.new.slice(0, 7))}): ` +
      `Pull moves this checkout onto it${su.rewritten.own ? ", keeping your " + n(su.rewritten.own, "commit") + " on top" : ""}</div>`;
    if (su.incoming.length) s += `<details><summary class="dim">the new commits</summary><div class="dim">${su.incoming.map(esc).join("<br>")}</div></details>` +
      `<button data-pull="pull" title="git pull --ff-only in this DirAI checkout; refused (with the commands to run yourself) if it can't fast-forward or would touch a file with uncommitted changes. Then this server restarts once no agent run is going.">Pull, restart when idle</button>`;
    if (su.pulled) s += `<div class="dim">pulled ${esc(su.pulled)}</div>`;
    if (su.note) s += `<div class="dim">${esc(su.note)}</div>`;
    return s;
  }
  function pullAct(op, b) {
    b.disabled = true; b.textContent += "…";
    lastMap = "";      // F3: redraw after it, so the button comes back
    fetch("/_review/" + (op === "pull" ? "pull" : "pull_check"), {method: "POST",
      headers: {"Content-Type": "application/json", "X-Review": "1"}, body: "{}"}).then(r => r.json()).then(res => {
        if (res.error) alert(res.error + (res.commands && res.commands.length ? "\n\nIn a terminal:\n" + res.commands.join("\n") : ""));
        setTimeout(machines, op === "check" ? 4000 : 300);
      }).catch(() => setTimeout(machines, 3000));
  }
  // the ssh links: an arrow from each machine box to the boxes it links (green up, red down, grey
  // dashed while DirAI is being copied); side by side it joins the facing edges, else bottom to top
  function drawArrows(el) {
    const row = el.querySelector(".mrow");
    if (!row || !el.open) return;
    const old = row.querySelector("svg.arrows"); if (old) old.remove();
    const R = row.getBoundingClientRect(), ox = R.left - row.scrollLeft, oy = R.top, box = {};
    row.querySelectorAll(".mach[data-key]").forEach(b => box[b.dataset.key] = b);
    const NS = "http://www.w3.org/2000/svg", svg = document.createElementNS(NS, "svg");
    svg.setAttribute("class", "arrows");
    const COL = {0: "#c62828", 1: "#2e7d32", 2: "#888"};
    svg.innerHTML = '<defs>' + Object.entries(COL).map(([k, c]) =>
      `<marker id="rv-ah${k}" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="${c}"/></marker>`).join("") + "</defs>";
    row.querySelectorAll(".mach[data-parent]").forEach(b => {
      const p = box[b.dataset.parent]; if (!p) return;
      const a = p.getBoundingClientRect(), c = b.getBoundingClientRect(), up = b.dataset.up;
      let x1, y1, x2, y2;
      if (c.left >= a.right - 1) { x1 = a.right; y1 = a.top + 24; x2 = c.left; y2 = c.top + 24; }       // to the right
      else if (c.top >= a.bottom - 1) { x1 = a.left + 30; y1 = a.bottom; x2 = c.left + 30; y2 = c.top; } // below (wrapped)
      else { x1 = a.left; y1 = a.top + 24; x2 = c.right; y2 = c.top + 24; }                                // to the left
      const ln = document.createElementNS(NS, "path");
      const mx = (x1 + x2) / 2 - ox, my = (y1 + y2) / 2 - oy;
      ln.setAttribute("d", y1 === y2 || Math.abs(x1 - x2) > Math.abs(y1 - y2)
        ? `M${x1 - ox},${y1 - oy} C${mx},${y1 - oy} ${mx},${y2 - oy} ${x2 - ox},${y2 - oy}`
        : `M${x1 - ox},${y1 - oy} C${x1 - ox},${my} ${x2 - ox},${my} ${x2 - ox},${y2 - oy}`);
      ln.setAttribute("fill", "none"); ln.setAttribute("stroke", COL[up] || COL[1]); ln.setAttribute("stroke-width", "2");
      if (up !== "1") ln.setAttribute("stroke-dasharray", "5 4");
      ln.setAttribute("marker-end", `url(#rv-ah${up in COL ? up : 1})`);
      svg.appendChild(ln);
    });
    row.prepend(svg);
  }
  window.addEventListener("resize", () => { const el = document.getElementById("rv-machines"); if (el) drawArrows(el); });
  // Memory (improvement/home-memory, F1-F4): the map is redrawn only when its HTML would differ from the one
  // drawn last (lastMap), not on every 10 s poll: each redraw left ~4,000 nodes behind and the tab grew to
  // ~240 MB. curRep: the last reply, for the handlers of a map that was kept. uSig: each remote usage
  // widget's last data, so a kept map redraws only the widgets whose usage changed. ro: the one ResizeObserver.
  let lastMap = "", curRep = null, ro = null, lastPoll = 0;
  // a shared repo's tick, as clicked, until a report agrees (or 60 s): a reply already on its way, or a
  // server upstream that hasn't polled that tree since, would otherwise put the old tick back for a while
  const ticks = {};      // "<tree id>|<repo>" -> [listed, until]
  function keepTicks(rep) {
    const now = Date.now();
    [["", rep.shares]].concat((rep.trees || []).map(t => [t.id, t.shares])).forEach(([tid, sh]) =>
      ((sh && sh.connected) || []).forEach(g => {
        const k = tid + "|" + g.full, w = ticks[k];
        if (!w) return;
        if (now > w[1] || (g.listed !== false) === w[0]) delete ticks[k];
        else g.listed = w[0];
      }));
  }
  const uSig = {};
  function machines() {
    lastPoll = Date.now();
    fetch("/_review/remotes").then(r => r.ok ? r.json() : null).then(rep => {
      if (!rep || dragging) return;      // a server from before Machines; or a usage slider is held
      curRep = rep;
      keepTicks(rep);
      let el = document.getElementById("rv-machines");
      if (!el) {
        el = document.createElement("details"); el.id = "rv-machines"; el.open = mOpen;
        el.addEventListener("toggle", () => { try { localStorage.setItem("dirai-machines", el.open ? "open" : "closed"); } catch (e) {} drawArrows(el); });
        document.getElementById("rv-tabs").before(el);
      }
      const groups = {};      // via path -> trees
      rep.trees.forEach(t => (groups[t.via.join(" → ")] = groups[t.via.join(" → ")] || []).push(t));
      // machines a downstream server links but lists no tree for (down, or DirAI missing there): a box too
      const empty = {};
      rep.trees.forEach(t => (t.hosts || []).filter(x => x.enabled).forEach(x => {
        const k = t.via.concat(x.alias).join(" → ");
        if (!groups[k] && !empty[k]) empty[k] = {via: t.via.concat(x.alias), up: t, h: x};
      }));
      const hostsOn = rep.hosts.filter(h => h.enabled);
      const nbad = rep.trees.filter(t => t.state === "not answering").length + hostsOn.filter(h => h.state !== "up").length;
      const nask = rep.trees.reduce((n, t) => n + (t.agents || []).filter(a => a.asking || a.denied).length, 0);
      const nmach = new Set(rep.trees.map(t => t.via.join(" → "))).size + 1;
      let h = `<summary>Machines — ${rep.trees.length + 1} servers on ${nmach} machines${nask ? " · " + nask + " needs you" : ""}${nbad ? " · " + nbad + " not answering" : ""}</summary>` +
        (actMsg ? `<div class="err"><div>${esc(actMsg)}</div><button class="gray" data-op="msgclose">Dismiss</button></div>` : "") + `<div class="mrow">`;
      // every machine is first a model, then drawn by machineBox, so all boxes have the same parts in the
      // same order. key: its via path ("" for this server); parent: the box it hangs from (drawArrows);
      // h: its ssh link as the server holding it reports it; at: the tree whose server holds that link
      // ("" for this server, null if unknown); trees: its trees; pickAt: a running tree there, whose
      // server can link the next machines (its hosts: that machine's ssh config)
      const boxes = [{key: "", local: true, name: rep.machine, sub: "this server", hosts: rep.hosts, pickAt: ""}];
      const live = ts => (ts || []).find(t => t.state === "alive");
      const add = (key, parent, name, sub, h, at, ts) => boxes.push({key, parent, name, sub, h, at, trees: ts,
        alias: name, hosts: live(ts) && live(ts).hosts, pickAt: live(ts) ? live(ts).id : null});
      // where that machine's ssh link lands (hostname -s there: on a cluster, which login node); its DirAI
      // commit is not here but in the body, and only when it differs from this server's (dirai(), U10)
      const sub = (pre, hh) => [pre, hh && hh.machine && hh.machine !== hh.alias ? "ssh on " + hh.machine : ""]
        .filter(Boolean).join(" · ");
      hostsOn.forEach(hst => add(hst.alias, "", hst.alias, sub("", hst), hst, "", groups[hst.alias] || []));
      Object.keys(groups).filter(k => !hostsOn.some(x => x.alias === k)).forEach(k => {
        const ts = groups[k], via = ts[0].via, last = via[via.length - 1], pk = via.slice(0, -1).join(" → ");
        // that machine as its upstream server sees it: in the hosts list of the tree reporting it
        const up = rep.trees.find(t => t.via.join(" → ") === pk && (t.hosts || []).some(x => x.alias === last));
        const hh = up && up.hosts.find(x => x.alias === last);
        // U13 (owner, 2026-11-09): no "via <machine>" in the title; the arrow into the box shows it
        add(k, pk, last, sub("", hh), hh, up ? up.id : null, ts);
      });
      Object.values(empty).forEach(e => {
        const pk = e.via.slice(0, -1).join(" → ");
        add(e.via.join(" → "), pk, e.via[e.via.length - 1], "", e.h, e.up.id, []);
      });
      function machineBox(m) {
        const h = m.h, reached = m.local || !h || h.state === "up" || h.state === "updating", linked = m.local || !h || h.state === "up";
        const link = !h || h.state === "up" ? 1 : h.state === "updating" ? 2 : 0;
        let s = `<div class="mach${reached ? "" : " down"}" data-key="${esc(m.key)}"` +
          (m.local ? ">" : ` data-parent="${esc(m.parent)}" data-up="${link}">`);
        if (!m.local && m.at != null) s += xBtn(m.alias, m.at);
        // U7: folded by default when every server on it is unticked (this server: rep.hidden)
        const ts = m.local ? [{hidden: rep.hidden, state: "alive", agents: []}] : m.trees;
        const shown = ts.filter(t => !t.hidden).length, def = !(ts.length && !shown), stored = machOpen()[m.key];
        const nask = ts.reduce((n, t) => n + (t.agents || []).filter(a => a.asking || a.denied).length, 0);
        const ndown = ts.filter(t => t.state !== "alive").length;
        const fold = [!ts.length ? "no servers" : ts.length + " server" + (ts.length === 1 ? "" : "s") + (shown ? ", " + shown + " shown" : ", none selected")]
          .concat(nask ? [`<b class="st-bad">${nask} needs you</b>`] : [], ndown ? [`<span class="st-bad">${ndown} not alive</span>`] : [],
                  reached ? [] : ['<span class="st-bad">not reached</span>']).join(" · ");
        s += `<details class="mbody" data-mkey="${esc(m.key)}" data-def="${def ? 1 : 0}"${(stored == null ? def : stored) ? " open" : ""}>` +
          `<summary><h4>${esc(m.name)} <span class="dim">${esc(m.sub)}</span></h4><div class="fold">${fold}</div></summary>`;
        if (!reached) s += `<div class="err">${esc(h.error || "connecting…")}</div>` +
          (m.at === "" ? '<button class="gray" data-op="refresh">Retry now</button>' : "");
        s += m.local ? '<div class="uslot"></div><div class="lslot"></div>' : uSlot(m.trees) + lSlots(m.trees) + dirai(h, m.at || "", rep);
        s += m.local ? `<div class="tnode${rep.hidden ? " hid" : ""}">
          <input type="checkbox" data-tree="" ${rep.hidden ? "" : "checked"} title="Show this tree's agents in this list"><b>${esc(short(rep.root))}</b><br>
          <span class="st-alive">alive · this list</span> <button class="gray" data-op="restart" data-tree=""
          title="DirAI restart here: reloads this server with the current code (e.g. after a DirAI update), then this page. Running agent runs are stopped.">Restart</button>${sharesBox(rep.shares, "", rep.hidden)}</div>` + pullBox(rep.self_update)
          : m.trees.map(t => treeNode(t, rep)).join("") || (reached ? '<div class="dim">no DirAI trees there yet</div>' : "");
        if (!m.local && linked && m.at != null) s += newTree(m.alias, m.at, m.trees);
        if (linked) s += connectPicker(m.local ? "this machine" : m.name, m.hosts, m.pickAt);
        return s + "</details></div>";
      }
      ntSeq = 0;      // New tree… datalist ids: the same on every poll, so an unchanged map gives the same HTML
      h += boxes.map(machineBox).join("");
      // each remote machine's usage: the same widget, its sliders and chart going to that machine's server.
      // Its times (when()) follow the clock, so it is redrawn at least every 10 min.
      const usageWidgets = all => el.querySelectorAll("[data-utree]").forEach(d => {
        const t = rep.trees.find(x => x.id === d.dataset.utree);
        if (!t) return;
        const sig = JSON.stringify(t.usage) + "|" + Math.floor(Date.now() / 600000);
        if (all || uSig[t.id] !== sig) { uSig[t.id] = sig; usageWidget(d, t.usage, remoteIO(t)); }
      });
      // F3: nothing the map shows has changed (states, counts, asks, notes, errors are all in h): keep it
      if (h === lastMap && el.querySelector(".mrow")) {
        usageWidgets(false);
        return syncRemote(rep);
      }
      lastMap = h;
      // the 10 s redraw keeps an open New tree form, what is typed in it and the focus
      const keep = {}, fk = f => f.querySelector("button").dataset.host + "|" + f.querySelector("button").dataset.at;
      el.querySelectorAll(".newtree").forEach(f => keep[fk(f)] = {open: f.open, path: f.querySelector("[data-path]").value,
        node: f.querySelector("[data-node]").value, focus: f.contains(document.activeElement) && document.activeElement.hasAttribute("data-path") ? "path" : f.contains(document.activeElement) && document.activeElement.hasAttribute("data-node") ? "node" : ""});
      el.querySelectorAll("select[data-at]").forEach(s => keep["pick|" + s.dataset.at] = s.value);   // a host picked, not yet Connected
      el.querySelectorAll("details.mbody").forEach(d => keep["mb|" + d.dataset.mkey] = d.open);
      el.querySelectorAll("details.tshares").forEach(d => keep["sh|" + d.dataset.sid] = d.open);    // folded unless opened
      // the usage row (sliders, chart) lives in this server's box: take it out before the redraw, put it back after
      // and so does the load row
      const usageEl = document.getElementById("rv-usage"), loadEl = document.getElementById("rv-load");
      [usageEl, loadEl].forEach(x => x && x.remove());
      el.innerHTML = h + "</div>";
      if (usageEl) el.querySelector(".uslot").appendChild(usageEl);
      if (loadEl) el.querySelector(".lslot").appendChild(loadEl);
      el.querySelectorAll("[data-ltree]").forEach(d => {
        const t = rep.trees.find(x => x.id === d.dataset.ltree);
        if (t) loadWidget(d, t.load);
      });
      usageWidgets(true);
      el.querySelectorAll("select[data-at]").forEach(s => {
        const v = keep["pick|" + s.dataset.at];
        if (v && [...s.options].some(o => o.value === v)) s.value = v;
      });
      el.querySelectorAll("details.mbody").forEach(d => {
        const k = "mb|" + d.dataset.mkey;
        if (k in keep) d.open = keep[k];
        d.addEventListener("toggle", () => drawArrows(el));       // folding moves the boxes under it
        // a click on the title is the owner's choice (not the redraw's own open/close): kept per machine
        d.querySelector("summary").addEventListener("click", () => machSave(d.dataset.mkey, !d.open, d.dataset.def === "1"));
      });
      el.querySelectorAll("details.tshares").forEach(d => {
        if (keep["sh|" + d.dataset.sid]) d.open = true;
        d.addEventListener("toggle", () => drawArrows(el));       // opening it moves the boxes under it
      });
      el.querySelectorAll(".newtree").forEach(f => {
        const k = keep[fk(f)]; if (!k) return;
        f.open = k.open; f.querySelector("[data-path]").value = k.path; f.querySelector("[data-node]").value = k.node;
        if (k.focus) { const i = f.querySelector("[data-" + k.focus + "]"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }
      });
      // one column per hop: this server, the machines it links, theirs, …
      const row = el.querySelector(".mrow"), cols = [];
      [...row.querySelectorAll(".mach")].forEach(b => {
        const d = b.dataset.key ? b.dataset.key.split(" → ").length : 0;
        for (let i = cols.length; i <= d; i++) { cols.push(document.createElement("div")); cols[i].className = "mcol"; }
        cols[d].appendChild(b);
      });
      cols.forEach(c => row.appendChild(c));
      drawArrows(el);
      if (window.ResizeObserver) {      // wrapping changes the layout
        if (ro) ro.disconnect();
        ro = new ResizeObserver(() => drawArrows(el)); ro.observe(row);
      }
      el.querySelectorAll("button[data-pull]").forEach(b => b.onclick = e => {
        e.preventDefault();
        if (b.dataset.pull === "pull" && !confirm("Pull DirAI (git pull --ff-only) and restart this server once no agent run is going?")) return;
        pullAct(b.dataset.pull, b);
      });
      el.querySelectorAll("button[data-op]").forEach(b => b.onclick = e => {
        e.preventDefault();
        const op = b.dataset.op;
        if (op === "connect") {
          const sel = b.previousElementSibling, at = b.dataset.at;
          return remoteAct({op: "enable", host: sel.value, at}, b);
        }
        if (op === "new") {
          const f = b.closest(".newtree"), path = f.querySelector("[data-path]").value.trim();
          if (!path) return alert("Give the folder's full path there, e.g. ~/project");
          return remoteAct({op, host: b.dataset.host, at: b.dataset.at, path, node: f.querySelector("[data-node]").value.trim()}, b);
        }
        if (op === "disable" && !confirm("Disconnect " + b.dataset.host + "? Its servers keep running.")) return;
        if (op === "restart" && !confirm("Restart this server? Agent runs going on there are stopped.")) return;
        // Stop… opens its confirm in the page under the tree (text you can select); Stop there sends it
        if (op === "stop") { stopAsk = b.dataset.tree; forgetAsk = ""; return machines(); }
        if (op === "forget") { forgetAsk = b.dataset.tree; stopAsk = ""; return machines(); }
        if (op === "stopno") { stopAsk = forgetAsk = ""; return machines(); }
        if (op === "forgetyes") { forgetAsk = ""; return remoteAct({op: "forget", tree: b.dataset.tree, at: ""}, b); }
        if (op === "msgclose") { actMsg = ""; return machines(); }
        if (op === "stopyes") { stopAsk = ""; return remoteAct({op: "stop", tree: b.dataset.tree, at: ""}, b); }
        if (op === "restart" && !b.dataset.tree) {    // this server: reload the page once it answers again
          b.disabled = true; b.textContent = "Restarting…";
          const back = () => fetch("/www/index.html", {cache: "no-store"}).then(r => r.ok ? location.reload() : setTimeout(back, 1500))
            .catch(() => setTimeout(back, 1500));
          return fetch("/_review/remotes", {method: "POST", headers: {"Content-Type": "application/json", "X-Review": "1"},
            body: JSON.stringify({op: "restart"})}).then(r => r.json()).then(res => {
              if (res.error) { alert("Restart: " + res.error); b.disabled = false; b.textContent = "Restart"; }
              else setTimeout(back, 3000);
            }).catch(() => setTimeout(back, 3000));
        }
        remoteAct({op, host: b.dataset.host, tree: b.dataset.tree, at: b.dataset.at || ""}, b);
      });
      // shared agent repos (ghPicker, gitNode): connect, fetch now, disconnect (POST /_review/share)
      el.querySelectorAll("button[data-sop]").forEach(b => b.onclick = e => {
        e.preventDefault();
        const op = b.dataset.sop, body = {op, repo: b.dataset.repo}, tid = b.dataset.stree || "";
        if (op === "connect") {
          const sel = [...el.querySelectorAll("select[data-gh]")].find(x => x.dataset.gh === tid), o = sel.selectedOptions[0];
          body.repo = sel.value;
          if (o.dataset.inv) body.invitation = +o.dataset.inv;
        }
        if (op === "disconnect" && !confirm("Disconnect " + b.dataset.repo + "? Its clone is deleted; your access stays, and Connect brings it back.")) return;
        if (tid) return remoteAct({op: "call", tree: tid, path: "share", data: body}, b);    // that tree's server does it
        b.disabled = true;
        fetch("/_review/share", {method: "POST", headers: {"Content-Type": "application/json", "X-Review": "1"}, body: JSON.stringify(body)})
          .then(r => r.json()).catch(err => ({error: String(err)}))
          .then(r => { if (r.error) actMsg = "GitHub: " + r.error; lastMap = ""; machines(); });
      });
      // a connected repo's tick: its agents in the list or not; shown at once, then saved by the tree holding the clone
      el.querySelectorAll("input[data-slist]").forEach(c => c.onchange = () => {
        const tid = c.dataset.slist, t = tid && curRep.trees.find(x => x.id === tid);
        const sh = tid ? t && t.shares : curRep.shares;
        ((sh && sh.connected) || []).forEach(g => { if (g.full === c.dataset.repo) g.listed = c.checked; });
        ticks[tid + "|" + c.dataset.repo] = [c.checked, Date.now() + 60000];
        c.parentElement.classList.toggle("hid", !c.checked);
        lastMap = "";
        syncRemote(curRep);
        const k = tid + "|" + c.dataset.repo, body = {op: c.checked ? "list" : "unlist", repo: c.dataset.repo};
        // saved by the tree holding the clone (this server's, or another through op call); a refusal puts the tick back
        fetch(tid ? "/_review/remotes" : "/_review/share", {method: "POST", headers: {"Content-Type": "application/json", "X-Review": "1"},
          body: JSON.stringify(tid ? {op: "call", tree: tid, path: "share", data: body} : body)})
          .then(r => r.json()).catch(err => ({error: String(err)}))
          .then(r => {
            if (!r.error) return;
            actMsg = hhmm() + " " + (tid || "this server") + ": " + r.error +
              (r.error === "no such agent" ? " (its server runs DirAI from before this tick box: Update or Restart it)" : "");
            delete ticks[k]; lastMap = ""; machines();
          });
      });
      // a tree's tick: its agents in the list (both tabs); shown at once, then saved on the server
      // (curRep, not rep: the handlers of a kept map act on the latest reply)
      el.querySelectorAll("input[data-tree]").forEach(c => c.onchange = () => {
        const tid = c.dataset.tree;
        if (tid) curRep.trees.forEach(t => { if (t.id === tid) t.hidden = !c.checked; });
        else curRep.hidden = !c.checked;
        c.parentElement.classList.toggle("hid", !c.checked);
        c.parentElement.querySelectorAll("input[data-slist]").forEach(x => {     // its shared repos wait with it
          x.disabled = !c.checked;      // (the tree's node, greyed, holds them: they're greyed with it)
        });
        lastMap = "";      // the box was changed by hand: the next poll draws the map again
        syncRemote(curRep);
        remoteAct({op: c.checked ? "show" : "hide", tree: tid});
      });
      syncRemote(rep);
    }).catch(() => {});
  }
  // Every shown remote tree's agents become rows of the one table: the <tr> that tree's own list has (same
  // columns and cells; remotes.agent_rows passes it on as "row"), linked to that tree and named
  // machine:path/. With them in the table, this server's own rows are named machine:path/ too.
  const stamp = t => new Date(t * 1000).toLocaleString([], {year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"});
  function remoteRow(t, a) {
    const label = t.via[t.via.length - 1] + ":" + short(t.root) + "/" + (a.dir ? a.dir + "/" : "");
    const box = document.createElement("tbody");
    // a server too old to pass its row on: the same cells, size and tokens left empty
    box.innerHTML = a.row || `<tr><td><a></a>${a.title ? `<div class="sub">${esc(a.title)}</div>` : ""}</td>` +
      `<td class="num" data-v="${+a.mtime || 0}">${esc(stamp(a.mtime))}</td><td class="num" data-v="-1"></td><td class="num" data-v="0"></td></tr>`;
    const tr = box.firstElementChild, link = tr.querySelector("a");
    link.textContent = label; tr.children[0].dataset.v = label;
    if (t.fport) link.href = remoteUrl(t, "/" + (a.dir ? encodeURI(a.dir) + "/" : "") + "index.html");
    else link.removeAttribute("href");
    tr.dataset.tree = t.id; tr.dataset.agent = a.dir;
    return tr;
  }
  // One tree reached by several routes (directly and through another machine) has the same tree_id on
  // each: its agents are listed from one route only. Of the routes not hidden, the one picked is alive and
  // not stale first, then the shortest, then the most recently checked (route length before the time, so
  // two healthy routes don't swap every poll). tree id -> the id of the route listing that tree.
  function listedRoute(rep) {
    const rank = t => [t.state === "alive" && !t.stale ? 1 : 0, -t.via.length, +t.checked || 0];
    const better = (a, b) => { const x = rank(a), y = rank(b); for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return x[i] > y[i]; return false; };
    const best = {}, out = {};
    rep.trees.filter(t => t.tree_id && !t.hidden && (t.agents || []).length)
      .forEach(t => { if (!best[t.tree_id] || better(t, best[t.tree_id])) best[t.tree_id] = t; });
    rep.trees.forEach(t => { out[t.id] = t.tree_id && best[t.tree_id] ? best[t.tree_id].id : t.id; });
    return out;
  }
  const routeLabel = t => t.via[t.via.length - 1] + ":" + short(t.root) + (t.via.length > 1 ? " via " + t.via.slice(0, -1).join(" → ") : "");
  function syncRemote(rep) {
    localHidden = !!rep.hidden;
    Object.keys(remoteRec).forEach(k => delete remoteRec[k]);
    const listed = listedRoute(rep);
    const shown = rep.trees.filter(t => !t.hidden && (t.agents || []).length && listed[t.id] === t.id);
    treeRoots = [{id: "", name: rep.machine + ":" + short(rep.root)}]
      .concat(shown.map(t => ({id: t.id, name: t.via[t.via.length - 1] + ":" + short(t.root)})));
    // F2: a remote row is made again only when what remoteRow draws changed (that tree's <tr>, the label, the
    // link); its status, badges and star come from remoteRec (paint, drawFavs), so a kept row is up to date
    const old = {};
    allRows().filter(tr => tr.dataset.tree).forEach(tr => old[tr.dataset.tree + "|" + tr.dataset.agent] = tr);
    shown.forEach(t => t.agents.forEach(a => {
      const k = t.id + "|" + a.dir, sig = JSON.stringify([a.row, a.title, a.mtime, t.via, t.root, t.fport]);
      remoteRec[k] = a;
      const tr = old[k]; delete old[k];
      if (tr && tr.rvSig === sig) return;
      if (tr) tr.remove();
      const nr = remoteRow(t, a); nr.rvSig = sig;
      tbody.appendChild(nr);
    }));
    // Proposal 72: the agents of the repos shared with you that are connected (read-only clones under a tree's
    // www/shares/, which the list's scan skips), as rows of their own, so the filter and tabs find them too:
    // this server's (old2, no data-tree) and those of each tree shown (in old, with that tree's rows)
    const old2 = {};
    allRows().filter(tr => tr.dataset.shared && !tr.dataset.tree).forEach(tr => old2[tr.dataset.agent] = tr);
    const sharedRows = (sh, t, olds, pre) => ((sh && sh.connected) || []).filter(g => g.listed !== false).forEach(g => g.agents.forEach(a => {
      const path = a.url.replace(/^\/+|\/+$/g, ""), k = pre + path;
      const label = (t ? t.via[t.via.length - 1] + ": " : "") + `${g.owner} / ${g.full.split("/").pop()} / ${a.slug} · shared, read-only`;
      const href = t ? (t.fport ? remoteUrl(t, a.url) : "") : a.url;
      const sig = JSON.stringify([label, href, a.title, a.published]);
      if (t) remoteRec[k] = {};
      const tr = olds[k]; delete olds[k];
      if (tr && tr.rvSig === sig) return;
      if (tr) tr.remove();
      const box = document.createElement("tbody");
      box.innerHTML = `<tr><td><a${href ? ` href="${esc(href)}"` : ""}></a>${a.title ? `<div class="sub">${esc(a.title)}</div>` : ""}</td>` +
        `<td class="num" data-v="${(Date.parse(a.published) / 1000) || 0}" title="published">${esc(a.published)}</td>` +
        `<td class="num" data-v="-1"></td><td class="num" data-v="0"></td></tr>`;
      const nr = box.firstElementChild;
      nr.querySelector("a").textContent = label; nr.children[0].dataset.v = label;
      if (t) nr.dataset.tree = t.id;
      nr.dataset.agent = path; nr.dataset.shared = "1"; nr.rvSig = sig;
      tbody.appendChild(nr);
    }));
    sharedRows(rep.shares, null, old2, "");
    shown.forEach(t => sharedRows(t.shares, t, old, t.id + "|"));
    Object.values(old2).forEach(tr => tr.remove());     // disconnected, or unshared by their owner
    Object.values(old).forEach(tr => tr.remove());      // trees unticked or gone, agents removed
    const pre = rep.machine + ":" + short(rep.root) + "/";
    allRows().filter(tr => !tr.dataset.tree).forEach(tr => {
      if (!tr.dataset.shared) {
        const label = shown.length ? pre + (tr.dataset.agent ? tr.dataset.agent + "/" : "") : tr.dataset.label;
        tr.querySelector("a").textContent = label; tr.children[0].dataset.v = label;
      }
      tr.classList.toggle("rv-off", localHidden);     // this tree's shared agents follow its tick box too
    });
    drawFavs();
    paint();
    const q = document.getElementById("q");
    if (q.value) q.dispatchEvent(new Event("input"));     // the filter, over the new rows too
  }
  let treeRoots = [{id: "", name: "this server"}];   // each tree whose agents are in the table, this server first
  machines();
  // F4: a hidden tab polls every 60 s, and catches up as soon as it is shown again
  setInterval(() => { if (!document.hidden || Date.now() - lastPoll >= 59000) machines(); }, 10000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden && Date.now() - lastPoll > 10000) machines(); });

  // What agent_tree.js (loaded right after this script) uses of the table above, so it keeps no copy of it:
  // rows and their records, stars, the filter box, an agent's summary card, and tabs of its own.
  window.diraiList = {
    rows: allRows, info, isFav, star, onChange: f => onChange.push(f),
    roots: () => treeRoots,
    // the agent's summary card ({} if none): this server's own, or a remote tree's through Machines
    card: tr => tr.dataset.tree ? callTree({id: tr.dataset.tree}, "card", {agent: tr.dataset.agent})
      : fetch("/_review/card?agent=" + encodeURIComponent(tr.dataset.agent)).then(r => r.ok ? r.json() : {}),
    // a new tab after All; show(on) is called on every redraw with whether it is the open one
    addView: (name, label, show) => {
      views[name] = show;
      const b = document.createElement("button");
      b.dataset.tab = name; b.textContent = label;
      tabs.appendChild(b); pickTab(b); drawFavs();
    },
  };

  // Refresh: run the server's 10-minute housekeeping now (SLURM job check, list rebuild), then reload
  document.body.insertAdjacentHTML("beforeend", `<button id="rv-refresh" title="Check the SLURM jobs agents are waiting on and rebuild this list now (it also happens every 10 minutes)"
    style="position:fixed;left:232px;bottom:16px;z-index:99999;padding:8px 14px;border-radius:20px;border:1px solid #888;
    background:#1d1d1f;color:#fff;font:600 14px system-ui;cursor:pointer">Refresh</button>`);
  const rb = document.getElementById("rv-refresh");
  rb.onclick = () => {
    rb.disabled = true; rb.textContent = "Refreshing…";
    fetch("/_review/refresh", {method: "POST", headers: {"Content-Type": "application/json", "X-Review": "1"}, body: "{}"})
      .then(r => r.ok ? location.reload() : Promise.reject())
      .catch(() => { rb.disabled = false; rb.textContent = "Refresh failed (DirAI restart?)"; });
  };
})();
