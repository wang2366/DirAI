// The Tree tab's model (web/agent_tree.js, part 1) under node: nesting by path, joined plain paths,
// roll-ups, what a click / double-click opens, and the path to an agent that needs you. Run by
// test_tree.py. Exits 1 on a failure.
const model = require("../web/agent_tree.js");

let failed = 0;
const check = (ok, what) => { console.log((ok ? "ok   " : "FAIL ") + what); if (!ok) failed++; };
const item = (tree, path, extra) => Object.assign({tree, path, needs: false, working: false}, extra);
const names = (lines) => lines.map(l => "  ".repeat(l.depth) + l.node.name + (l.open ? "-" : "") );
const same = (a, b, what) => check(JSON.stringify(a) === JSON.stringify(b), what + (JSON.stringify(a) === JSON.stringify(b) ? "" : ": " + JSON.stringify(a)));

const trees = [{id: "", name: "here"}, {id: "t1", name: "far"}, {id: "t2", name: "empty"}];
const items = [
  item("", "nanowire"), item("", "nanowire/bands", {working: true}), item("", "nanowire/bands/strain", {needs: true}),
  item("", "nanowire/transport"), item("", "papers/a"), item("", "papers/b"),
  item("", "archive/2025/q3/fit"), item("", "archive/2025/q3/plots"),
  item("t1", "", {working: true}), item("t1", "x/y/z"),
];
let nodes = model.build(items, trees);

same(nodes.map(n => n.name), ["here", "far"], "a tree with no agents is left out");
const here = nodes[0];
same(here.children.map(c => c.name), ["archive/2025/q3", "nanowire", "papers"],
     "a chain of plain paths is one line (archive/2025/q3); papers has no index.html of its own and stays plain");
const nano = here.children[1];
check(nano.item && nano.children.length === 2, "nanowire is one node: the agent, with its subagents under it");
check(here.agents === 8 && here.needs === 1 && here.working === 1, "roll-up of a tree: 8 agents, 1 needs you, 1 working");
check(nano.agents === 3 && nano.needs === 1, "roll-up of an agent does not count itself");
same(model.rollup(nano), {count: "3 below", needs: "1 needs you", working: "1 working"}, "an agent's roll-up says 'below'");
same(model.rollup(here.children[2]), {count: "2 agents", needs: "", working: ""}, "a plain path's roll-up says 'agents'");
const far = nodes[1];
check(far.item && far.item.working && far.children.length === 1 && far.children[0].name === "x/y" && far.children[0].children[0].item,
      "a tree whose top folder is an agent: the top node is that agent; the plain x/y is joined, the agent z stays its own node");

// nothing open: one line per tree
let open = new Set();
same(names(model.lines(nodes, open, false)), ["here", "far"], "all folded: one line per tree");
open = new Set([here.key, far.key]);
same(names(model.lines(nodes, open, false)), ["here-", "  archive/2025/q3", "  nanowire", "  papers", "far-", "  x/y"],
     "opening a tree's top node shows level 1");

// a click: two levels
open = new Set();
model.toggle(here, open);
same(names(model.lines(nodes, open, false)),
     ["here-", "  archive/2025/q3-", "    fit", "    plots", "  nanowire-", "    bands", "    transport", "  papers-", "    a", "    b", "far"],
     "a click opens the node and its children that have children: children and grandchildren show, bands (3 levels down) stays folded");
open = new Set([here.key]);
model.toggle(nano, open);
same(names(model.lines(nodes, open, false)).slice(0, 6), ["here-", "  archive/2025/q3", "  nanowire-", "    bands-", "      strain", "    transport"],
     "clicking nanowire opens it and bands; strain, three down, has no children");
model.toggle(nano, open);
check(!open.has(nano.key) && !open.has(nano.children[0].key) && open.has(here.key), "a click on an open node folds it with everything under it");

// a double-click: everything under it
open = new Set();
model.openAll(here, open);
check(model.lines(nodes, open, false).length === 12, "a double-click opens everything under the node (11 lines under here, then far)");
check(!open.has(far.key), "...and nothing outside it");

// filtering forces everything open
check(model.lines(nodes, new Set(), true).length === 14, "while filtering, every node is open");

// D4: the path to an agent that needs you opens when it first needs you, and not again
open = new Set();
let seen = model.openForNeeds(nodes, new Set(), open);
same([...open].sort(), ["|", "|nanowire", "|nanowire/bands"], "the nodes on the way to strain open");
check(seen.has("|nanowire/bands/strain") && seen.size === 1, "...and strain is remembered");
open.delete("|nanowire/bands");
seen = model.openForNeeds(nodes, seen, open);
check(!open.has("|nanowire/bands"), "folded again by you: it stays folded while strain still needs you");
const gone = model.build(items.map(i => Object.assign({}, i, {needs: false})), trees);
seen = model.openForNeeds(gone, seen, open);
check(seen.size === 0, "when it stops needing you it is forgotten...");
seen = model.openForNeeds(nodes, seen, open);
check(open.has("|nanowire/bands"), "...so the next time opens the path again");

// Files mode: this server's tree as the folders and files on disk; a far tree stays as it is
const listing = {"": {dirs: [{name: "nanowire", agent: true}, {name: "docs", agent: false}, {name: "linked", agent: false, out: true}], files: [{name: "top.txt", size: 3}]},
                 "nanowire": {dirs: [{name: "bands", agent: true}, {name: "data", agent: false}], files: [{name: "run.sh", size: 9}]},
                 "docs": {dirs: [], files: [{name: "a.md", size: 1}]}};
const byPath = {}; items.filter(i => !i.tree).forEach(i => byPath[i.path] = i);
const fnodes = model.build(items, trees);
model.addFiles(fnodes, p => listing[p], byPath);
const froot = fnodes[0];
same(froot.children.map(c => c.name), ["nanowire", "docs", "linked", "top.txt"], "this server's tree is the folders then the files on disk (plain agent nesting is gone)");
const fnano = froot.children[0];
check(fnano.item && fnano.item.path === "nanowire" && froot.children[1].item === null, "a folder with an index.html is that agent's node, the others are plain");
check(froot.children[2].lazy === undefined && froot.children[2].children.length === 0, "a link out of the tree is a name and does not open");
same(fnano.children.map(c => c.name), ["bands", "data", "run.sh"], "...and nanowire holds its folders and files");
const bands = fnano.children[0], data = fnano.children[1];
check(bands.lazy && bands.children.length === 0 && data.lazy, "a folder whose listing is not loaded opens (to be loaded), empty for now");
same(fnodes[1].children.map(c => c.name), ["x/y"], "the far tree is unchanged");
open = new Set([froot.key, fnano.key]);
same(names(model.lines(fnodes, open, false)).slice(0, 8), ["here-", "  nanowire-", "    bands", "    data", "    run.sh", "  docs", "  linked", "  top.txt"],
     "open folders show their folders and files");
open = new Set();
model.openAll(froot, open);
check(open.has(froot.key) && open.has(fnano.key) && !open.has(bands.key), "a double-click opens the loaded folders, not those not loaded yet");

process.exit(failed ? 1 : 0);
