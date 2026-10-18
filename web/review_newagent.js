// "New agent" button injected by html_server.py (owner only): pick a folder (autocomplete),
// describe a task; the server creates <folder>/index.html if needed and starts the AI assistant there.
(function () {
  const BASE = document.currentScript.dataset.base;   // this page's folder ("" on the list page)
  const ROOT = document.currentScript.dataset.root;   // absolute path of the tree being served
  const css = `
  #na-btn{position:fixed;left:120px;bottom:16px;z-index:99999;padding:8px 14px;border-radius:20px;
    border:1px solid #888;background:#1d1d1f;color:#fff;font:600 14px system-ui;cursor:pointer}
  #na-dlg{position:fixed;inset:0;z-index:100000;display:none;align-items:center;justify-content:center;
    background:rgba(0,0,0,.35)}
  #na-dlg.open{display:flex}
  #na-box{width:min(560px,calc(100vw - 32px));background:#fff;color:#1d1d1f;border-radius:10px;padding:16px;
    box-shadow:0 8px 30px rgba(0,0,0,.3);font:14px/1.45 system-ui}
  #na-box label{display:block;font-weight:600;margin:10px 0 4px}
  #na-box select{font:14px system-ui;padding:4px;border:1px solid #bbb;border-radius:6px}
  #na-box input,#na-box textarea{width:100%;box-sizing:border-box;padding:6px 8px;font:14px system-ui;
    border:1px solid #bbb;border-radius:6px}
  #na-box textarea{min-height:110px}
  #na-hint{font-size:12px;color:#666;margin-top:3px}
  #na-row{display:flex;gap:8px;justify-content:flex-end;margin-top:12px}
  #na-row button{padding:6px 14px;border-radius:6px;border:1px solid #999;background:#fafafa;cursor:pointer;font:14px system-ui}
  #na-row .primary{background:#0b63ce;color:#fff;border-color:#0b63ce}`;
  document.head.insertAdjacentHTML("beforeend", "<style>" + css + "</style>");
  document.body.insertAdjacentHTML("beforeend", `
  <button id="na-btn">New agent</button>
  <div id="na-dlg"><div id="na-box">
    <b>New agent</b>
    <label for="na-dir">Folder (relative to <code id="na-root"></code>)</label>
    <input id="na-dir" list="na-dirs" autocomplete="off" spellcheck="false" placeholder="e.g. RTD_project/new_study">
    <datalist id="na-dirs"></datalist>
    <div id="na-hint">Existing folders are suggested as you type; a new name is created. Its index.html is made if missing.</div>
    <label for="na-task">Task</label>
    <textarea id="na-task" placeholder="What should the agent do there?"></textarea>
    <label for="na-every">Repeat</label>
    <select id="na-every"><option value="off">Once</option><option value="hour">Every hour</option>
      <option value="day">Every day</option><option value="week">Every week</option></select>
    <div id="na-hint2" style="font-size:12px;color:#666;margin-top:3px">Runs now, then sends the same task again on this schedule (change it later in the page's AI assistant panel).</div>
    <div id="na-row"><button id="na-cancel">Cancel</button><button id="na-go" class="primary">Create &amp; start</button></div>
  </div></div>`);

  const $ = id => document.getElementById(id);
  $("na-root").textContent = ROOT + "/";
  const call = (path, body) => fetch("/_review/" + path, body === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json", "X-Review": "1"}, body: JSON.stringify(body),
  }).then(r => r.json());

  let pending = 0;
  function suggest() {
    const n = ++pending;
    call("dirs?prefix=" + encodeURIComponent($("na-dir").value)).then(list => {
      if (n !== pending) return;            // a newer keystroke already asked
      $("na-dirs").innerHTML = list.map(d => `<option value="${d.replace(/"/g, "&quot;")}">`).join("");
    });
  }
  $("na-dir").addEventListener("input", suggest);

  $("na-btn").onclick = () => {
    $("na-dir").value = BASE ? BASE + "/" : "";
    $("na-dlg").classList.add("open");
    suggest();
    $("na-dir").focus();
  };
  $("na-cancel").onclick = () => $("na-dlg").classList.remove("open");
  $("na-dlg").onclick = e => { if (e.target.id === "na-dlg") $("na-dlg").classList.remove("open"); };
  $("na-go").onclick = () => {
    $("na-go").disabled = true;
    call("new", {dir: $("na-dir").value, task: $("na-task").value, every: $("na-every").value}).then(r => {
      $("na-go").disabled = false;
      if (r.error) return alert(r.error);
      location.href = r.url;                // the new page, with the assistant working
    }, () => { $("na-go").disabled = false; alert("Request failed."); });
  };
})();
