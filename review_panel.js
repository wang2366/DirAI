// Review panel injected by html_server.py into index.html pages (owner only).
(function () {
  const PAGE = document.currentScript.dataset.page;
  const FILE = document.currentScript.dataset.file || "index.html";   // plan_*.html pages share the folder's thread
  const api = (path, body) => fetch("/_review/" + path, body === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json", "X-Review": "1"},
    body: JSON.stringify(Object.assign({page: PAGE}, body)),
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
  .rv-closed{background:#666}.rv-none{background:#999}
  #rv-thread{overflow:auto;padding:10px 12px;flex:1}
  .rv-msg{margin:0 0 10px;padding:8px 10px;border-radius:8px;white-space:pre-wrap;word-wrap:break-word}
  .rv-user{background:#eef4ff}.rv-claude{background:#f3f3f3}.rv-system{background:#fff6e0;font-size:13px}
  .rv-meta{font-size:11px;color:#777;margin-bottom:3px}
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
  #rv-ctx.warn{color:#b26b00;font-weight:600} #rv-ctx.high{color:#c62828;font-weight:600}
  #rv-ctxnote{display:none;margin:0 0 6px;padding:6px 8px;border-radius:6px;background:#fff6e0;font-size:12.5px}`;
  document.head.insertAdjacentHTML("beforeend", "<style>" + css + "</style>");
  document.body.insertAdjacentHTML("beforeend", `
  <button id="rv-btn">AI assistant</button>
  <div id="rv-panel">
    <div id="rv-head"><b>AI assistant</b><span id="rv-ctx" title="tokens in this session's context, resent with every message"></span><span id="rv-status" class="rv-pill rv-none">none</span>
      <button id="rv-x" style="border:0;background:none;font-size:18px;cursor:pointer">&times;</button></div>
    <div id="rv-thread"></div>
    <div id="rv-denials"><b>Claude was blocked from:</b><ul id="rv-dlist"></ul>
      <div class="rv-row"><button id="rv-once">Allow once (this page)</button><button id="rv-always">Always allow</button></div></div>
    <div id="rv-foot"><div id="rv-ctxnote"></div><textarea id="rv-text" placeholder="Message the AI assistant about this page..."></textarea>
      <div class="rv-row"><button id="rv-save" class="primary">Send</button>
        <button id="rv-read">Mark read</button><button id="rv-new" title="Your next message starts a fresh session (the assistant re-reads the page, todo.md and the last few messages)">New chat</button><button id="rv-compact" title="Summarize the conversation so far (Claude Code /compact); the session continues with a much smaller context">Compact</button><button id="rv-close">TaskDone</button></div></div>
  </div>`);

  const $ = id => document.getElementById(id);
  let state = null, timer = null;
  // redraw the thread only when it changed, and keep the reader's scroll position;
  // jump to the newest message only on first load and after the owner sends something
  let shownThread = null, scrollToEnd = true;
  const LABEL = {closed: "TaskDone"};   // shown name for a stored status
  const esc = s => s.replace(/[&<>]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;"}[c]));

  function render(st) {
    state = st;
    const s = st.status;
    $("rv-status").textContent = LABEL[s] || s; $("rv-status").className = "rv-pill rv-" + s;
    $("rv-btn").textContent = "AI assistant" + (s === "unread" ? " •" : s === "working" || s === "queued" ? " …" : "");
    const threadKey = JSON.stringify(st.thread);
    if (threadKey !== shownThread) {
      const box = $("rv-thread"), top = box.scrollTop;
      box.innerHTML = st.thread.map(m =>
        `<div class="rv-msg rv-${m.role}"><div class="rv-meta">${m.role} · ${m.time}${m.cost != null ? " · $" + m.cost : ""}</div>${esc(m.text)}</div>`
      ).join("") || '<div class="rv-meta">No comments yet.</div>';
      shownThread = threadKey;
      if (!$("rv-panel").classList.contains("open")) {}        // hidden: scroll when it opens
      else if (scrollToEnd) { box.scrollTop = box.scrollHeight; scrollToEnd = false; }
      else box.scrollTop = top;
    }
    const busy = s === "working" || s === "queued";
    ["rv-save", "rv-read", "rv-close", "rv-new"].forEach(id => $(id).disabled = busy);
    $("rv-new").disabled = busy || !st.session_id;   // nothing to start over from yet
    $("rv-compact").disabled = busy || !st.session_id;
    const ctx = st.context, level = ctx == null ? "" : ctx >= st.context_high ? "high" : ctx >= st.context_warn ? "warn" : "";
    $("rv-ctx").textContent = ctx == null ? "" : "context " + Math.round(ctx / 1000) + "K";
    $("rv-ctx").className = level;
    $("rv-ctxnote").style.display = level && !busy ? "block" : "none";
    if (level) $("rv-ctxnote").textContent = `This conversation is ${Math.round(ctx / 1000)}K tokens, and every message resends all of it, ` +
      `which uses up your Claude limits faster${level === "high" ? " (a lot faster at this size)" : ""}. ` +
      "Compact summarizes it and keeps the session; New chat starts over from the page and the last few messages.";
    const grantable = st.denials.filter(d => !d.blocked && !d.granted);
    // one line per denial; click to see the full command
    const denialKey = JSON.stringify(st.denials);   // same idea: don't collapse opened entries
    if (denialKey !== render.shownDenials) render.shownDenials = denialKey, $("rv-dlist").innerHTML = st.denials.map(d =>
      `<li><details><summary>${d.blocked ? '<i style="color:#a00">always blocked, run it yourself:</i> '
        : d.granted ? '<i style="color:#a00">already allowed, refused by a built-in safety check (shell constructs like $( ), loops or ..); ask the assistant to do it with a script:</i> '
        : ""}${esc(d.text.slice(0, 120))}</summary>` +
      `<pre>${esc(d.text)}</pre></details></li>`).join("");
    $("rv-once").style.display = $("rv-always").style.display = grantable.length ? "" : "none";
    $("rv-denials").style.display = st.denials.length && !busy ? "block" : "none";
    clearTimeout(timer);
    if (busy) timer = setTimeout(refresh, 4000);
  }
  const refresh = () => api("state?page=" + encodeURIComponent(PAGE)).then(render);
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
    post("comment", {text, file: FILE});
  };
  $("rv-read").onclick = () => post("status", {status: "read"});
  $("rv-new").onclick = () => { scrollToEnd = true; post("newchat", {}); };
  $("rv-close").onclick = () => post("status", {status: "closed"});
  $("rv-compact").onclick = () => { scrollToEnd = true; post("compact", {}); };
  const grant = always => post("grant", {rules: state.denials.filter(d => !d.blocked && !d.granted).flatMap(d => d.rules), always});
  $("rv-once").onclick = () => grant(false);
  $("rv-always").onclick = () => grant(true);
  refresh();
})();
