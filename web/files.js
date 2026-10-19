// The agent's folder, which server.py adds (owner only) at the end of its index.html: each text file
// in a collapsed section, raw with line numbers (a .md rendered, with a Raw switch), then the names
// of the files not shown and of the subfolders. Every line, or rendered block, carries its source
// line numbers (data-line, data-line-end, in a <details data-file>), so text selected in a file
// reaches the agent as "run.sh, lines 12-14" (panel.js; for a rendered .md the server narrows the
// block's lines to the text). Raw HTML in a .md is shown as text, never run: agents write these
// files, and this page holds the owner's login. Reloads when a run of the agent ends (panel.js sends
// "dirai:run-done"), marking what changed and showing, collapsed, what was removed.
(function () {
  const AGENT = document.currentScript.dataset.agent;
  const MARKED = "https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js";
  const esc = s => s.replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const css = document.createElement("style");
  css.textContent = `
    #dirai-files { margin: 2rem 0 4rem; font: 14px/1.5 system-ui, sans-serif; }
    #dirai-files > h2 { font-size: 1rem; margin: 0 0 .4rem; opacity: .75; }
    #dirai-files > details { border: 1px solid rgba(128,128,128,.4); border-radius: 8px; margin: .4rem 0; padding: 0 .8rem; }
    #dirai-files > details > summary { cursor: pointer; padding: .4rem 0; font-weight: 600; }
    #dirai-files > details > summary span { font-weight: 400; opacity: .65; margin-left: .5rem; }
    #dirai-files .f-tools { text-align: right; margin: -.2rem 0 .2rem; }
    #dirai-files .f-tools button { font: 12px system-ui; padding: 1px 8px; border: 1px solid rgba(128,128,128,.5);
      border-radius: 10px; background: none; color: inherit; cursor: pointer; }
    #dirai-files .f-src { font: 13px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace; overflow-x: auto;
      padding: 0 0 .6rem; }
    #dirai-files .f-line { white-space: pre-wrap; padding-left: 4.2em; text-indent: -4.2em; min-height: 1.45em; }
    #dirai-files .f-line::before { content: attr(data-line); display: inline-block; width: 3.6em; margin-right: .6em;
      text-align: right; opacity: .4; user-select: none; }
    #dirai-files .f-md { padding: 0 0 .6rem; }
    #dirai-files .f-block { border-left: 3px solid transparent; padding-left: .5rem; margin-left: -.8rem; }
    #dirai-files .f-block:hover { border-left-color: rgba(128,128,128,.35); }
    #dirai-files .f-md pre { overflow-x: auto; background: rgba(128,128,128,.1); padding: .6rem; border-radius: 6px; }
    #dirai-files .f-md table { border-collapse: collapse; }
    #dirai-files .f-md td, #dirai-files .f-md th { border: 1px solid rgba(128,128,128,.4); padding: .2rem .5rem; }
    #dirai-files .f-gone { white-space: pre-wrap; padding-left: 4.2em; text-indent: -4.2em; min-height: 1.45em; }
    #dirai-files .f-gone::before { content: "−"; display: inline-block; width: 3.6em; margin-right: .6em;
      text-align: right; opacity: .5; user-select: none; }
    #dirai-files .f-names { opacity: .75; margin: .5rem 0; }
    #dirai-files .f-names a { color: inherit; }`;
  document.head.appendChild(css);
  const box = document.createElement("section");
  box.id = "dirai-files";
  box.style.display = "none";
  document.body.appendChild(box);

  let markedReady = null;
  function loadMarked() {   // null when the CDN can't be reached: a .md is then shown raw
    return markedReady = markedReady || new Promise(done => {
      const s = document.createElement("script");
      s.src = MARKED;
      s.onload = () => {
        const m = window.marked && window.marked.lexer ? window.marked : null;
        if (m) m.use({renderer: {html: t => esc(typeof t === "string" ? t : (t.text || t.raw || ""))}});
        done(m);
      };
      s.onerror = () => done(null);
      document.head.appendChild(s);
    });
  }

  const kb = n => n < 1024 ? n + " B" : n < 1 << 20 ? (n / 1024).toFixed(1) + " KB" : (n / (1 << 20)).toFixed(1) + " MB";
  const nl = s => (s.match(/\n/g) || []).length;
  const isMd = name => /\.md$/i.test(name);
  // [{a, b, raw, html}]: one per source line (raw), or per top-level markdown block (rendered)
  function pieces(f, marked) {
    if (!marked) return f.text.replace(/\n$/, "").split("\n").map((l, i) => ({a: i + 1, b: i + 1, raw: l, html: esc(l)}));
    const tokens = marked.lexer(f.text), out = [];
    let line = 1;
    for (const t of tokens) {
      const a = line, raw = t.raw || "";
      line += nl(raw);
      if (t.type === "space") continue;
      const one = [t];
      one.links = tokens.links;
      out.push({a, b: a + nl(raw.replace(/\s+$/, "")), raw, html: marked.parser(one)});
    }
    return out;
  }
  // links and images only to http(s), relative paths or anchors; no handlers, styles or embeds
  function clean(root) {
    root.querySelectorAll(".f-md *").forEach(el => {
      for (const at of [...el.attributes]) {
        const n = at.name.toLowerCase();
        if (n.startsWith("on") || n === "style" || n === "srcdoc" ||
            ((n === "href" || n === "src") && /^\s*(javascript|data|vbscript):/i.test(at.value))) el.removeAttribute(at.name);
      }
    });
    root.querySelectorAll(".f-md :is(script,iframe,object,embed,form,style,link,meta,base)").forEach(el => el.remove());
  }

  let data = null, marked = null;
  const raw = new Set();   // .md files the owner switched to raw
  let shown = {};          // file name -> its pieces' raw text, to mark what a run changed
  // {j: html}: the old pieces with no twin (twin[i] < 0), each run of them collapsed, after current
  // piece j, the twin of the old piece just before the run (-1: before the first piece)
  function removed(before, twin, rendered) {
    const out = {};
    let run = [], after = -1;
    const flush = () => {
      if (!run.length) return;
      const n = run.length, what = rendered ? "block" : "line";
      const html = rendered ? marked.parser(marked.lexer(run.join(""))) : run.map(r => `<div class="f-gone">${esc(r)}</div>`).join("");
      out[after] = (out[after] || "") + `<details class="rv-removed"><summary>Removed (${n} ${what}${n === 1 ? "" : "s"})</summary>` +
        `<div>${html}</div></details>`;
      run = [];
    };
    before.forEach((r, i) => {
      if (twin[i] < 0) return run.push(r);
      flush();
      after = twin[i];
    });
    flush();
    return out;
  }
  function draw(markChanges) {
    const open = new Set([...box.querySelectorAll(":scope > details[open]")].map(x => x.dataset.file));
    const next = {};
    const files = data.files.map(f => {
      const md = isMd(f.name) && marked, rendered = md && !raw.has(f.name);
      const ps = pieces(f, rendered ? marked : null), key = f.name + (rendered ? "\0r" : "");
      const before = markChanges && shown[key] && shown[key].slice();
      next[key] = ps.map(p => p.raw);
      // each old piece goes to the first current one with the same text; the rest were removed
      const twin = before && before.map(() => -1), changed = ps.map((p, j) => {
        if (!before) return false;
        const k = before.findIndex((r, i) => r === p.raw && twin[i] < 0);
        return k < 0 || (twin[k] = j, false);
      });
      const gone = before ? removed(before, twin, rendered) : {};
      const body = (gone[-1] || "") + ps.map((p, j) => (rendered
          ? `<div class="f-block${changed[j] ? " rv-changed" : ""}" data-line="${p.a}" data-line-end="${p.b}" data-rendered="1" ` +
            `title="${esc(f.name)}, line${p.a === p.b ? " " + p.a : "s " + p.a + "–" + p.b}">${p.html}</div>`
          : `<div class="f-line${changed[j] ? " rv-changed" : ""}" data-line="${p.a}">${p.html}</div>`) + (gone[j] || "")).join("");
      const lines = nl(f.text.replace(/\n$/, "")) + 1;
      return `<details data-file="${esc(f.name)}"${open.has(f.name) ? " open" : ""}><summary>${esc(f.name)}` +
        `<span>${lines} line${lines === 1 ? "" : "s"} · ${kb(f.size)} · updated ` +
        `${esc(new Date(f.mtime * 1000).toLocaleString())}</span></summary>` +
        (md ? `<div class="f-tools"><button data-raw="${esc(f.name)}">${rendered ? "Raw" : "Rendered"}</button></div>` : "") +
        `<div class="${rendered ? "f-md" : "f-src"}">${body}</div></details>`;
    }).join("");
    const other = data.other.map(f => `${esc(f.name)} (${esc(f.why)}, ${kb(f.size)})`);
    const dirs = data.dirs.map(x => x.agent ? `<a href="${encodeURIComponent(x.name)}/">${esc(x.name)}/</a>` : esc(x.name) + "/");
    const more = data.more ? ` and ${data.more} more` : "";
    box.innerHTML = (files || other.length || dirs.length ? "<h2>Files in this folder</h2>" : "") + files +
      (other.length ? `<div class="f-names">Not shown: ${other.join(", ")}</div>` : "") +
      (dirs.length || more ? `<div class="f-names">Subfolders: ${dirs.join(", ") || "none listed"}${more}</div>` : "");
    clean(box);
    shown = next;
    box.style.display = box.innerHTML ? "" : "none";
  }
  box.addEventListener("click", e => {   // Raw / Rendered
    const b = e.target.closest("button[data-raw]");
    if (!b) return;
    const name = b.dataset.raw;
    raw.has(name) ? raw.delete(name) : raw.add(name);
    draw(false);
  });
  function load(markChanges) {
    return fetch("/_review/files?agent=" + encodeURIComponent(AGENT)).then(r => r.ok ? r.json() : null).then(d => {
      if (!d) return;
      data = d;
      return (d.files.some(f => isMd(f.name)) ? loadMarked() : Promise.resolve(null)).then(m => {
        marked = m;
        draw(markChanges);
      });
    });
  }
  load(false);
  document.addEventListener("dirai:run-done", () => load(true));
})();
