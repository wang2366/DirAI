// The agent's folder, which server.py adds (owner only) at the end of its index.html: each text file
// in a collapsed section, raw with line numbers (a .md rendered, with a Raw switch), then the names
// of the files not shown. Subfolders are collapsed sections too: opening one fetches that folder
// (/_review/files?agent=A&sub=rerun/nemo5) and draws it the same way, at any depth, with thumbnails for
// its images; a subfolder holding an index.html is another agent, so only a link. Every line, or
// rendered block, carries its source line numbers (data-line, data-line-end, in a <details
// data-file="rerun/fit.py">, the file's path in the folder), so text selected in a file reaches the
// agent as "rerun/run.sh, lines 12-14" (panel.js; for a rendered .md the server narrows the block's
// lines to the text). Raw HTML in a .md is shown as text, never run: agents write these files, and
// this page holds the owner's login. Reloads the opened folders when a run of the agent ends (panel.js
// sends "dirai:run-done"), marking what changed and showing, collapsed, what was removed.
(function () {
  const AGENT = document.currentScript.dataset.agent;
  const MARKED = "https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js";
  const OPEN_KEY = "dirai-files-open:" + AGENT;   // the opened folders, kept for this tab
  const THUMBS = /\.(png|jpe?g|gif|svg|webp)$/i, THUMB_MAX = 24;
  let byTime = true;   // files newest first (default) or by name; kept in localStorage
  try { byTime = localStorage.getItem("dirai-files-sort") !== "name"; } catch (e) {}
  const esc = s => s.replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const css = document.createElement("style");
  css.textContent = `
    #dirai-files { margin: 2rem 0 4rem; font: 14px/1.5 system-ui, sans-serif; }
    #dirai-files > h2 { font-size: 1rem; margin: 0 0 .4rem; opacity: .75; }
    #dirai-files details[data-file] { border: 1px solid rgba(128,128,128,.4); border-radius: 8px; margin: .4rem 0; padding: 0 .8rem; }
    #dirai-files details[data-file] > summary { cursor: pointer; padding: .4rem 0; font-weight: 600; }
    #dirai-files details[data-file] > summary span { font-weight: 400; opacity: .65; margin-left: .5rem; }
    #dirai-files details.f-dir { margin: .4rem 0; }
    #dirai-files details.f-dir > summary { cursor: pointer; padding: .3rem 0; font-weight: 600; }
    #dirai-files details.f-dir > summary span { font-weight: 400; opacity: .65; margin-left: .5rem; }
    #dirai-files details.f-dir > div { border-left: 2px solid rgba(128,128,128,.3); margin-left: .4rem; padding-left: .8rem; }
    #dirai-files .f-thumbs { display: flex; flex-wrap: wrap; gap: .5rem; margin: .4rem 0; }
    #dirai-files .f-thumbs a { font-size: 12px; opacity: .85; color: inherit; text-decoration: none; max-width: 120px; overflow: hidden; }
    #dirai-files .f-thumbs img { display: block; max-width: 120px; max-height: 90px; border: 1px solid rgba(128,128,128,.4); border-radius: 4px; }
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
    #dirai-files .f-names a { color: inherit; }
    #dirai-files a.f-dl { margin-left: .4rem; text-decoration: none; color: inherit; opacity: .7; font-weight: 400; }
    #dirai-files a.f-dl:hover { opacity: 1; }
    #dirai-files .f-thumbs .f-thumb { display: inline-flex; align-items: flex-end; }`;
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
  const plural = (n, w) => n + " " + w + (n === 1 ? "" : "s");
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

  let marked = null;
  const folders = {};      // sub ("" = the agent's folder) -> what the server sent for it, for the folders fetched
  const opened = new Set(JSON.parse(sessionStorage.getItem(OPEN_KEY) || "[]"));   // subs the owner opened
  const raw = new Set();   // .md files (by path) the owner switched to raw
  let shown = {};          // file path -> its pieces' raw text, to mark what a run changed
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
  const encPath = p => p.split("/").map(encodeURIComponent).join("/");
  // ⤓: a file of the folder (any type, any size) or a folder as .zip, saved by the browser (server.py)
  const dlUrl = path => "/_review/download?agent=" + encodeURIComponent(AGENT) + "&name=" + encodeURIComponent(path);
  const zipUrl = sub => "/_review/zip?agent=" + encodeURIComponent(AGENT) + (sub ? "&sub=" + encodeURIComponent(sub) : "");
  const dlA = (href, title, label) => `<a class="f-dl" download href="${href}" title="${esc(title)}">${label || "⤓"}</a>`;
  // The html of one folder (sub) from its data d: its files, the names of the rest, its subfolders
  // (opened ones drawn in place). openFiles: paths of the files now open; markChanges: mark what changed.
  function folderHtml(d, sub, markChanges, openFiles, next) {
    const pre = sub ? sub + "/" : "";
    const sorted = byTime ? d.files.slice().sort((a, b) => b.mtime - a.mtime) : d.files;
    const files = sorted.map(f => {
      const path = pre + f.name;
      const md = isMd(f.name) && marked, rendered = md && !raw.has(path);
      const ps = pieces(f, rendered ? marked : null), key = path + (rendered ? "\0r" : "");
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
            `title="${esc(path)}, line${p.a === p.b ? " " + p.a : "s " + p.a + "–" + p.b}">${p.html}</div>`
          : `<div class="f-line${changed[j] ? " rv-changed" : ""}" data-line="${p.a}">${p.html}</div>`) + (gone[j] || "")).join("");
      const lines = nl(f.text.replace(/\n$/, "")) + 1;
      return `<details data-file="${esc(path)}"${openFiles.has(path) ? " open" : ""}><summary>${esc(f.name)}` +
        dlA(dlUrl(path), "Download " + f.name) + `<span>${plural(lines, "line")} · ${kb(f.size)} · updated ` +
        `${esc(new Date(f.mtime * 1000).toLocaleString())}</span></summary>` +
        (md ? `<div class="f-tools"><button data-raw="${esc(path)}">${rendered ? "Raw" : "Rendered"}</button></div>` : "") +
        `<div class="${rendered ? "f-md" : "f-src"}">${body}</div></details>`;
    }).join("");
    // images of a subfolder as thumbnails (the page's own relative URL, which the server serves)
    const thumbs = sub ? d.other.filter(f => f.why === "image" && THUMBS.test(f.name)) : [];
    const thumbHtml = thumbs.length ? `<div class="f-thumbs">` + thumbs.slice(0, THUMB_MAX).map(f =>
      `<span class="f-thumb"><a href="${encPath(pre + f.name)}" title="${esc(f.name)}, ${kb(f.size)}"><img loading="lazy" alt="${esc(f.name)}" ` +
      `src="${encPath(pre + f.name)}">${esc(f.name)}</a>${dlA(dlUrl(pre + f.name), "Download " + f.name)}</span>`).join("") + `</div>` : "";
    const named = new Set(thumbs.slice(0, THUMB_MAX));
    const other = d.other.filter(f => !named.has(f)).map(f => esc(f.name) +
      (f.why === "not in this folder" ? "" : dlA(dlUrl(pre + f.name), "Download " + f.name)) + ` (${esc(f.why)}, ${kb(f.size)})`);
    const dirs = d.dirs.map(x => {
      const path = pre + x.name;
      if (x.agent) return `<div class="f-names"><a href="${encPath(path)}/">${esc(x.name)}/</a> (agent: its own page)</div>`;
      if (x.out) return `<div class="f-names">${esc(x.name)}/ (link out of this folder, not followed)</div>`;
      const c = x.count || {files: 0, dirs: 0}, cap = c.capped ? "+" : "";
      const what = [c.files ? plural(c.files, "file") : "", c.dirs ? plural(c.dirs, "folder") : ""].filter(Boolean).join(" · ");
      const isOpen = opened.has(path);
      const inner = !isOpen ? "" : folders[path] ? folderHtml(folders[path], path, markChanges, openFiles, next)
                                                 : `<div class="f-names">Loading…</div>`;
      return `<details class="f-dir" data-dir="${esc(path)}"${isOpen ? " open" : ""}><summary>${esc(x.name)}/` +
        dlA(zipUrl(path), "Download " + x.name + "/ as .zip", "⤓ .zip") + `<span>${what ? what.replace(/(\d+)/, "$1" + cap) : "empty"}</span></summary><div>${inner}</div></details>`;
    }).join("");
    const more = d.more ? `<div class="f-names">and ${d.more} more not listed</div>` : "";
    return files + thumbHtml + (other.length ? `<div class="f-names">Not shown: ${other.join(", ")}</div>` : "") + dirs + more;
  }
  function draw(markChanges) {
    const d = folders[""];
    const openFiles = new Set([...box.querySelectorAll("details[data-file][open]")].map(x => x.dataset.file));
    const next = {};
    const html = folderHtml(d, "", markChanges, openFiles, next);
    const sw = b => `<button data-sort="${b}"${(b === "time") === byTime ? " disabled" : ""}>${b === "time" ? "Modified ▼" : "Name"}</button>`;
    box.innerHTML = (html ? `<h2>Files in this folder <span class="f-tools">${dlA(zipUrl(""), "Download this folder as .zip", "⤓ .zip")} ` +
      `Sort: ${sw("name")} ${sw("time")}</span></h2>` : "") + html;
    clean(box);
    shown = next;
    box.style.display = box.innerHTML ? "" : "none";
  }
  function fetchFolder(sub) {
    return fetch("/_review/files?agent=" + encodeURIComponent(AGENT) + (sub ? "&sub=" + encodeURIComponent(sub) : ""))
      .then(r => r.ok ? r.json() : null).then(d => { if (d) folders[sub] = d; return d; });
  }
  const anyMd = () => Object.values(folders).some(d => d.files.some(f => isMd(f.name)));
  function redraw(markChanges) {
    return (anyMd() ? loadMarked() : Promise.resolve(null)).then(m => {
      marked = m;
      draw(markChanges);
    });
  }
  box.addEventListener("click", e => {
    if (e.target.closest("a.f-dl")) return e.stopPropagation();   // ⤓: the browser saves it; nothing opens
    const o = e.target.closest("button[data-sort]");   // Name / Modified
    if (o) {
      byTime = o.dataset.sort === "time";
      try { localStorage.setItem("dirai-files-sort", byTime ? "time" : "name"); } catch (err) {}
      return draw(false);
    }
    const b = e.target.closest("button[data-raw]");   // Raw / Rendered
    if (b) {
      const path = b.dataset.raw;
      raw.has(path) ? raw.delete(path) : raw.add(path);
      return draw(false);
    }
    const s = e.target.closest("details.f-dir > summary");   // open or close a subfolder
    if (!s) return;
    e.preventDefault();
    const path = s.parentElement.dataset.dir;
    if (opened.has(path)) opened.delete(path); else opened.add(path);
    sessionStorage.setItem(OPEN_KEY, JSON.stringify([...opened]));
    if (opened.has(path) && !folders[path]) {
      redraw(false).then(() => fetchFolder(path)).then(() => redraw(false));   // "Loading…" first
    } else redraw(false);
  });
  // the folder and the opened ones (at any depth: a folder is fetched once its parent is known)
  function load(markChanges) {
    const walk = sub => fetchFolder(sub).then(d => d && Promise.all(
      d.dirs.filter(x => !x.agent && !x.out && opened.has(sub ? sub + "/" + x.name : x.name))
            .map(x => walk(sub ? sub + "/" + x.name : x.name))));
    return walk("").then(() => folders[""] && redraw(markChanges));
  }
  load(false);
  document.addEventListener("dirai:run-done", () => load(true));
})();
