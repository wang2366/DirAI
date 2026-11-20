// The Tree tab of the agent list (www/index.html), injected by server.py after agent_list.js (owner only).
// Part 1, the model: the agents nested by path, and what a click does to it. Pure functions, no page;
// tests/tree_model.js runs them under node. Part 2, the view: draws the model in a tab of its own, reading
// the rows, statuses, stars and summary cards through window.diraiList (agent_list.js).
(function () {
  // ---- the model ----
  // An item is one agent: {tree: its tree's id ("" for this server), path: "a/b" ("" for the tree's top
  // folder), needs: bool, working: bool, ...whatever the view wants back}. A tree is {id, name}.
  // A node is {key, tree, path, name, item, children, agents, needs, working}: item is the agent that lives
  // at that path (every index.html is one node, with its subagents under it), null for a plain path.
  // agents / needs / working count the agents under the node, not the node's own.
  const node = (tree, path, name) => ({key: tree + "|" + path, tree, path, name, item: null, children: []});
  const count = (n, f) => n.children.reduce((s, c) => s + count(c, f) + (c.item && f(c.item) ? 1 : 0), 0);

  function finish(n, top) {
    n.children = n.children.map(c => finish(c, false)).sort((a, b) => a.name.localeCompare(b.name));
    n.agents = count(n, () => true); n.needs = count(n, i => i.needs); n.working = count(n, i => i.working);
    const only = n.children[0];
    // a chain of plain paths is one line: a/b/c (D2); a tree's top node and agents are never joined
    return !top && !n.item && n.children.length === 1 && !only.item
      ? Object.assign({}, only, {name: n.name + "/" + only.name}) : n;
  }

  // the trees that have agents, each as a top node
  function build(items, trees) {
    return trees.map(t => {
      const mine = items.filter(i => i.tree === t.id);
      if (!mine.length) return null;
      const top = node(t.id, "", t.name);
      mine.forEach(it => {
        let n = top;
        const segs = it.path.split("/").filter(Boolean);
        segs.forEach((seg, i) => {
          const path = segs.slice(0, i + 1).join("/");
          let c = n.children.find(x => x.path === path);
          if (!c) n.children.push(c = node(t.id, path, seg));
          n = c;
        });
        n.item = it;
      });
      return finish(top, true);
    }).filter(Boolean);
  }

  // open: the set of keys of the nodes that are unfolded
  const walk = (n, f) => { f(n); n.children.forEach(c => walk(c, f)); };
  // lazy: a folder whose files are not loaded yet (Files mode) can still be opened
  const real = n => n.children.length > 0;
  const hasKids = n => real(n) || !!n.lazy;
  // a click on a folded node: it and its children that have children of their own (two levels)
  const openTwo = (n, open) => { if (hasKids(n)) open.add(n.key); n.children.forEach(c => real(c) && open.add(c.key)); };
  const openAll = (n, open) => { if (hasKids(n)) open.add(n.key); walk(n, x => real(x) && open.add(x.key)); };   // a double-click
  const closeAll = (n, open) => walk(n, x => open.delete(x.key));                // with everything under it
  const toggle = (n, open) => open.has(n.key) ? closeAll(n, open) : openTwo(n, open);

  // D4: the path to an agent that needs you opens by itself, once, when it first needs you (so you can fold
  // it again). seen: the keys of the agents that needed you at the last look; returns the same for this one.
  function openForNeeds(nodes, seen, open) {
    const now = new Set();
    const go = (n, way) => {
      if (n.item && n.item.needs) { now.add(n.key); if (!seen.has(n.key)) way.forEach(k => open.add(k)); }
      n.children.forEach(c => go(c, way.concat(n.key)));
    };
    nodes.forEach(n => go(n, []));
    return now;
  }

  // the lines shown, top to bottom: {node, depth, open}; force: everything open (while filtering)
  function lines(nodes, open, force) {
    const out = [];
    const go = (n, depth) => {
      const isOpen = hasKids(n) && (open.has(n.key) || (force && real(n)));
      out.push({node: n, depth, open: isOpen});
      if (isOpen) n.children.forEach(c => go(c, depth + 1));
    };
    nodes.forEach(n => go(n, 0));
    return out;
  }

  // Files mode: this server's tree as the folders and files on disk, in place of its agents' nesting (another
  // machine's tree stays as it is). get(path) is a folder's listing ({dirs, files}, see lib/agent_files.py
  // dir_listing) once loaded, else undefined. A folder holding an index.html is that agent's node (byPath:
  // path -> item); the others are plain names. A folder opens when you click it; its listing is then loaded.
  function addFiles(nodes, get, byPath) {
    const fill = (n, path) => {
      n.lazy = true; n.dir = path; n.children = [];
      const d = get(path);
      if (!d) return;
      d.dirs.forEach(x => {
        const p = path ? path + "/" + x.name : x.name;
        const c = node(n.tree, p, x.name);
        c.item = byPath[p] || null;
        if (x.out) c.agents = 0; else fill(c, p);
        n.children.push(c);
      });
      d.files.forEach(f => {
        const c = node(n.tree, path ? path + "/" + f.name : f.name, f.name);
        c.file = f;
        n.children.push(c);
      });
    };
    nodes.forEach(n => { if (!n.tree) { const keep = n.item; fill(n, ""); n.item = keep; n.agents = n.needs = n.working = 0; } });
  }

  // what a folded node says about what is under it
  function rollup(n) {
    const plural = (k, w) => k + " " + w + (k === 1 ? "" : "s");
    return {count: n.item ? n.agents + " below" : plural(n.agents, "agent"),
            needs: n.needs ? n.needs + " needs you" : "", working: n.working ? n.working + " working" : ""};
  }

  const model = {build, addFiles, openTwo, openAll, closeAll, toggle, openForNeeds, lines, rollup};
  if (typeof module !== "undefined" && module.exports) { module.exports = model; return; }

  // ---- the view ----
  const L = window.diraiList;
  if (!L) return;
  const css = `#rv-tree{margin:.5rem 0;font:14px system-ui}
  #rv-tree .bar{display:flex;gap:8px;margin:0 0 6px}
  #rv-tree .bar button{padding:3px 12px;border-radius:12px;border:1px solid #888;background:none;color:inherit;font:600 12px system-ui;cursor:pointer}
  #rv-tree .bar button.on{background:#3b5bdb;border-color:#3b5bdb;color:#fff}
  #rv-tree .fn{color:var(--muted,#6e6e73);word-break:break-all} #rv-tree a.fn{color:var(--link,#0b63ce)}
  #rv-tree .sz{margin-left:auto;color:var(--muted,#6e6e73);font-size:11px;white-space:nowrap}
  #rv-tree .ln{display:flex;align-items:center;gap:6px;padding:3px 4px;border-bottom:1px solid var(--line,#e5e5ea);user-select:none}
  #rv-tree .ln.kids{cursor:pointer} #rv-tree .ln:hover{background:rgba(128,128,128,.1)}
  #rv-tree .car{flex:none;width:12px;color:var(--muted,#6e6e73);font-size:11px}
  #rv-tree .ico{flex:none}
  #rv-tree .pn{color:var(--muted,#6e6e73)}
  #rv-tree .nm{color:var(--link,#0b63ce);text-decoration:none;word-break:break-all} #rv-tree .nm:hover{text-decoration:underline}
  #rv-tree .roll{color:var(--muted,#6e6e73);font-size:12px}
  #rv-tree .roll .need{color:#c62828;font-weight:600} #rv-tree .roll .work{color:#b26b00;font-weight:600}
  #rv-tree .none{padding:1rem .5rem;color:var(--muted,#6e6e73)}
  #rv-treecard{position:fixed;z-index:99999;width:340px;padding:8px 10px;border-radius:6px;background:#fffbe6;color:#1d1d1f;
    border:1px solid #e0c060;font:12px system-ui;box-shadow:0 2px 10px rgba(0,0,0,.2);pointer-events:none}
  #rv-treecard .k{font-weight:600;margin-top:4px} #rv-treecard .k:first-child{margin-top:0}
  #rv-treecard .v{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere}`;
  document.head.insertAdjacentHTML("beforeend", "<style>" + css + "</style>");
  // the agent icon: a robot head
  const ICON = '<svg class="ico" width="14" height="14" viewBox="0 0 14 14"><line x1="7" y1="2" x2="7" y2="4" stroke="#3b5bdb" stroke-width="1.4"/>' +
    '<circle cx="7" cy="1.4" r="1.4" fill="#3b5bdb"/><rect y="4" width="14" height="10" rx="3" fill="#3b5bdb"/>' +
    '<circle cx="4.5" cy="9" r="1.6" fill="#fff"/><circle cx="9.5" cy="9" r="1.6" fill="#fff"/></svg>';

  const box = document.createElement("div");
  box.id = "rv-tree"; box.hidden = true;
  box.innerHTML = '<div class="bar"><button data-do="agents" title="On: agents only, nested by path. Off: the folders and files on disk">Agents</button>' +
    '<button data-do="star" title="Show only the starred agents (turns Agents on)">★</button></div><div class="body"></div>';
  document.getElementById("rv-nofav").before(box);
  const body = box.querySelector(".body");
  const q = document.getElementById("q");

  let open = new Set(), seen = new Set(), shown = false, drawn = "", cur = [], files = false, starOnly = false;
  const folders = new Map(), pending = new Set();     // Files mode: "agent|sub" -> listing, loaded when its folder opens
  try { files = localStorage.getItem("dirai-tree-mode") === "files"; } catch (e) {}
  try { starOnly = !files && localStorage.getItem("dirai-tree-star") === "1"; } catch (e) {}
  const saveStar = () => { try { localStorage.setItem("dirai-tree-star", starOnly ? "1" : ""); } catch (e) {} };
  try { open = new Set(JSON.parse(localStorage.getItem("dirai-tree-open") || "[]")); } catch (e) {}
  const save = () => { try { localStorage.setItem("dirai-tree-open", JSON.stringify([...open])); } catch (e) {} };

  // the visible rows of the agent list: the filter box and the Machines ticks have already applied
  const items = () => L.rows().filter(tr => !tr.classList.contains("rv-off") && !tr.hidden && (!starOnly || L.isFav(tr))).map(tr => {
    const s = L.info(tr);
    return {tree: tr.dataset.tree || "", path: tr.dataset.agent, needs: !!(s.asking || s.denied), working: s.status === "working", tr};
  });
  // the status badge the table row already has (agent_list.js paint), and its ⏰
  const badge = tr => {
    const b = tr.querySelector(".rv-badge"), r = tr.querySelector(".rv-rep");
    return b ? {cls: b.className, text: b.textContent, title: b.title, rep: r ? r.textContent : "", repTitle: r ? r.title : ""} : null;
  };

  function draw() {
    if (!shown) return;
    box.querySelector('[data-do="star"]').classList.toggle("on", starOnly);
    box.querySelector('[data-do="agents"]').classList.toggle("on", !files);
    const nodes = model.build(items(), L.roots()), filtering = !!q.value.trim();
    if (files) {
      const byPath = {};
      items().forEach(it => { if (!it.tree) byPath[it.path] = it; });
      model.addFiles(nodes, p => folders.get(p), byPath);
      cur = model.lines(nodes, open, false);     // a folder is opened by you, not by the filter
      cur.forEach(l => l.open && l.node.dir !== undefined && load(l.node.dir));
    } else seen = model.openForNeeds(nodes, seen, open);
    save();
    if (!files) cur = model.lines(nodes, open, filtering);
    // what is shown, as data: nothing is redrawn (and a hover not disturbed) while it is the same
    const view = cur.map(l => ({k: l.node.key, d: l.depth, o: l.open, n: l.node.name, kids: hasKids(l.node),
      roll: l.node.agents && !l.open ? model.rollup(l.node) : null,
      f: l.node.file ? {s: l.node.file.size} : null,
      a: l.node.item ? {fav: L.isFav(l.node.item.tr), badge: badge(l.node.item.tr),
                        href: l.node.item.tr.querySelector("a").getAttribute("href")} : null}));
    const sig = JSON.stringify(view);
    if (sig === drawn) return;
    drawn = sig;
    hideCard();
    body.textContent = "";
    if (!cur.length) { body.innerHTML = '<div class="none">No agents.</div>'; return; }
    cur.forEach((l, i) => body.appendChild(line(l, view[i])));
  }
  // Files mode: the listing of one folder of this server, once (a change shows after turning Agents on and off)
  function load(path) {
    if (folders.has(path) || pending.has(path)) return;
    pending.add(path);
    fetch("/_review/ls?path=" + encodeURIComponent(path))
      .then(r => r.ok ? r.json() : null).catch(() => null)
      .then(j => { pending.delete(path); folders.set(path, j || {dirs: [], files: []}); draw(); });
  }
  const size = n => n < 1024 ? n + " B" : n < 1 << 20 ? Math.round(n / 1024) + " KB" : (n / (1 << 20)).toFixed(1) + " MB";
  const IMG = /\.(png|jpe?g|gif|svg|webp|html)$/i;
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };
  // the page address of a file node: its path from the tree's root, under this server
  const pathOf = n => n.tree ? "" : "/" + n.path.split("/").map(encodeURIComponent).join("/");
  const last = {key: "", t: 0};
  function line(l, v) {
    const n = l.node, ln = el("div", "ln" + (v.kids ? " kids" : ""));
    ln.style.paddingLeft = 4 + 18 * l.depth + "px";
    ln.appendChild(el("span", "car", v.kids ? (l.open ? "▾" : "▸") : ""));
    if (v.f) {
      // a file of an agent's folder; only images and .html are served as pages
      const dirOf = pathOf(n);
      const a = IMG.test(n.name) && dirOf ? el("a", "fn", n.name) : el("span", "fn", n.name);
      if (a.tagName === "A") a.setAttribute("href", dirOf);
      ln.appendChild(a);
      ln.appendChild(el("span", "sz", size(v.f.s)));
    } else if (v.a) {
      const star = el("button", "rv-star" + (v.a.fav ? " on" : ""), v.a.fav ? "★" : "☆");
      star.title = v.a.fav ? "Remove from favorites" : "Add to favorites";
      star.onclick = () => L.star(n.item.tr);
      ln.appendChild(star);
      ln.insertAdjacentHTML("beforeend", ICON);
      const a = el("a", "nm", n.name);
      if (v.a.href) a.setAttribute("href", v.a.href);
      hover(a, n.item.tr);
      ln.appendChild(a);
      const b = v.a.badge;
      if (b) {
        const s = el("span", b.cls, b.text);
        if (b.title) s.title = b.title;
        ln.appendChild(s);
        if (b.rep) { const r = el("span", "rv-rep", b.rep); r.title = b.repTitle; ln.appendChild(r); }
      }
    } else ln.appendChild(el("span", "pn", n.name));
    if (v.roll) {
      const r = el("span", "roll", v.roll.count);
      if (v.roll.needs) r.append(" · ", el("span", "need", v.roll.needs));
      if (v.roll.working) r.append(" · ", el("span", "work", v.roll.working));
      ln.appendChild(r);
    }
    if (v.kids) {
      // a click anywhere on the line but the name and the star: open two levels, or fold; a double-click: open everything under it
      const skip = e => e.target.closest("a,button");
      // The line is redrawn by the first click, so the browser's dblclick event never reaches it: a second click
      // on the same node within 350 ms is the double-click.
      ln.onclick = e => {
        if (skip(e)) return;
        const t = Date.now(), twice = last.key === n.key && t - last.t < 350;
        last.key = twice ? "" : n.key; last.t = t;
        if (twice) model.openAll(n, open); else model.toggle(n, open);
        save(); draw();
      };
    }
    return ln;
  }

  // Hovering an agent's name for 300 ms shows its summary card (fetched once per page load)
  const cards = new Map();
  const card = document.createElement("div");
  card.id = "rv-treecard"; card.hidden = true;
  document.body.appendChild(card);
  let timer = 0;
  function hideCard() { clearTimeout(timer); card.hidden = true; }
  function hover(a, tr) {
    a.onmouseenter = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        const key = (tr.dataset.tree || "") + "|" + tr.dataset.agent;
        if (!cards.has(key)) cards.set(key, L.card(tr).catch(() => ({})));
        cards.get(key).then(c => {
          if (!a.isConnected || !a.matches(":hover")) return;
          card.textContent = "";
          const fields = [["objective", "Objective"], ["result", "Result"], ["open", "Open"], ["updated", "Updated"]]
            .filter(([k]) => c && c[k]);
          if (!fields.length) card.appendChild(el("div", "v", "No summary card."));
          fields.forEach(([k, label]) => { card.appendChild(el("div", "k", label)); card.appendChild(el("div", "v", c[k])); });
          const r = a.getBoundingClientRect();
          card.hidden = false;
          card.style.left = Math.max(4, Math.min(r.left, innerWidth - card.offsetWidth - 8)) + "px";
          card.style.top = (r.bottom + card.offsetHeight + 8 > innerHeight ? Math.max(4, r.top - card.offsetHeight - 4) : r.bottom + 4) + "px";
        });
      }, 300);
    };
    a.onmouseleave = a.onclick = hideCard;
  }

  // Agents on: agents only; off: the folders and files on disk
  box.querySelector('[data-do="agents"]').onclick = () => {
    files = !files;
    if (files) { starOnly = false; saveStar(); }      // ★ is an Agents-view filter
    try { localStorage.setItem("dirai-tree-mode", files ? "files" : "agents"); } catch (e) {}
    folders.clear(); drawn = ""; draw();
  };
  box.querySelector('[data-do="star"]').onclick = () => {
    starOnly = !starOnly; saveStar();
    if (starOnly && files) { files = false; try { localStorage.setItem("dirai-tree-mode", "agents"); } catch (e) {} folders.clear(); }
    // every starred agent in sight: open the way to each (a fold left from before would hide it); you can fold again
    if (starOnly) { model.build(items(), L.roots()).forEach(n => model.openAll(n, open)); save(); }
    drawn = ""; draw();
  };
  q.addEventListener("input", draw);
  L.onChange(draw);
  L.addView("tree", "Tree", on => { shown = on; box.hidden = !on; if (on) draw(); else hideCard(); });
})();
