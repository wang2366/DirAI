// "New agent" button injected by server.py (owner only): pick a tree and a folder (autocomplete),
// describe a task; that tree's server creates <folder>/index.html if needed and starts the agent there.
// Another tree (Where, proposal 68): its suggestions and the create request go through Machines' relay
// (op "call", paths "dirs" and "new"), so the server that owns the folder still checks it.
(function () {
  const BASE = document.currentScript.dataset.base;   // this agent's folder ("" on the agent list)
  const ROOT = document.currentScript.dataset.root;   // absolute path of the tree being served
  const LAST = "dirai-na-tree";                       // the tree last used from the agent list (D1)
  const css = `
  #na-btn{position:fixed;left:120px;bottom:16px;z-index:99999;padding:8px 14px;border-radius:20px;
    border:1px solid #888;background:#1d1d1f;color:#fff;font:600 14px system-ui;cursor:pointer}
  #na-dlg{position:fixed;inset:0;z-index:100000;display:none;align-items:center;justify-content:center;
    background:rgba(0,0,0,.35)}
  #na-dlg.open{display:flex}
  #na-box{width:min(560px,calc(100vw - 32px));background:#fff;color:#1d1d1f;border-radius:10px;padding:16px;
    box-shadow:0 8px 30px rgba(0,0,0,.3);font:14px/1.45 system-ui}
  #na-box label{display:block;font-weight:600;margin:10px 0 4px}
  #na-box select{font:14px system-ui;padding:4px;border:1px solid #bbb;border-radius:6px;max-width:100%}
  #na-box input,#na-box textarea{width:100%;box-sizing:border-box;padding:6px 8px;font:14px system-ui;
    border:1px solid #bbb;border-radius:6px}
  #na-box textarea{min-height:110px}
  #na-hint,#na-hint2,#na-whint{font-size:12px;color:#666;margin-top:3px}
  #na-where-row{display:none}
  #na-where-row.on{display:block}
  #na-row{display:flex;gap:8px;justify-content:flex-end;margin-top:12px}
  #na-row button{padding:6px 14px;border-radius:6px;border:1px solid #999;background:#fafafa;cursor:pointer;font:14px system-ui}
  #na-row .primary{background:#0b63ce;color:#fff;border-color:#0b63ce}`;
  document.head.insertAdjacentHTML("beforeend", "<style>" + css + "</style>");
  document.body.insertAdjacentHTML("beforeend", `
  <button id="na-btn">New agent</button>
  <div id="na-dlg"><div id="na-box">
    <b>New agent</b>
    <div id="na-where-row"><label for="na-where">Where</label>
      <select id="na-where"></select>
      <div id="na-whint">Running trees under Machines. A folder outside every tree: use New tree… in Machines.</div></div>
    <label for="na-dir">Folder (relative to <code id="na-root"></code>)</label>
    <input id="na-dir" list="na-dirs" autocomplete="off" spellcheck="false" placeholder="e.g. RTD_project/new_study">
    <datalist id="na-dirs"></datalist>
    <div id="na-hint">Existing folders are suggested as you type; a new name is created. Its index.html is made if missing.</div>
    <label for="na-task">Task</label>
    <textarea id="na-task" placeholder="What should the agent do there?"></textarea>
    <label for="na-every">Repeat</label>
    <select id="na-every"><option value="off">Once</option><option value="hour">Every hour</option>
      <option value="day">Every day</option><option value="week">Every week</option></select>
    <div id="na-hint2">Runs now, then sends the same task again on this schedule (change it later in the agent's panel).</div>
    <div id="na-row"><button id="na-cancel">Cancel</button><button id="na-go" class="primary">Create &amp; start</button></div>
  </div></div>`);

  const $ = id => document.getElementById(id);
  const esc = s => String(s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"})[c]);
  const post = (path, body) => fetch("/_review/" + path, {
    method: "POST", headers: {"Content-Type": "application/json", "X-Review": "1"}, body: JSON.stringify(body),
  }).then(r => r.json());
  let trees = {};       // Where option value -> {id, root, fport, alive}; "" is this tree
  // "dirs"/"new" on the picked tree: here directly, else through Machines' relay to that tree's server
  function call(path, data) {
    const tid = $("na-where").value;
    if (!tid) return path === "dirs" ? fetch("/_review/dirs?prefix=" + encodeURIComponent(data.prefix)).then(r => r.json())
      : post(path, data);
    return post("remotes", {op: "call", tree: tid, path, data});
  }

  let pending = 0;
  function suggest() {
    const n = ++pending;
    call("dirs", {prefix: $("na-dir").value}).then(list => {
      if (n !== pending || !Array.isArray(list)) return;   // a newer keystroke already asked; or an error
      $("na-dirs").innerHTML = list.map(d => `<option value="${esc(d)}">`).join("");
    }, () => {});
  }
  $("na-dir").addEventListener("input", suggest);

  function picked() {
    const t = trees[$("na-where").value] || trees[""];
    $("na-root").textContent = t.root + "/";
    $("na-dirs").innerHTML = "";
    suggest();
  }
  // Where: this tree, then every tree Machines lists (one entry per tree, whichever route reports it);
  // stopped ones greyed out; a linked machine with no tree points to New tree… (D3: no tree is made here)
  function fillWhere(rep, start) {
    trees = {"": {root: ROOT, alive: true}};
    let opts = `<option value="">${esc((rep && rep.machine) || "this server")} : ${esc(ROOT)}</option>`;
    const seen = new Set(rep && rep.tree_id ? [rep.tree_id] : []), withTree = new Set();
    const rank = t => (t.state === "alive" && t.fport && !t.stale ? 0 : 1) + t.via.length / 100;
    ((rep && rep.trees) || []).slice().sort((x, y) => rank(x) - rank(y)).forEach(t => {
      withTree.add(t.via.join(" → "));
      if (t.tree_id && seen.has(t.tree_id)) return;
      if (t.tree_id) seen.add(t.tree_id);
      const alive = t.state === "alive" && !!t.fport;
      trees[t.id] = {id: t.id, root: t.root, fport: t.fport, alive};
      opts += `<option value="${esc(t.id)}"${alive ? "" : " disabled"}>${esc(t.via.join(" → "))} : ${esc(t.root)}${
        alive ? "" : " (" + esc(t.state || "stopped") + ": start it first, in Machines)"}</option>`;
    });
    const bare = [];      // machines linked, no tree listed there
    ((rep && rep.hosts) || []).filter(h => h.enabled && !withTree.has(h.alias)).forEach(h => bare.push(h.alias));
    bare.forEach(a => { opts += `<option value="newtree:${esc(a)}">${esc(a)} : New tree on this machine…</option>`; });
    $("na-where").innerHTML = opts;
    $("na-where-row").classList.toggle("on", Object.keys(trees).length + bare.length > 1);
    $("na-where").value = trees[start] && trees[start].alive ? start : "";
    picked();
  }
  $("na-where").addEventListener("change", () => {
    const v = $("na-where").value;
    if (v.startsWith("newtree:")) {        // Machines' New tree… in that machine's box (on the agent list)
      $("na-dlg").classList.remove("open");
      const box = document.querySelector(`#rv-machines .mach[data-key="${CSS.escape(v.slice(8))}"]`);
      if (!box) { location.href = "/www/index.html"; return; }
      $("rv-machines").open = true;
      const nt = box.querySelector("details.newtree");
      if (nt) nt.open = true;
      box.scrollIntoView({block: "center"});
      return;
    }
    if (!BASE) try { localStorage.setItem(LAST, v); } catch (e) {}
    picked();
  });

  $("na-btn").onclick = () => {
    $("na-dir").value = BASE ? BASE + "/" : "";
    $("na-dlg").classList.add("open");
    // D1: on an agent page this tree, folder prefilled; on the agent list the tree used last
    let start = "";
    if (!BASE) try { start = localStorage.getItem(LAST) || ""; } catch (e) {}
    fillWhere(null, "");
    fetch("/_review/remotes").then(r => r.ok ? r.json() : null).then(rep => { if (rep) fillWhere(rep, start); }, () => {});
    $("na-dir").focus();
  };
  $("na-cancel").onclick = () => $("na-dlg").classList.remove("open");
  $("na-dlg").onclick = e => { if (e.target.id === "na-dlg") $("na-dlg").classList.remove("open"); };
  $("na-go").onclick = () => {
    const t = trees[$("na-where").value] || trees[""];
    // D2: another tree's agent opens in a new tab on its server (through the forwarded port Open uses);
    // the tab is opened now, while the click counts, so no pop-up blocker stops it
    const tab = t.id ? window.open("", "_blank") : null;
    $("na-go").disabled = true;
    call("new", {dir: $("na-dir").value, task: $("na-task").value, every: $("na-every").value}).then(r => {
      $("na-go").disabled = false;
      if (r.error) { if (tab) tab.close(); return alert(r.error); }
      if (!t.id) { location.href = r.url; return; }      // the new agent, already working
      const url = location.protocol + "//" + location.hostname + ":" + t.fport + r.url;
      if (tab) tab.location.href = url; else window.open(url, "_blank");
      $("na-dlg").classList.remove("open");
      $("na-task").value = "";
    }, () => { $("na-go").disabled = false; if (tab) tab.close(); alert("Request failed."); });
  };
})();
