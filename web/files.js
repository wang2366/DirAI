// The agent's folder, which server.py adds (owner only) at the end of its index.html: each text file
// raw, in a collapsed section with line numbers, then the names of the files not shown and of the
// subfolders. Every line carries its number (data-line, in a <details data-file>), so text selected
// in a file reaches the agent as "run.sh, lines 12-14" (panel.js). Reloads when a run of the agent
// ends (panel.js sends "dirai:run-done"), marking the lines that changed.
(function () {
  const AGENT = document.currentScript.dataset.agent;
  const esc = s => s.replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const css = document.createElement("style");
  css.textContent = `
    #dirai-files { margin: 2rem 0 4rem; font: 14px/1.5 system-ui, sans-serif; }
    #dirai-files > h2 { font-size: 1rem; margin: 0 0 .4rem; opacity: .75; }
    #dirai-files > details { border: 1px solid rgba(128,128,128,.4); border-radius: 8px; margin: .4rem 0; padding: 0 .8rem; }
    #dirai-files > details > summary { cursor: pointer; padding: .4rem 0; font-weight: 600; }
    #dirai-files > details > summary span { font-weight: 400; opacity: .65; margin-left: .5rem; }
    #dirai-files .f-src { font: 13px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace; overflow-x: auto;
      padding: 0 0 .6rem; }
    #dirai-files .f-line { white-space: pre-wrap; padding-left: 4.2em; text-indent: -4.2em; min-height: 1.45em; }
    #dirai-files .f-line::before { content: attr(data-line); display: inline-block; width: 3.6em; margin-right: .6em;
      text-align: right; opacity: .4; user-select: none; }
    #dirai-files .f-names { opacity: .75; margin: .5rem 0; }
    #dirai-files .f-names a { color: inherit; }`;
  document.head.appendChild(css);
  const box = document.createElement("section");
  box.id = "dirai-files";
  box.style.display = "none";
  document.body.appendChild(box);

  const kb = n => n < 1024 ? n + " B" : n < 1 << 20 ? (n / 1024).toFixed(1) + " KB" : (n / (1 << 20)).toFixed(1) + " MB";
  const linesOf = text => text.replace(/\n$/, "").split("\n");
  let shown = {};   // file name -> its lines, to mark what a run changed
  function load(markChanges) {
    return fetch("/_review/files?agent=" + encodeURIComponent(AGENT)).then(r => r.ok ? r.json() : null).then(d => {
      if (!d) return;
      const open = new Set([...box.querySelectorAll(":scope > details[open]")].map(x => x.dataset.file));
      const next = {};
      const files = d.files.map(f => {
        const lines = linesOf(f.text), before = markChanges && shown[f.name] && shown[f.name].slice();
        next[f.name] = lines;
        const body = lines.map((l, i) => {
          let changed = false;
          if (before) { const k = before.indexOf(l); changed = k < 0; if (k >= 0) before.splice(k, 1); }
          return `<div class="f-line${changed ? " rv-changed" : ""}" data-line="${i + 1}">${esc(l)}</div>`;
        }).join("");
        return `<details data-file="${esc(f.name)}"${open.has(f.name) ? " open" : ""}><summary>${esc(f.name)}` +
          `<span>${lines.length} line${lines.length === 1 ? "" : "s"} · ${kb(f.size)} · updated ` +
          `${esc(new Date(f.mtime * 1000).toLocaleString())}</span></summary><div class="f-src">${body}</div></details>`;
      }).join("");
      const other = d.other.map(f => `${esc(f.name)} (${esc(f.why)}, ${kb(f.size)})`);
      const dirs = d.dirs.map(x => x.agent ? `<a href="${encodeURIComponent(x.name)}/">${esc(x.name)}/</a>` : esc(x.name) + "/");
      const more = d.more ? ` and ${d.more} more` : "";
      box.innerHTML = (files || other.length || dirs.length ? "<h2>Files in this folder</h2>" : "") + files +
        (other.length ? `<div class="f-names">Not shown: ${other.join(", ")}</div>` : "") +
        (dirs.length || more ? `<div class="f-names">Subfolders: ${dirs.join(", ") || "none listed"}${more}</div>` : "");
      shown = next;
      box.style.display = box.innerHTML ? "" : "none";
    });
  }
  load(false);
  document.addEventListener("dirai:run-done", () => load(true));
})();
