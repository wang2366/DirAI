// The agent's panel, which server.py adds to every index.html it serves (owner only).
(function () {
  const AGENT = document.currentScript.dataset.agent;
  const api = (path, body) => fetch("/_review/" + path, body === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json", "X-Review": "1"},
    body: JSON.stringify(Object.assign({agent: AGENT}, body)),
  }).then(r => r.json());

  const css = `
  #rv-btn{position:fixed;right:16px;bottom:16px;z-index:99999;padding:8px 14px;border-radius:20px;
    border:1px solid #888;background:#1d1d1f;color:#fff;font:600 14px system-ui;cursor:pointer}
  #rv-panel{position:fixed;right:16px;bottom:64px;z-index:99999;width:min(460px,calc(100vw - 32px));
    max-height:75vh;display:none;flex-direction:column;background:#fff;color:#1d1d1f;border:1px solid #bbb;
    border-radius:10px;box-shadow:0 8px 30px rgba(0,0,0,.25);font:14px/1.45 system-ui}
  #rv-panel.open{display:flex}
  #rv-head{display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid #ddd}
  #rv-head b{flex:1}
  .rv-pill{padding:2px 9px;border-radius:10px;font-size:12px;font-weight:600;color:#fff}
  .rv-working{background:#b26b00}.rv-queued{background:#7b1fa2}.rv-unread{background:#0b63ce}.rv-read{background:#2e7d32}
  .rv-closed{background:#666}.rv-none{background:#999}.rv-asking{background:#c62828}
  #rv-thread{overflow:auto;padding:10px 12px;flex:1}
  .rv-msg{margin:0 0 10px;padding:8px 10px;border-radius:8px;white-space:pre-wrap;word-wrap:break-word}
  .rv-user{background:#eef4ff}.rv-claude{background:#f3f3f3}.rv-system{background:#fff6e0;font-size:13px}
  .rv-meta{font-size:11px;color:#777;margin-bottom:3px}
  .rv-ask{background:#fdecea;border:1px solid #e8b4ae;font-size:13px;white-space:normal}
  .rv-ask summary{cursor:pointer;word-break:break-all}
  .rv-ask pre{white-space:pre-wrap;word-break:break-all;margin:4px 0;font-size:12px;background:#fff;padding:4px;border:1px solid #eee;max-height:25vh;overflow:auto}
  .rv-ask .rv-row button.deny{border-color:#c62828;color:#c62828}
  .rv-said{font-size:12px;color:#555;margin-top:4px}
  #rv-denials{padding:8px 12px;border-top:1px solid #ddd;background:#fff8f0;display:none;flex-shrink:0}
  #rv-dlist{max-height:22vh;overflow:auto;margin:6px 0;padding-left:18px}
  #rv-dlist li{margin:3px 0;font-size:12.5px;word-break:break-all}
  #rv-dlist summary{cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  #rv-dlist details[open] summary{white-space:normal}
  #rv-dlist pre{white-space:pre-wrap;margin:4px 0;font-size:12px;background:#fff;padding:4px;border:1px solid #eee}
  #rv-thread{min-height:80px}
  #rv-foot{flex-shrink:0}
  #rv-foot{padding:10px 12px;border-top:1px solid #ddd}
  #rv-text{width:100%;box-sizing:border-box;min-height:70px;font:14px system-ui;padding:6px}
  .rv-row{display:flex;gap:6px;margin-top:6px;flex-wrap:wrap}
  .rv-row button,#rv-denials button{padding:5px 10px;border-radius:6px;border:1px solid #999;background:#fafafa;cursor:pointer;font:13px system-ui}
  .rv-row button.primary{background:#0b63ce;color:#fff;border-color:#0b63ce}
  button:disabled{opacity:.5;cursor:default}
  #rv-ctx{font-size:12px;color:#777;white-space:nowrap}
  #rv-every{font:13px system-ui;padding:4px 2px;border:1px solid #999;border-radius:6px;background:#fafafa;color:#1d1d1f}
  #rv-repedit{display:none;margin-top:6px;padding:6px 8px;border-radius:6px;background:#f3f3f3}
  #rv-repedit div{font-size:12.5px;margin-bottom:4px}
  #rv-reptext{width:100%;box-sizing:border-box;min-height:60px;font:13px system-ui;padding:5px}
  #rv-repinfo{display:none;margin-top:6px;font-size:12.5px;color:#555;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  #rv-model{font:12px system-ui;padding:1px 2px;border:1px solid #bbb;border-radius:6px;background:#fff;color:#1d1d1f}
  #rv-ctx.warn{color:#b26b00;font-weight:600} #rv-ctx.high{color:#c62828;font-weight:600}
  #rv-stale{display:none;margin:0 0 6px;padding:6px 8px;border-radius:6px;background:#ffe0e0;font-size:12.5px}
  #rv-cardnote{display:none;margin:0 0 6px;padding:6px 8px;border-radius:6px;background:#ffe0e0;font-size:12.5px}
  #rv-ctxnote{display:none;margin:0 0 6px;padding:6px 8px;border-radius:6px;background:#fff6e0;font-size:12.5px}
  #rv-chip{display:none;align-items:flex-start;gap:6px;margin:0 0 6px;padding:5px 8px;border-radius:6px;background:#eef4ff;font-size:12.5px}
  #rv-chip details,.rv-sel{flex:1;min-width:0}
  #rv-chip summary,.rv-sel summary{cursor:pointer;color:#0b63ce;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  #rv-chip details[open] summary,.rv-sel[open] summary{white-space:normal}
  #rv-unsel{border:0;background:none;cursor:pointer;font-size:15px;line-height:1;padding:0 2px;color:#555}
  .rv-quote{margin:4px 0 2px;padding:4px 8px;border-left:3px solid #9bb8e8;background:#fff;color:#333;
    white-space:pre-wrap;max-height:30vh;overflow:auto;font-size:12.5px}
  .rv-sel{margin:0 0 6px;font-size:12.5px}
  #rv-ask{position:absolute;z-index:99999;display:none;padding:3px 9px;border-radius:12px;border:1px solid #0b63ce;
    background:#0b63ce;color:#fff;font:600 12px system-ui;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.2)}
  .rv-changed{background:rgba(255,213,0,.28)!important;box-shadow:0 0 0 3px rgba(255,213,0,.28)}
  body.rv-nohl .rv-changed{background:none!important;box-shadow:none}
  .rv-removed{margin:4px 0;padding:2px 8px;border-left:3px solid #d93025;background:rgba(217,48,37,.14)}
  .rv-removed>summary{cursor:pointer;color:#c5221f;font:600 12px system-ui}
  body.rv-nohl .rv-removed{display:none}`;
  document.head.insertAdjacentHTML("beforeend", "<style>" + css + "</style>");
  document.body.insertAdjacentHTML("beforeend", `
  <button id="rv-btn">Chat</button><button id="rv-ask">Ask the agent about this</button>
  <div id="rv-panel">
    <div id="rv-head"><b>Chat</b><span id="rv-ctx" title="tokens in this session's context, resent with every message"></span><select id="rv-model" title="Model for this agent's next messages (Sonnet uses fewer of your Claude limits than Opus; the local gpt-oss and GenAI Studio models use none, but are weaker)"></select><span id="rv-status" class="rv-pill rv-none">none</span>
      <button id="rv-x" style="border:0;background:none;font-size:18px;cursor:pointer">&times;</button></div>
    <div id="rv-thread"></div>
    <div id="rv-denials"><b>Claude was blocked from:</b><ul id="rv-dlist"></ul>
      <div class="rv-row"><button id="rv-once">Allow once (this agent)</button><button id="rv-always" title="Folder reads stay with this agent; other rules apply to every agent">Always allow</button></div></div>
    <div id="rv-foot"><div id="rv-stale">DirAI was updated. Send or clear your message and this tab reloads, or reload it now.</div><div id="rv-ctxnote"></div><div id="rv-cardnote"></div><div id="rv-chip"></div><textarea id="rv-text" placeholder="Message this agent..."></textarea>
      <div class="rv-row"><button id="rv-save" class="primary">Send</button>
        <button id="rv-read">Mark read</button><button id="rv-new" title="Your next message starts a fresh session (the agent re-reads its index.html and the last few messages)">New chat</button><button id="rv-compact" title="Summarize the conversation so far (Claude Code /compact); the session continues with a much smaller context">Compact</button><button id="rv-close">TaskDone</button><button id="rv-cancel" style="display:none" title="Stop this run (or take the message out of the queue). The session is kept: change the model if you like, then send another message to continue.">Cancel</button><button id="rv-hl" style="display:none" title="Parts of index.html the agent added or changed in its latest run that edited it">Hide changes</button>
        <select id="rv-every" title="Send a message to this agent again on a schedule (it waits if the agent is busy)"><option value="off">Repeat: off</option><option value="hour">Every hour</option><option value="day">Every day</option><option value="week">Every week</option></select></div>
      <div id="rv-repedit"><div id="rv-replabel"></div><textarea id="rv-reptext"></textarea>
        <div class="rv-row"><button id="rv-repsave" class="primary">Save schedule</button><button id="rv-repcancel">Cancel</button></div></div>
      <div id="rv-repinfo"></div></div>
  </div>`);

  const $ = id => document.getElementById(id);
  let state = null, timer = null;
  // redraw the thread only when it changed, and keep the reader's scroll position;
  // jump to the newest message only on first load and after the owner sends something
  let shownThread = null, scrollToEnd = true;
  const LABEL = {closed: "TaskDone"};   // shown name for a stored status
  const esc = s => s.replace(/[&<>]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;"}[c]));

  // The scripts changed on the server since this tab loaded (st.ui): reload, unless that would
  // throw away a message being typed; then just say so. An open panel stays open.
  function stale() {
    if (!$("rv-text").value.trim() && !repEditing()) {
      try { if ($("rv-panel").classList.contains("open")) sessionStorage.setItem("rv-open", "1"); } catch (e) {}
      return location.reload();
    }
    $("rv-stale").style.display = "block";
    clearTimeout(timer);
    timer = setTimeout(refresh, 4000);
  }
  function render(st) {
    if (render.ui === undefined) render.ui = st.ui;
    else if (st.ui !== render.ui) return stale();
    state = st;
    const s = st.status;
    const asking = !!st.asking;   // a run waits for the owner's answer in the thread
    $("rv-status").textContent = asking ? "needs you" : LABEL[s] || s;
    $("rv-status").className = "rv-pill rv-" + (asking ? "asking" : s);
    $("rv-btn").textContent = "Chat" + (asking ? " ❗" : s === "unread" ? " •" : s === "working" || s === "queued" ? " …" : "");
    if (asking && !render.asking) scrollToEnd = true;   // bring a new prompt into view
    // a run ended (a new reply, also before any SLURM jobs it left are done): files.js reloads the folder
    const last = (st.thread.filter(m => m.role === "claude").pop() || {}).time || "";
    if (render.lastReply !== undefined && last !== render.lastReply) document.dispatchEvent(new Event("dirai:run-done"));
    render.lastReply = last;
    render.asking = asking;
    const threadKey = JSON.stringify(st.thread);
    if (threadKey !== shownThread) {
      const box = $("rv-thread"), top = box.scrollTop;
      const opened = [...box.querySelectorAll(".rv-sel")].map(d => d.open);   // keep expanded quotes expanded
      box.innerHTML = st.thread.map(m => m.role === "ask" ? askHtml(m) :
        `<div class="rv-msg rv-${m.role}"><div class="rv-meta">${m.role}${m.scheduled ? " (scheduled, every " + m.scheduled + ")" : ""}${m.model ? " (" + m.model + ")" : ""} · ${m.time}${m.cost != null ? " · $" + m.cost : ""}</div>${m.selection ? selHtml(m.selection) : ""}${esc(m.text)}</div>`
      ).join("") || '<div class="rv-meta">No comments yet.</div>';
      box.querySelectorAll(".rv-sel").forEach((d, i) => d.open = !!opened[i]);
      shownThread = threadKey;
      if (!$("rv-panel").classList.contains("open")) {}        // hidden: scroll when it opens
      else if (scrollToEnd) { box.scrollTop = box.scrollHeight; scrollToEnd = false; }
      else box.scrollTop = top;
    }
    // waiting on SLURM jobs still counts as working, but a new comment can go in
    const watching = (st.watching || []).length > 0;
    const busy = (s === "working" || s === "queued") && !watching;
    const sel = $("rv-model");
    if (sel.dataset.models !== st.models.join())
      sel.dataset.models = st.models.join(), sel.innerHTML = st.models.map(m => `<option value="${m}">${(st.model_labels || {})[m] || m[0].toUpperCase() + m.slice(1)}</option>`).join("");
    if (document.activeElement !== sel) sel.value = st.model;
    sel.disabled = busy;   // takes effect from the next message
    const rep = st.repeat;
    if (document.activeElement !== $("rv-every") && !repEditing()) $("rv-every").value = rep ? rep.every : "off";
    $("rv-repinfo").style.display = rep ? "block" : "none";
    if (rep) {
      $("rv-repinfo").textContent = `🔁 Every ${rep.every}, next ${new Date(rep.next * 1000).toLocaleString([],
        {weekday: "short", hour: "2-digit", minute: "2-digit"})}: ${rep.text.replace(/\s+/g, " ")}`;
      $("rv-repinfo").title = rep.text;
    }
    ["rv-save", "rv-new"].forEach(id => $(id).disabled = busy);
    ["rv-read", "rv-close"].forEach(id => $(id).disabled = busy || watching);
    $("rv-new").disabled = busy || !st.session_id;   // nothing to start over from yet
    $("rv-compact").disabled = busy || !st.session_id;
    $("rv-cancel").style.display = busy || watching ? "" : "none";
    const ctx = st.context, level = ctx == null ? "" : ctx >= st.context_high ? "high" : ctx >= st.context_warn ? "warn" : "";
    $("rv-ctx").textContent = ctx == null ? "" : "context " + Math.round(ctx / 1000) + "K";
    $("rv-ctx").className = level;
    $("rv-ctxnote").style.display = level && !busy ? "block" : "none";
    if (level) $("rv-ctxnote").textContent = `This conversation is ${Math.round(ctx / 1000)}K tokens, and every message resends all of it, ` +
      `which uses up your Claude limits faster${level === "high" ? " (a lot faster at this size)" : ""}. ` +
      "Compact summarizes it and keeps the session; New chat starts over from index.html and the last few messages.";
    const card = st.card || [];   // the summary card in index.html (dirai_card.py), checked by the server
    $("rv-cardnote").style.display = card.length && !busy ? "block" : "none";
    $("rv-cardnote").textContent = "Summary card: " + card.join("; ") + ". Ask the agent to fix it.";
    const grantable = st.denials.filter(d => !d.blocked && !d.granted);
    // one line per denial; click to see the full command
    const denialKey = JSON.stringify(st.denials);   // same idea: don't collapse opened entries
    if (denialKey !== render.shownDenials) render.shownDenials = denialKey, $("rv-dlist").innerHTML = st.denials.map(d =>
      `<li><details><summary>${d.blocked ? '<i style="color:#a00">always blocked, run it yourself:</i> '
        : d.granted ? '<i style="color:#a00">already allowed, refused by a built-in safety check (shell constructs like $( ), loops or ..); ask the agent to do it with a script:</i> '
        : ""}${esc(d.text.slice(0, 120))}</summary>` +
      `<pre>${esc(d.text)}</pre></details></li>`).join("");
    $("rv-once").style.display = $("rv-always").style.display = grantable.length ? "" : "none";
    $("rv-denials").style.display = st.denials.length && !busy ? "block" : "none";
    clearTimeout(timer);
    if (busy || watching) timer = setTimeout(refresh, watching ? 30000 : 4000);
  }
  // a permission prompt from the run (ask mode): Allow / Always allow / Deny while it waits
  const SAID = {allow: "✅ Allowed", always: "✅ Allowed, and always allowed from now on", deny: "⛔ Denied",
    timeout: "⛔ Denied: no answer within the run's waiting limit", ended: "Not answered: the run ended",
    withdrawn: "Withdrawn by Claude"};
  function askHtml(m) {
    return `<div class="rv-msg rv-ask"><div class="rv-meta">Claude asks to use · ${m.time}</div>` +
      `<details><summary>${esc(m.text.slice(0, 200))}</summary><pre>${esc(m.detail || m.text)}</pre></details>` +
      (m.answer ? `<div class="rv-said">${SAID[m.answer] || esc(m.answer)}</div>`
        : `<div class="rv-row" data-ask="${esc(m.id)}"><button data-choice="allow" class="primary">Allow</button>` +
          `<button data-choice="always" title="Allow it, and keep the rule like the Always allow button (folder reads: this agent only)">Always allow</button>` +
          `<button data-choice="deny" class="deny">Deny</button></div>`) + `</div>`;
  }
  $("rv-thread").addEventListener("click", e => {
    const b = e.target.closest("[data-choice]"), row = b && b.closest("[data-ask]");
    if (!row) return;
    row.querySelectorAll("button").forEach(x => x.disabled = true);
    post("answer", {id: row.dataset.ask, choice: b.dataset.choice});
  });
  const refresh = () => api("state?agent=" + encodeURIComponent(AGENT)).then(render);
  const post = (path, body) => api(path, body).then(r => { if (r.error) alert(r.error); refresh(); });

  $("rv-btn").onclick = () => {
    $("rv-panel").classList.toggle("open");
    if ($("rv-panel").classList.contains("open") && scrollToEnd) {
      $("rv-thread").scrollTop = $("rv-thread").scrollHeight; scrollToEnd = false;   // first open: newest message
    }
    if ($("rv-panel").classList.contains("open") && state && state.status === "unread") post("status", {status: "read"});
  };
  $("rv-x").onclick = () => $("rv-panel").classList.remove("open");
  $("rv-save").onclick = () => {
    const text = $("rv-text").value.trim();
    if (!text) return;
    $("rv-text").value = "";
    scrollToEnd = true;   // show the message just sent
    post("comment", pinned ? {text, selection: pinned} : {text});
    pin(null);
  };
  $("rv-model").onchange = () => post("model", {model: $("rv-model").value});
  // Picking a period opens a multi-line editor for the message (the message box's text, else the
  // current repeated message, else the last one sent); Save schedule stores it.
  const repEditing = () => $("rv-repedit").style.display === "block";
  const repClose = () => { $("rv-repedit").style.display = "none"; $("rv-every").value = state.repeat ? state.repeat.every : "off"; };
  $("rv-every").onchange = () => {
    const every = $("rv-every").value;
    if (every === "off") { $("rv-repedit").style.display = "none"; return post("repeat", {every}); }
    const last = state.thread.filter(m => m.role === "user").pop();
    if (!repEditing()) $("rv-reptext").value =
      $("rv-text").value.trim() || (state.repeat && state.repeat.text) || (last ? last.text : "");
    $("rv-replabel").textContent = `Message to send every ${every} (first run one ${every} from now; each run starts a fresh chat):`;
    $("rv-repedit").style.display = "block";
    $("rv-reptext").focus();
  };
  $("rv-repsave").onclick = () => {
    const text = $("rv-reptext").value.trim();
    if (!text) return alert("Write the message to repeat.");
    $("rv-repedit").style.display = "none";
    post("repeat", {every: $("rv-every").value, text});
  };
  $("rv-repcancel").onclick = repClose;
  $("rv-read").onclick = () => post("status", {status: "read"});
  $("rv-new").onclick = () => { scrollToEnd = true; post("newchat", {}); };
  $("rv-close").onclick = () => post("status", {status: "closed"});
  $("rv-compact").onclick = () => { scrollToEnd = true; post("compact", {}); };
  $("rv-cancel").onclick = () => { if (confirm("Stop this agent?")) { scrollToEnd = true; post("cancel", {}); } };
  const grant = always => post("grant", {rules: state.denials.filter(d => !d.blocked && !d.granted).flatMap(d => d.rules), always});
  // Highlight the blocks that differ from index.html as it was before the agent's latest edit:
  // a leaf block (paragraph, list item, cell, heading, image...) whose content isn't in the old copy.
  const BLOCKS = "p,li,h1,h2,h3,h4,h5,h6,pre,blockquote,figcaption,caption,td,th,dt,dd,summary,img,svg,video,iframe,div";
  const SKIP = "#dirai-status,[id^=rv-],[id^=na-],.rv-removed,script,style";
  const sig = el => el.tagName + "|" + (/^(IMG|VIDEO|IFRAME)$/.test(el.tagName) ? el.getAttribute("src")
    : el.tagName === "SVG" || el.tagName === "svg" ? el.outerHTML.length + ":" + el.textContent.slice(0, 200)
    : el.textContent.replace(/\s+/g, " ").trim());
  // the folder's files (files.js) aren't part of index.html: never compared with it
  const leaves = root => [...root.querySelectorAll(BLOCKS)].filter(el =>
    !el.closest(SKIP + ",#dirai-files") && !(el.parentElement && el.parentElement.closest("svg")) &&
    !el.querySelector(BLOCKS) && (el.textContent.trim() || /^(IMG|VIDEO|IFRAME|svg|SVG)$/.test(el.tagName)));
  function highlight() {
    fetch("/_review/prev?agent=" + encodeURIComponent(AGENT)).then(r => r.ok ? r.text() : null).then(old => {
      if (old === null) return;
      const before = leaves(new DOMParser().parseFromString(old, "text/html").body);
      const free = {};     // signature -> indexes of old blocks not yet matched to a current one
      before.forEach((el, i) => (free[sig(el)] = free[sig(el)] || []).push(i));
      const twin = new Map();   // old block -> the current block with the same content
      const changed = leaves(document.body).filter(el => {
        const k = free[sig(el)];
        return k && k.length ? (twin.set(before[k.shift()], el), false) : true;
      });
      changed.forEach(el => el.classList.add("rv-changed"));
      const removed = showRemoved(before, twin);
      if (changed.length || removed) $("rv-hl").style.display = "";
    });
  }
  // Old blocks with no current twin were removed: show each run of them, collapsed, after the
  // current twin of the old block just before it (or before the first kept block, if none is before).
  function showRemoved(before, twin) {
    let runs = 0, run = [], after = null;
    const placed = new Map();   // spot -> the last box put after it
    const flush = next => {
      if (!run.length) return;
      const box = document.createElement("details");
      box.className = "rv-removed";
      box.innerHTML = `<summary>Removed (${run.length} block${run.length === 1 ? "" : "s"})</summary><div></div>`;
      run.forEach(el => {
        // a cell, list item... out of its table or list: keep only what's inside it
        const part = /^(TD|TH|LI|DT|DD|CAPTION|FIGCAPTION|SUMMARY)$/.test(el.tagName) ? document.createElement("div") : document.importNode(el, false);
        el.childNodes.forEach(n => part.appendChild(document.importNode(n, true)));
        part.querySelectorAll("script").forEach(x => x.remove());
        [part, ...part.querySelectorAll("[id]")].forEach(x => x.removeAttribute("id"));   // the page's ids stay unique
        box.lastChild.appendChild(part);
      });
      // never inside a table, or a <details> that may be closed; runs after the same spot keep their order
      const spot = el => el.closest("table") || el.closest("details") || el;
      if (after) { const at = spot(after); (placed.get(at) || at).after(box); placed.set(at, box); }
      else if (next) spot(next).before(box);
      else document.body.prepend(box);
      runs++, run = [];
    };
    before.forEach(el => {
      if (twin.has(el)) { flush(twin.get(el)); after = twin.get(el); }
      else run.push(el);
    });
    flush(null);
    return runs;
  }
  $("rv-hl").onclick = () => {
    $("rv-hl").textContent = document.body.classList.toggle("rv-nohl") ? "Show changes" : "Hide changes";
  };
  highlight();

  // Text the owner selects in index.html goes with their next message (quoted, with the nearest heading;
  // the server adds the source lines). Selecting while the panel is open attaches it right away;
  // otherwise the "Ask AI about this" button next to the selection does. Text only.
  const SEL_MAX = 4000;
  let pinned = null;
  const lineCount = t => t.split("\n").filter(l => l.trim()).length;
  function selHtml(sel) {
    const where = (sel.file ? ` · ${esc(sel.file)}` : "") + (sel.heading ? ` · near "${esc(sel.heading)}"` : "") +
      (sel.lines ? ` · line${sel.lines[0] === sel.lines[1] ? " " + sel.lines[0] : "s " + sel.lines[0] + "–" + sel.lines[1]}` : "");
    return `<details class="rv-sel"><summary>📎 Selected text (${lineCount(sel.text)} line${lineCount(sel.text) === 1 ? "" : "s"})${where}</summary>` +
      `<div class="rv-quote">${esc(sel.text)}</div></details>`;
  }
  function pin(sel) {
    pinned = sel;
    const chip = $("rv-chip");
    chip.style.display = sel ? "flex" : "none";
    if (!sel) return chip.innerHTML = "";
    chip.innerHTML = `<details><summary>📎 "${esc(sel.text.replace(/\s+/g, " ").slice(0, 70))}${sel.text.length > 70 ? "…" : ""}" ` +
      `(${sel.file ? esc(sel.file) + ", " : ""}${lineCount(sel.text)} line${lineCount(sel.text) === 1 ? "" : "s"}${sel.cut ? ", cut to " + SEL_MAX + " characters" : ""})</summary>` +
      `<div class="rv-quote">${esc(sel.text)}</div></details><button id="rv-unsel" title="Don't send the selection">&times;</button>`;
    $("rv-unsel").onclick = () => pin(null);
  }
  // {text, heading} of a selection in index.html, or {text, file, lines, rendered} of one in a file of
  // the folder shown at its end (files.js: every line, or rendered .md block, carries its numbers); else null
  function indexSelection() {
    const s = window.getSelection();
    if (!s || s.isCollapsed || !s.rangeCount) return null;
    const r = s.getRangeAt(0), node = n => n.nodeType === 1 ? n : n.parentElement;
    if ([r.startContainer, r.endContainer].some(n => !node(n) || node(n).closest(SKIP + ",#rv-btn,#rv-ask"))) return null;
    let text = s.toString().replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
    if (!text) return null;
    const cut = text.length > SEL_MAX;
    if (cut) text = text.slice(0, SEL_MAX);
    let heading = "";
    document.querySelectorAll("h1,h2,h3,h4,h5,h6").forEach(h => {
      if (!h.closest(SKIP) && h.compareDocumentPosition(r.startContainer) & Node.DOCUMENT_POSITION_FOLLOWING)
        heading = h.textContent.replace(/\s+/g, " ").trim().slice(0, 200);
    });
    const line = n => node(n).closest("#dirai-files [data-line]");
    const first = line(r.startContainer);
    let last = line(r.endContainer);
    // a selection that ends at the very start of a line (triple click, dragging to the line's edge) ends on the one before
    if (last && last !== first && r.endOffset === 0) {   // (skipping a box of removed lines)
      let prev = last.previousElementSibling;
      while (prev && !prev.dataset.line) prev = prev.previousElementSibling;
      if (prev) last = prev;
    }
    const file = el => el && el.closest("details[data-file]").dataset.file;
    if (first || last) {
      if (!first || !last || file(first) !== file(last)) return null;   // half in a file, or across two
      // a rendered .md block spans lines (data-line-end); the server narrows them to the selected text
      return {text, heading: "", file: file(first), lines: [+first.dataset.line, +(last.dataset.lineEnd || last.dataset.line)],
              rendered: !!first.dataset.rendered, cut, rect: r.getBoundingClientRect()};
    }
    return {text, heading, cut, rect: r.getBoundingClientRect()};
  }
  function onSelect() {
    const sel = indexSelection(), ask = $("rv-ask");
    if (!sel) return ask.style.display = "none";
    if ($("rv-panel").classList.contains("open")) { ask.style.display = "none"; return pin(sel); }
    ask.style.left = Math.min(sel.rect.right + scrollX, scrollX + innerWidth - 150) + "px";
    ask.style.top = sel.rect.bottom + scrollY + 6 + "px";
    ask.style.display = "block";
    ask.sel = sel;
  }
  document.addEventListener("mouseup", () => setTimeout(onSelect));   // after the click clears or sets it
  document.addEventListener("keyup", e => { if (e.shiftKey) onSelect(); });
  $("rv-ask").onmousedown = e => e.preventDefault();   // keep the selection in index.html
  $("rv-ask").onclick = () => {
    pin($("rv-ask").sel); $("rv-ask").style.display = "none";
    if (!$("rv-panel").classList.contains("open")) $("rv-btn").click();
    $("rv-text").focus();
  };
  $("rv-once").onclick = () => grant(false);
  $("rv-always").onclick = () => grant(true);
  try { if (sessionStorage.getItem("rv-open")) { sessionStorage.removeItem("rv-open"); $("rv-btn").click(); } } catch (e) {}
  refresh();
})();
