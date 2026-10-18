#!/usr/bin/env python3
"""Regenerate <root>/www/index.html with links to every index.html page (agent) under <root>.

Usage: build_index.py [ROOT] [--sizes]   (ROOT defaults to the top of the git repo holding the
current directory; DirAI build runs it for the tree you are in.)

Skipped folders: PRUNE_DIRS anywhere, other trees' www/ data folders, and the tree's dirai.json
"exclude" list (folder names anywhere, or tree-relative paths with a slash).

Each row shows the size of everything under the page's folder. Sizes are cached in
www/page_sizes.json together with the page's index.html mtime, and a folder is measured again
only when its index.html changed (or is new): a normal run uses the cache and, if any page needs
measuring, starts "build_index.py ROOT --sizes" in the background, which measures just those
folders, updates the cache and rewrites the page.

Each row also shows the tokens used by the Claude Code sessions run in that folder (or a
subfolder not holding a page of its own), read from the transcripts in ~/.claude/projects
(input + cache writes + cache reads + output, subagents included; breakdown on hover).
Per-transcript sums are cached in www/page_tokens.json, keyed by file size and mtime.

Each run prints how long each step took (find pages, size cache, measure sizes, tokens,
write index.html).

Links are relative (../<path>), so they work both when the page is opened from an
rsync'd copy of the HTML files and when ROOT is served over HTTP.
"""
import datetime
import html
import json
import os
import re
import stat
import subprocess
import sys
import time

import dirai_config

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
ROOT = os.path.abspath(ARGS[0]) if ARGS else \
    subprocess.run(["git", "rev-parse", "--show-toplevel"], stdout=subprocess.PIPE,
                   universal_newlines=True, check=True).stdout.strip()
TITLE = os.environ.get("DIRAI_TITLE") or ROOT   # list page heading: the tree's path
OUT = os.path.join(ROOT, "www", "index.html")
SIZES = os.path.join(ROOT, "www", "page_sizes.json")
SIZE_LOCK = SIZES + ".lock"
TOKENS = os.path.join(ROOT, "www", "page_tokens.json")
TRANSCRIPTS = dirai_config.TRANSCRIPTS
PRUNE_DIRS = {".git", "node_modules", "__pycache__", ".claude", ".venv", "venv", "site-packages",
              ".tox", ".mypy_cache", ".pytest_cache", ".ipynb_checkpoints"}
_EXCLUDE = dirai_config.tree_config(ROOT)["exclude"]
PRUNE_DIRS |= {e.strip("/") for e in _EXCLUDE if "/" not in e.strip("/")}
PRUNE_PATHS = {os.path.join(ROOT, e.strip("/")) for e in _EXCLUDE if "/" in e.strip("/")}


def keep_dir(dirpath, name):
    """False for folders the page scan skips."""
    full = os.path.join(dirpath, name)
    if name in PRUNE_DIRS or full in PRUNE_PATHS:
        return False
    # another tree's data folder (its list page, threads, caches)
    return not (name == "www" and os.path.isfile(os.path.join(full, "dirai.json")))
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def page_title(path):
    # Only look near the top: big plotly pages carry unrelated <title> tags in SVG/JS.
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            head = f.read(4096)
    except OSError:
        return ""
    m = TITLE_RE.search(head)
    return " ".join(m.group(1).split()) if m else ""


class Steps:
    """Wall time of each step, printed as it finishes."""
    def __init__(self):
        self.start = self.last = time.time()

    def done(self, name, detail=""):
        now = time.time()
        print("  %-18s %7.2fs  %s" % (name, now - self.last, detail), flush=True)
        self.last = now

    def total(self):
        print("  %-18s %7.2fs" % ("total", time.time() - self.start), flush=True)


def find_pages(stats=None):
    """Pages, newest first. "dir" is the page folder relative to ROOT ("" for ROOT itself)."""
    pages = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        if stats is not None:
            stats["walked"] = stats.get("walked", 0) + 1
        dirnames[:] = sorted(d for d in dirnames if keep_dir(dirpath, d))
        if "index.html" not in filenames:
            continue
        full = os.path.join(dirpath, "index.html")
        if full == OUT:
            continue
        rel_dir = os.path.relpath(dirpath, ROOT)
        pages.append({"dir": "" if rel_dir == "." else rel_dir, "title": page_title(full),
                      "mtime": os.path.getmtime(full)})
    pages.sort(key=lambda p: p["mtime"], reverse=True)
    return pages


def folder_size(path):
    """Bytes of all regular files under path (symlinks and PRUNE_DIRS skipped)."""
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS]
        for name in filenames:
            try:
                st = os.lstat(os.path.join(dirpath, name))
            except OSError:
                continue
            if not stat.S_ISLNK(st.st_mode):
                total += st.st_size
    return total


def load_cache():
    try:
        return dirai_config.load_json(SIZES, {}).get("pages", {})
    except AttributeError:
        return {}


def save_cache(cache):
    dirai_config.save_json(SIZES, {"pages": cache}, indent=1)


def stale(pages, cache):
    """Pages whose folder size is missing or older than their index.html."""
    return [p for p in pages if cache.get(p["dir"], {}).get("mtime") != p["mtime"]]


def measure_in_background():
    """Start a detached --sizes run unless one is already going (lock younger than 1 h)."""
    try:
        if time.time() - os.path.getmtime(SIZE_LOCK) < 3600:
            return
        os.remove(SIZE_LOCK)
    except OSError:
        pass
    try:
        os.close(os.open(SIZE_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except OSError:
        return
    subprocess.Popen([sys.executable, os.path.abspath(__file__), ROOT, "--sizes"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def transcript_usage(path):
    """cwd and [input, cache write, cache read, output] tokens of one transcript.
    A message split over several lines repeats its usage, so count each message id once."""
    cwd, tok, seen = None, [0, 0, 0, 0], set()
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if cwd and '"usage"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            cwd = cwd or d.get("cwd")
            m = d.get("message")
            u = m.get("usage") if isinstance(m, dict) else None
            if not isinstance(u, dict) or m.get("id") in seen:
                continue
            seen.add(m.get("id"))
            for i, k in enumerate(("input_tokens", "cache_creation_input_tokens",
                                   "cache_read_input_tokens", "output_tokens")):
                tok[i] += u.get(k) or 0
    return cwd, tok


def session_tokens(pages, stats=None):
    """{page dir: {"tok": [in, cache write, cache read, out], "sessions": n}}. A transcript goes
    to the deepest page folder holding its cwd; subagent transcripts add tokens, not sessions."""
    cache = dirai_config.load_json(TOKENS, {})
    new = {}
    for dirpath, dirnames, filenames in os.walk(TRANSCRIPTS):
        for name in filenames:
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(dirpath, name)
            try:
                st = os.stat(path)
            except OSError:
                continue
            key = [st.st_size, st.st_mtime]
            c = cache.get(path)
            if stats is not None:
                stats["files"] = stats.get("files", 0) + 1
            if not c or c["key"] != key:
                if stats is not None:
                    stats["read"] = stats.get("read", 0) + 1
                try:
                    cwd, tok = transcript_usage(path)
                except OSError:
                    continue
                c = {"key": key, "cwd": cwd, "tok": tok, "sub": "subagents" in dirpath.split(os.sep)}
            new[path] = c
    try:
        dirai_config.save_json(TOKENS, new)
    except OSError:
        pass
    roots = {os.path.abspath(ROOT), os.path.realpath(ROOT)}
    dirs = {p["dir"] for p in pages}
    out = {}
    for c in new.values():
        cwd = c["cwd"]
        if not cwd:
            continue
        rel = next((os.path.relpath(cwd, r) for r in roots if dirai_config.within(cwd, r)), None)
        if rel is None:
            continue
        rel = "" if rel == "." else rel
        while rel not in dirs and rel:
            rel = os.path.dirname(rel)
        if rel not in dirs:
            continue
        o = out.setdefault(rel, {"tok": [0, 0, 0, 0], "sessions": 0})
        o["tok"] = [a + b for a, b in zip(o["tok"], c["tok"])]
        o["sessions"] += 0 if c["sub"] else 1
    return out


def human_count(n):
    for unit in ("", "K", "M", "G"):
        if n < 1000 or unit == "G":
            return "%d" % n if unit == "" else "%.1f%s" % (n, unit)
        n /= 1000.0


def human_size(n):
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024 or unit == "T":
            return "%.0f%s" % (n, unit) if unit == "B" else "%.1f%s" % (n, unit)
        n /= 1024.0


def render(pages, cache, tokens):
    rows = []
    for p in pages:
        label = html.escape(p["dir"] + "/" if p["dir"] else "(top)")
        href = html.escape("../" + (p["dir"] + "/" if p["dir"] else "") + "index.html", quote=True)
        title = html.escape(p["title"]) if p["title"] else ""
        when = datetime.datetime.fromtimestamp(p["mtime"]).strftime("%Y-%m-%d %H:%M")
        c = cache.get(p["dir"])
        if c and c.get("mtime") == p["mtime"]:
            measured = datetime.datetime.fromtimestamp(c["measured"]).strftime("%Y-%m-%d %H:%M")
            size = '<td class="num" data-v="%d" title="measured %s">%s</td>' % (
                c["size"], measured, human_size(c["size"]))
        else:
            size = '<td class="num" data-v="-1" title="being measured">&hellip;</td>'
        t = tokens.get(p["dir"])
        if t:
            tok = '<td class="num" data-v="%d" title="%d session%s&#10;input %s&#10;cache write %s&#10;cache read %s&#10;output %s">%s</td>' % (
                sum(t["tok"]), t["sessions"], "" if t["sessions"] == 1 else "s",
                *(human_count(x) for x in t["tok"]), human_count(sum(t["tok"])))
        else:
            tok = '<td class="num" data-v="0"></td>'
        rows.append('<tr><td data-v="%s"><a href="%s">%s</a>%s</td><td class="num" data-v="%d">%s</td>%s%s</tr>'
                    % (label, href, label, '<div class="sub">%s</div>' % title if title else "",
                       p["mtime"], when, size, tok))
    generated = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    return TEMPLATE.format(title=html.escape(TITLE), count=len(pages), generated=generated, rows="\n".join(rows))


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ --bg:#fff; --fg:#1d1d1f; --muted:#6e6e73; --line:#e5e5ea; --link:#0b63ce; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#1c1c1e; --fg:#f2f2f7; --muted:#a1a1a6; --line:#38383a; --link:#5aa9ff; }}
  }}
  body {{ background:var(--bg); color:var(--fg); font-family:system-ui,sans-serif;
         max-width:60rem; margin:2rem auto; padding:0 16px; }}
  h1 {{ margin-bottom:.25rem; }}
  .meta, .sub {{ color:var(--muted); font-size:.85rem; }}
  input {{ width:100%; box-sizing:border-box; padding:.5rem .75rem; margin:1rem 0;
          font-size:1rem; border:1px solid var(--line); border-radius:6px;
          background:var(--bg); color:var(--fg); }}
  table {{ width:100%; border-collapse:collapse; }}
  th, td {{ text-align:left; padding:.45rem .5rem; border-bottom:1px solid var(--line);
           vertical-align:top; }}
  th {{ font-size:.8rem; color:var(--muted); font-weight:600; cursor:pointer; user-select:none; white-space:nowrap; }}
  th:hover {{ color:var(--fg); }}
  td a {{ color:var(--link); text-decoration:none; word-break:break-all; }}
  td a:hover {{ text-decoration:underline; }}
  .num {{ white-space:nowrap; color:var(--muted); font-variant-numeric:tabular-nums; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="meta">{count} agents &middot; generated {generated}
  by <code>www/build_index.py</code> &middot; click a column to sort</div>
<input id="q" type="search" placeholder="Filter by folder or title&hellip;" autofocus>
<table>
<thead><tr><th data-col="0">Agent</th><th data-col="1">Modified</th>
  <th data-col="2" title="everything under the agent's folder; re-measured when its index.html changes">Folder size</th>
  <th data-col="3" title="tokens of the Claude Code sessions run in this folder (input + cache write + cache read + output); hover a cell for the breakdown">Tokens</th></tr></thead>
<tbody id="rows">
{rows}
</tbody>
</table>
<script>
  const q = document.getElementById("q");
  const tbody = document.getElementById("rows");
  const rows = [...tbody.querySelectorAll("tr")];
  q.addEventListener("input", () => {{
    const terms = q.value.toLowerCase().split(/\\s+/).filter(Boolean);
    for (const r of rows) {{
      const text = r.textContent.toLowerCase();
      r.hidden = !terms.every(t => text.includes(t));
    }}
  }});
  // click a header to sort by it, again to reverse; marks the table as user-sorted so the
  // status-badge script (owner view) stops reordering it
  let sortCol = null, sortDir = 1;
  document.querySelectorAll("th[data-col]").forEach(th => th.addEventListener("click", () => {{
    const col = +th.dataset.col;
    sortDir = sortCol === col ? -sortDir : (col === 0 ? 1 : -1);   // names A-Z first, numbers largest first
    sortCol = col;
    const key = r => r.children[col].dataset.v;
    rows.slice().sort((a, b) => col === 0 ? sortDir * key(a).localeCompare(key(b)) : sortDir * (key(a) - key(b)))
      .forEach(r => tbody.appendChild(r));
    tbody.dataset.userSort = "1";
    document.querySelectorAll("th[data-col]").forEach(h => h.textContent = h.textContent.replace(/ [▲▼]$/, ""));
    th.textContent += sortDir > 0 ? " ▲" : " ▼";
  }}));
</script>
</body>
</html>
"""


if __name__ == "__main__":
    measuring = "--sizes" in sys.argv[1:]
    steps = Steps()
    try:
        walk = {}
        pages = find_pages(walk)
        steps.done("find pages", "%d folders walked, %d pages" % (walk.get("walked", 0), len(pages)))
        cache = load_cache()
        todo = stale(pages, cache)
        steps.done("size cache", "%d of %d folders stale" % (len(todo), len(pages)))
        if measuring:
            took = []
            for p in todo:
                t0 = time.time()
                cache[p["dir"]] = {"mtime": p["mtime"], "measured": time.time(),
                                   "size": folder_size(os.path.join(ROOT, p["dir"]))}
                took.append((time.time() - t0, p["dir"] or "(top)"))
            known = {p["dir"] for p in pages}
            cache = {d: v for d, v in cache.items() if d in known}   # forget removed pages
            save_cache(cache)
            slowest = ", ".join("%s %.1fs" % (d, t) for t, d in sorted(took, reverse=True)[:3])
            steps.done("measure sizes", "%d folders%s" % (len(todo), "; slowest: " + slowest if took else ""))
        elif todo:
            measure_in_background()
            steps.done("measure sizes", "started in background for %d folders" % len(todo))
        else:
            steps.done("measure sizes", "nothing to measure")
        tstats = {}
        tokens = session_tokens(pages, tstats)
        steps.done("tokens", "%d transcripts, %d read, %d cached, %d pages with sessions" % (
            tstats.get("files", 0), tstats.get("read", 0),
            tstats.get("files", 0) - tstats.get("read", 0), len(tokens)))
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT + ".tmp", "w", encoding="utf-8") as f:
            f.write(render(pages, cache, tokens))
        os.replace(OUT + ".tmp", OUT)
        steps.done("write index.html")
        steps.total()
    finally:
        if measuring:
            try:
                os.remove(SIZE_LOCK)
            except OSError:
                pass
    print("Wrote %s (%d agents%s)" % (OUT, len(pages),
                                      ", measured %d folders" % len(todo) if measuring else ""))
