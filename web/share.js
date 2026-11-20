// The Share pill (proposal 72, lib/shares.py), next to Chat at the bottom right of your agent's page.
// Its popover is a checklist while GitHub isn't ready on this machine (each failed check has a button that
// DirAI runs), then the Share options: repos to share to, mode, children, the check before push, Publish.
// On someone else's agent (www/shares/…, data-shared) it is "From <owner> · read-only" instead, with Copy to
// my tree, Use as colleague and Ask owner. A copy of a shared agent shows when its owner published again.
(() => {
  const me = document.currentScript, agent = me.dataset.agent || "", shared = me.dataset.shared === "1";
  const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const post = body => fetch("/_review/share", {method: "POST", headers: {"Content-Type": "application/json", "X-Review": "1"},
    body: JSON.stringify(Object.assign({agent}, body))}).then(r => r.json()).catch(e => ({error: String(e)}));
  const get = q => fetch("/_review/share?agent=" + encodeURIComponent(agent) + (q || "")).then(r => r.ok ? r.json() : null).catch(() => null);
  document.head.insertAdjacentHTML("beforeend", `<style>
  #rv-share{position:fixed;bottom:16px;right:90px;z-index:99999;padding:8px 14px;border-radius:20px;border:1px solid #c77c1e;
    background:#fff8e1;color:#222;font:600 14px system-ui;cursor:pointer}
  #rv-share.grey{border-color:#bbb;background:#e5e7eb;color:#888}
  #rv-share .dot{display:inline-block;width:8px;height:8px;border-radius:4px;background:#c77c1e;margin-left:6px}
  #rv-share-pop{position:fixed;bottom:60px;right:16px;z-index:99999;width:440px;max-width:calc(100vw - 32px);max-height:70vh;
    overflow:auto;background:#fff;color:#222;border:1px solid #c77c1e;border-radius:8px;padding:10px 12px;font:13px system-ui;
    box-shadow:0 4px 16px #0003;display:none}
  #rv-share-pop.open{display:block} #rv-share-pop h4{margin:0 0 6px;font-size:14px}
  #rv-share-pop .row{display:flex;gap:6px;align-items:baseline;margin:3px 0} #rv-share-pop .row .f{color:#666;font-size:12px;margin-left:auto}
  #rv-share-pop .fix{background:#fdecea;border:1px solid #e6b0aa;border-radius:5px;padding:6px 8px;margin:4px 0 6px 22px;font-size:12px}
  #rv-share-pop .run{background:#fff8e1;border:1px solid #c77c1e}
  #rv-share-pop code{font:11px Menlo,Consolas,monospace;background:#f3f4f6;padding:1px 3px;border-radius:3px;overflow-wrap:anywhere}
  #rv-share-pop button{padding:2px 9px;border-radius:4px;border:1px solid #2563a8;background:#2563a8;color:#fff;cursor:pointer;font:12px system-ui;margin:2px 4px 2px 0}
  #rv-share-pop button.gray{background:none;color:#222;border-color:#888} #rv-share-pop button:disabled{opacity:.5;cursor:default}
  #rv-share-pop .dim{color:#666;font-size:12px} #rv-share-pop .warn{color:#c77c1e;font-size:12px} #rv-share-pop .err{color:#c0392b;font-size:12px}
  #rv-share-pop input[type=text]{font:12px system-ui;padding:1px 4px;width:150px}
  #rv-share-pop .sec{border-top:1px solid #eee;margin-top:8px;padding-top:6px}
  #rv-share-pop .mk{display:inline-block;width:16px;height:16px;border-radius:8px;color:#fff;font:bold 11px/16px system-ui;text-align:center;flex:none}
  #rv-share-upd{position:fixed;bottom:60px;right:16px;z-index:99998;background:#eef7f0;border:1px solid #2f7d4a;border-radius:6px;
    padding:6px 10px;font:13px system-ui;max-width:420px}
  #rv-share-upd button{margin-left:6px}</style>`);
  const pill = document.createElement("button"); pill.id = "rv-share"; pill.textContent = shared ? "From …" : "Share";
  const pop = document.createElement("div"); pop.id = "rv-share-pop";
  document.body.append(pill, pop);
  // left of Chat (panel.js may add it after us)
  const place = () => { const c = document.getElementById("rv-btn"); pill.style.right = (c && c.offsetWidth ? c.offsetWidth + 24 : 16) + "px"; };
  place(); setTimeout(place, 500); window.addEventListener("resize", place);
  let st = null, poll = null, msg = "";
  const MARK = {true: ["#2f7d4a", "✓"], false: ["#c0392b", "✗"], null: ["#bbb", "–"], run: ["#c77c1e", "…"]};
  const mark = ok => { const [c, t] = MARK[ok]; return `<span class="mk" style="background:${c}">${t}</span>`; };

  // --- someone else's agent ----------------------------------------------------------------------
  if (shared) {
    get().then(r => {
      const s = r && r.shared;
      if (!s) { pill.textContent = "Shared agent · read-only"; return; }
      pill.textContent = `From ${s.owner} · read-only`;
      const issue = `${s.web || "https://github.com/" + s.full}/issues/new?title=${encodeURIComponent("[" + s.slug + "] question")}` +
        `&body=${encodeURIComponent("About agents/" + s.slug + " (published " + s.published + "):\n\n")}`;
      pop.innerHTML = `<h4>${esc(s.owner)}'s agent · published ${esc(s.published)}</h4>
        <div class="dim">From ${esc(s.full)}. Read-only here, and no Chat: it isn't yours to run.</div>
        <div class="sec"><b>Copy to my tree</b> <span class="dim">makes it yours; you're told when ${esc(s.owner)} publishes again</span><br>
          <input type="text" data-dest value="copies/${esc(s.slug)}"> <button data-copy>Copy</button></div>
        <div class="sec"><b>Use as colleague</b> <span class="dim">paste this page's link in your agent's Colleagues box</span><br>
          <button class="gray" data-link>Copy link</button></div>
        <div class="sec"><b>Ask owner</b> <span class="dim">a new issue in their repo; GitHub tells them</span><br>
          <button data-ask>Open an issue</button></div><div class="err" data-msg></div>`;
      pop.querySelector("[data-copy]").onclick = e => {
        e.target.disabled = true;
        post({op: "copy", dest: pop.querySelector("[data-dest]").value.trim()}).then(r => {
          e.target.disabled = false;
          if (r.error) pop.querySelector("[data-msg]").textContent = r.error; else location.href = r.url;
        });
      };
      pop.querySelector("[data-link]").onclick = e => {
        navigator.clipboard && navigator.clipboard.writeText(location.origin + location.pathname);
        e.target.textContent = "Copied";
      };
      pop.querySelector("[data-ask]").onclick = () => window.open(issue, "_blank", "noopener");
    });
    pill.onclick = () => pop.classList.toggle("open");
    return;
  }

  // --- your agent ----------------------------------------------------------------------------------
  function look(ready, sharedTo, changed) {
    pill.classList.toggle("grey", ready === false);
    pill.title = ready === false ? "Sharing needs GitHub on this machine: click for the steps" :
      sharedTo.length ? "Shared to " + sharedTo.join(", ") : "Share this agent";
    pill.innerHTML = (sharedTo.length ? "Shared" : "Share") + (changed ? ` · ${changed} changed<span class="dot"></span>` : "");
  }
  function origin(o) {     // a copy of someone's agent: their newer version
    let el = document.getElementById("rv-share-upd");
    if (!o || !o.files || !o.files.length) { if (el) el.remove(); return; }
    if (!el) { el = document.createElement("div"); el.id = "rv-share-upd"; document.body.append(el); }
    const who = o.repo.split("/")[0];
    el.innerHTML = `${esc(who)} published a newer version: ${o.files.length} file${o.files.length === 1 ? "" : "s"} changed
      <button class="gray" data-files>Show files</button><button data-upd>Update</button><div class="dim" data-out></div>`;
    el.querySelector("[data-files]").onclick = () => el.querySelector("[data-out]").textContent = o.files.join(", ");
    el.querySelector("[data-upd]").onclick = () => post({op: "update_copy"}).then(r => {
      el.querySelector("[data-out]").textContent = r.error || `Updated ${r.updated.length}` +
        (r.kept.length ? `; kept yours for ${r.kept.join(", ")} (theirs beside as .theirs)` : "");
      setTimeout(() => location.reload(), 2500);
    });
  }
  get("&quick=1").then(q => {
    if (!q) return;
    look(q.ready, q.shared || [], 0);
    origin(q.origin);
    if (q.ready && q.shared && q.shared.length) load();     // the "· 3 changed" count
  });

  function load() {
    return get().then(r => {
      if (!r) return;
      st = r;
      const changed = Math.max(0, ...r.repos.filter(x => x.shared).map(x => x.changed || 0));
      look(r.ready, r.repos.filter(x => x.shared).map(x => x.full), changed);
      origin(r.origin);
      if (pop.classList.contains("open")) draw();
      clearTimeout(poll);
      if (r.job && r.job.state === "running") poll = setTimeout(load, 2000);
    });
  }
  pill.onclick = () => {
    pop.classList.toggle("open");
    if (pop.classList.contains("open")) { pop.innerHTML = '<div class="dim">Checking GitHub on this machine…</div>'; load(); }
  };
  const fixOp = op => op === "open_org" ? null : op;
  function jobBox(j, op) {
    if (!j || j.op !== op) return "";
    if (j.state === "running" && op === "gh_login") return `<div class="fix run">1. Copy this code: <code>${esc(j.code || "…")}</code>
      <button class="gray" data-copycode="${esc(j.code || "")}">Copy</button><br>2. Enter it on GitHub and approve:
      <button data-open="${esc(j.url)}">Open github.com/login/device</button><div class="dim">This turns green by itself when GitHub says yes.</div></div>`;
    if (j.state === "running") return `<div class="fix run">Running… <span class="dim">${esc(j.out || "")}</span></div>`;
    if (j.state === "failed") return `<div class="err">Failed: ${esc(j.out)}</div>`;
    return "";
  }
  function checkRow(c, first) {
    const ok = st.job && st.job.state === "running" && c.fixes.some(f => f.op === st.job.op) ? "run" : c.ok;
    let s = `<div class="row">${mark(ok)} <span${c.ok === false ? ' style="color:#c0392b;font-weight:600"' : ""}>${c.n} ${esc(c.name)}</span><span class="f">${esc(c.ok == null ? "waits for an earlier step" : c.found)}</span></div>`;
    if (c.ok === false) {
      const run = st.job && st.job.state === "running";
      s += `<div class="fix">` + c.fixes.map(f => `<button ${first && !run ? "" : "disabled"} data-fix="${esc(f.op)}"${f.url ? ` data-open="${esc(f.url)}"` : ""}>${esc(f.label)}</button>` +
        `<div class="dim">runs: <code>${esc(f.runs)}</code></div>`).join("") + "</div>";
      s += c.fixes.map(f => jobBox(st.job, f.op)).join("");
    }
    return s;
  }
  function draw() {
    if (!st) return;
    const c = st.checks;
    let h = `<h4>Share ${esc(agent.split("/").pop() || "this tree")}</h4>`;
    // Share as: the github.com account sharing goes through on every machine, whatever this one's own login is
    const acc = c[1].accounts || [], want = c[1].chosen || c[0].login;
    if (acc.length || want) {
      const opts = acc.concat(want && !acc.includes(want) ? [want] : []).map(a =>
        `<option value="${esc(a)}" ${a === want ? "selected" : ""}>${esc(a)}${acc.includes(a) ? "" : " (not logged in here)"}</option>`);
      h += `<div class="row"><b>Share as</b> <select data-account>${opts.join("")}<option value="+">+ Add another github.com account…</option></select>
        <span class="f">github.com, on every machine</span></div>`;
      if (c[1].ok !== false) h += jobBox(st.job, "gh_login");    // adding an account (else shown under check 2)
    }
    if (!st.ready) {
      const n = c.slice(0, 2).filter(x => x.ok).length, first = c.slice(0, 2).findIndex(x => x.ok === false);
      h += `<div class="dim">Sharing needs gh on this machine: ${n} of 2 ready. Only the first open step's button is active.</div>`;
      h += c.slice(0, 2).map((x, i) => checkRow(x, i === first)).join("");
    } else if (!st.repos.length && !(st.hidden || []).length) {
      const first = c.findIndex(x => x.ok === false);
      h += `<div class="dim">GitHub is ready (${esc(c[1].found)}). Set up sharing, once:</div>` + c.slice(2).map(x => checkRow(x, c.indexOf(x) === first)).join("");
      if (c[2].ok && !c[3].ok) h += `<div class="dim">Repo name: <input type="text" data-rname value="${esc(c[0].login || "")}_agent_repo"></div>`;
    } else {
      h += `<div class="dim"><b>Share to</b> · a repo's readers see every agent shared to it</div>`;
      // each repo: its name, and where it is when that isn't your github.com org (another org, another server, internal)
      const where = r => (r.host && r.host !== "github.com" ? `${r.owner} @ ${r.host}` : (st.places[0] && st.places[0].orgs[0] === r.owner ? "" : r.owner)) +
        (r.visibility === "internal" ? " · internal: all of " + r.host + " reads it" : "");
      h += st.repos.map(r => `<div class="row"><input type="checkbox" data-repo="${esc(r.full)}" ${r.shared ? "checked" : ""}>
        <code>${esc(r.full.split("/").pop())}</code> <span class="dim">${esc(where(r))}${where(r) ? " · " : ""}${esc((r.readers || []).map(x => x.login).join(" · ") || (r.visibility === "internal" ? "" : "no readers yet"))}</span>
        <span class="f">${r.shared ? "published " + esc((r.published || "").slice(5, 10)) + (r.changed ? " · " + r.changed + " changed" : "") : "not shared"}</span></div>
        <div class="row" style="margin-left:22px"><input type="text" data-reader="${esc(r.full)}" placeholder="login"><button class="gray" data-addreader="${esc(r.full)}">+ add reader</button>
          <button class="gray" data-hide="${esc(r.full)}" title="Take it off this list (in this tree only); the repo on GitHub, its agents and its readers stay">Remove from list</button></div>`).join("");
      const hid = st.hidden || [];      // removed from the list: each can be put back
      if (hid.length) h += `<details class="dim"><summary>${hid.length} removed from this list</summary>` + hid.map(r =>
        `<div class="row"><code>${esc(r.full.split("/").pop())}</code>${r.shared ? " · this agent is in it" : ""}<button class="gray" data-unhide="${esc(r.full)}">Put back</button></div>`).join("") + "</details>";
      // + new repo: on which GitHub server (each one gh is logged in to here), in which org, private or internal
      const pl = st.places || [];
      h += `<div class="sec"><b>+ new repo</b> <span class="dim">for another audience</span><div class="row">
        <input type="text" data-rname placeholder="e.g. kubis">
        <select data-rhost>${pl.map((p, i) => `<option value="${i}">${esc(p.host)}</option>`).join("")}</select>
        <select data-rorg></select><select data-rvis></select>
        <button class="gray" data-fix="create_repo">Create</button></div><div class="dim" data-rnote></div></div>`;
      h += `<div class="sec">Mode: <select data-mode><option value="hand">by hand</option><option value="run" ${st.mode === "run" ? "selected" : ""}>after it changes (checked every 10 min)</option></select></div>`;
      // the agents Publish sends and Unshare removes: this one (with children: its own tick box) and the ticked children
      if (st.children.length) h += `<div class="sec"><b>Agents</b>` +
        (st.children.length > 1 ? ` <button class="gray" data-allchildren></button>` : "") +
        `<div class="row"><input type="checkbox" data-self checked> <code>${esc(agent.split("/").pop() || "this tree")}/</code> <span class="dim">this page</span></div>` +
        st.children.map(ch =>
        `<div class="row"><input type="checkbox" data-child="${esc(ch.agent)}" ${ch.shared.length ? "checked" : ""}> <code>${esc(ch.agent.split("/").pop())}/</code> <span class="dim">${esc(ch.title)}${ch.shared.length ? " · shared" : ""}</span></div>`).join("") + "</div>";
      const any = st.repos.some(r => r.shared) || st.children.some(ch => ch.shared.length);
      h += `<div class="sec dim">${st.files} files, ${(st.bytes / 1000).toFixed(0)} kB` + (st.left_out.length ? ` · left out: ${esc(st.left_out.join(", "))} <span title="Left out of every Publish: hidden files, tmp/, *.log, and files over 1 MB">ⓘ</span>` : "") + "</div>";
      h += st.warnings.map(w => `<div class="warn">! ${esc(w)}</div>`).join("");
      h += `<div class="sec"><button data-publish>Publish</button>` +
        (any ? `<button class="gray" data-unshare title="Remove the ticked agents from the ticked repos">Unshare…</button>` : "") +
        `<button class="gray" data-close>Cancel</button></div>`;
      h += jobBox(st.job, "create_repo") + jobBox(st.job, "add_reader");
    }
    if (st.copy) h += `<div class="sec"><b>A copy</b> <span class="dim">made by Copy to my tree (inside copies/)</span><br>
      <button class="gray" data-rmcopy>Remove this copy…</button> <span class="dim">the owner's repo is untouched</span></div>`;
    h += `<div class="sec"><button class="gray" data-check>Check again</button><span class="err" data-msg>${esc(msg)}</span></div>`;
    pop.innerHTML = h;
    const rm = pop.querySelector("[data-rmcopy]");
    if (rm) rm.onclick = () => {       // what goes, from the server's own look at the folder (copy_info)
      const c = st.copy, kb = (c.bytes / 1000).toFixed(0);
      if (c.running) { msg = "A run is going in this agent: stop it first."; draw(); return; }
      const lines = [`Remove ${agent}/ from this tree: ${c.files} files, ${kb} kB` + (c.children.length ? `, and ${c.children.length} agent(s) inside it` : "") + ".",
        "It is moved to www/trash/, not deleted."];
      if (c.edited && c.edited.length) lines.push(`! You changed ${c.edited.length} file(s) since the copy: ${c.edited.slice(0, 5).join(", ")}${c.edited.length > 5 ? ", …" : ""}`);
      if (c.published_to.length) lines.push("! You published it: it is unshared from " + c.published_to.join(", ") + " first.");
      if (c.used_by.length) lines.push("! Used as a colleague by: " + c.used_by.join(", ") + " (removed from theirs).");
      if (confirm(lines.join("\n"))) post({op: "remove_copy"}).then(r => { if (r.error) { msg = r.error; draw(); } else location.href = r.url; });
    };
    pop.querySelectorAll("[data-open]").forEach(b => { if (!b.dataset.fix) b.onclick = () => window.open(b.dataset.open, "_blank", "noopener"); });
    pop.querySelectorAll("[data-copycode]").forEach(b => b.onclick = () => navigator.clipboard && navigator.clipboard.writeText(b.dataset.copycode));
    pop.querySelectorAll("[data-fix]").forEach(b => b.onclick = () => {
      if (b.dataset.open) window.open(b.dataset.open, "_blank", "noopener");
      const op = fixOp(b.dataset.fix);
      if (!op) return;
      const name = pop.querySelector("[data-rname]"), body = {op, name: name ? name.value.trim() : ""};
      const hs = pop.querySelector("[data-rhost]");
      if (op === "create_repo" && hs && st.places[hs.value]) {
        const p = st.places[hs.value];
        Object.assign(body, {host: p.host, org: pop.querySelector("[data-rorg]").value, visibility: pop.querySelector("[data-rvis]").value});
      }
      if (op === "create_repo" && !confirm(`Create ${body.org ? body.org + "/" : ""}${(body.name || "…").replace(/_agent_repo$/, "")}_agent_repo` +
        (body.host ? ` on ${body.host}, ${body.visibility}` : "") + "? This changes your GitHub account.")) return;
      act(body);
    });
    const hs = pop.querySelector("[data-rhost]");
    if (hs) {     // the org and visibility lists follow the server picked
      const fill = () => {
        const p = st.places[hs.value] || {orgs: []}, dotcom = p.host === "github.com";
        pop.querySelector("[data-rorg]").innerHTML = p.orgs.map(o => `<option>${esc(o)}</option>`).join("") || "<option value=''>no org</option>";
        pop.querySelector("[data-rvis]").innerHTML = `<option value="private">private: readers you add</option>` +
          (dotcom ? "" : `<option value="internal">internal: everyone on ${esc(p.host)} reads</option>`);
        pop.querySelector("[data-rnote]").textContent = p.orgs.length ? "" : `You're in no org on ${p.host}: readers of a repo under your own name can push, so make or join an org first.`;
      };
      hs.onchange = fill; fill();
    }
    pop.querySelectorAll("[data-hide]").forEach(b => b.onclick = () => {
      const r = st.repos.find(x => x.full === b.dataset.hide) || {};
      if (!r.shared || confirm(`This agent is published in ${b.dataset.hide.split("/").pop()} and stays there (use Unshare… to take it out).\nRemove the repo from this list anyway?`))
        act({op: "hide", repo: b.dataset.hide});
    });
    pop.querySelectorAll("[data-unhide]").forEach(b => b.onclick = () => act({op: "unhide", repo: b.dataset.unhide}));
    pop.querySelectorAll("[data-addreader]").forEach(b => b.onclick = () => {
      const login = pop.querySelector(`[data-reader="${b.dataset.addreader}"]`).value.trim();
      if (login && confirm(`Give ${login} read access to ${b.dataset.addreader} (every agent in it)?`)) act({op: "add_reader", repo: b.dataset.addreader, login});
    });
    const self = pop.querySelector("[data-self]");
    const un = pop.querySelector("[data-unshare]");   // the ticked agents from the ticked repos, like Publish
    if (un) un.onclick = () => {
      const repos = [...pop.querySelectorAll("[data-repo]:checked")].map(x => x.dataset.repo);
      const me = !self || self.checked;
      const kids = [...pop.querySelectorAll("[data-child]:checked")].map(x => x.dataset.child);
      const gone = [];
      for (const r of repos) {    // what goes from each repo: this agent takes the children inside it along
        const mine = me && st.repos.some(x => x.full === r && x.shared);
        const items = (mine ? [agent.split("/").pop() || "this tree"] : []).concat(
          st.children.filter(ch => ch.shared.includes(r) && (mine || kids.includes(ch.agent))).map(ch => ch.agent.split("/").pop()));
        if (items.length) gone.push(`${r.split("/").pop()}:${items.map(x => x + "/").join(", ")}`);
      }
      if (!gone.length) { msg = "Nothing to unshare: none of the ticked agents is in the ticked repos."; draw(); return; }
      if (confirm(`Remove from GitHub (its old commits still hold them):\n${gone.join("\n")}`))
        act({op: "unshare", repos, agents: (me ? [agent] : []).concat(kids)});
    };
    const as = pop.querySelector("[data-account]");
    if (as) as.onchange = () => {
      if (as.value === "+") act({op: "gh_login"});
      else { pop.innerHTML = '<div class="dim">Checking GitHub as ' + esc(as.value) + "…</div>"; act({op: "account", account: as.value}); }
    };
    const all = pop.querySelector("[data-allchildren]");   // several children: one button ticks them all, or clears them
    if (all) {
      const boxes = [...pop.querySelectorAll("[data-child]")];
      const label = () => { all.textContent = boxes.every(x => x.checked) ? "Select none" : "Select all"; };
      all.onclick = () => { const on = !boxes.every(x => x.checked); boxes.forEach(x => { x.checked = on; }); label(); };
      boxes.forEach(x => x.addEventListener("change", label));
      label();
    }
    const sel = pop.querySelector("[data-mode]");
    if (sel) sel.onchange = () => act({op: "mode", mode: sel.value});
    const pub = pop.querySelector("[data-publish]");
    if (pub && self) {    // Publish always sends this agent, so it needs its tick
      const f = () => { pub.disabled = !self.checked; pub.title = self.checked ? "" : "Publish always sends this agent: tick it"; };
      self.addEventListener("change", f); f();
    }
    if (pub) pub.onclick = () => {
      const repos = [...pop.querySelectorAll("[data-repo]:checked")].map(x => x.dataset.repo);
      const children = [...pop.querySelectorAll("[data-child]:checked")].map(x => x.dataset.child);
      pub.disabled = true; pub.textContent = "Publishing…";
      act({op: "publish", repos, children});
    };
    const cl = pop.querySelector("[data-close]");
    if (cl) cl.onclick = () => pop.classList.remove("open");
    pop.querySelector("[data-check]").onclick = () => { pop.innerHTML = '<div class="dim">Checking…</div>'; act({op: "check"}); };
  }
  function act(body) {
    msg = "";
    return post(body).then(r => { if (r.error) msg = r.error; return load(); });
  }
})();
