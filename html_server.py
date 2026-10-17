#!/usr/bin/env python3
"""Serve only HTML pages and the images they use under a directory; everything else is 404.
Markdown files (.md) are shown to the owner only, rendered in the browser (see MD_PAGE).

Usage: html_server.py ROOT PORT [BIND_ADDR]    (BIND_ADDR defaults to 0.0.0.0)

A folder URL serves that folder's index.html (no directory listings). Paths that
resolve outside ROOT (e.g. through symlinks) are refused.

The owner (connecting through the SSH tunnel, with the review key cookie) also gets a
review panel on every index.html and the /_review/* API; see review.py.
"""
import http.server
import io
import json
import os
import re
import signal
import socketserver
import subprocess
import sys
import threading
import time
from http import cookies
from urllib.parse import parse_qs, urlparse

import claude_usage
import node_load
import page_status
import review

ROOT = os.path.realpath(sys.argv[1])
PORT = int(sys.argv[2])
BIND = sys.argv[3] if len(sys.argv) > 3 else "0.0.0.0"
ALLOWED_EXT = (".html", ".htm", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")
WWW_DIR = os.path.dirname(os.path.abspath(__file__))


def ui_version():
    """Newest mtime of the scripts served under /_review/ (they are read from disk per request)."""
    return max(os.path.getmtime(os.path.join(WWW_DIR, "review_%s.js" % n)) for n in ("panel", "list", "newagent"))
LIST_PAGE = os.path.join(ROOT, "www", "index.html")
REVIEWS = review.Reviews(ROOT)
HOME_BUTTON = ('<a href="/www/index.html" title="All pages" style="position:fixed;left:16px;bottom:16px;'
               'z-index:99999;padding:8px 14px;border-radius:20px;border:1px solid #888;background:#1d1d1f;'
               'color:#fff;font:600 14px system-ui;text-decoration:none">&#8962; Home</a>')
KEY = review.login_key()
NEWAGENT_TAG = ('<script src="/_review/newagent.js" data-base="%s" data-root="'
                + ROOT.replace("&", "&amp;").replace('"', "&quot;") + '"></script>')
# A .md file is sent inside this page and rendered by the browser: marked for the markdown, KaTeX
# for $...$ / $$...$$ math (taken out before marked so it can't mangle them), mermaid for ```mermaid
# blocks. No Python dependency; the viewer's browser loads the libraries from the CDN.
MD_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(title)s</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
<script src="https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script>
<style>
  :root { --bg: #fbfbf9; --fg: #1d1d1f; --line: #e3e3de; --code-bg: #f2f2ee; --accent: #2f6fdb; }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #161618; --fg: #e8e8e6; --line: #2f2f33; --code-bg: #26262a; --accent: #7aa7ff; }
  }
  body { margin: 0; background: var(--bg); color: var(--fg); font: 16px/1.6 system-ui, sans-serif; }
  main { max-width: 56rem; margin: 0 auto; padding: 2rem 16px 6rem; }
  a { color: var(--accent); }
  img { max-width: 100%%; }
  code { font: .9em ui-monospace, Menlo, monospace; background: var(--code-bg); padding: .1em .3em; border-radius: 4px; }
  pre { background: var(--code-bg); padding: .8rem 1rem; border-radius: 8px; overflow-x: auto; }
  pre code { background: none; padding: 0; }
  pre.mermaid { background: none; }
  table { border-collapse: collapse; display: block; overflow-x: auto; }
  th, td { border: 1px solid var(--line); padding: .35rem .6rem; text-align: left; }
  blockquote { margin: 1rem 0; padding: .2rem 1rem; border-left: 4px solid var(--line); }
  .katex-display { overflow-x: auto; overflow-y: hidden; }
</style></head>
<body><main id="md"></main>
<script type="application/json" id="md-src">%(src)s</script>
<script>
(function () {
  var src = JSON.parse(document.getElementById("md-src").textContent), out = document.getElementById("md");
  if (!window.marked) { out.innerHTML = "<pre></pre>"; out.firstChild.textContent = src; return; }
  var math = [];   // code spans/blocks are kept as they are; math outside them becomes a placeholder
  src = src.replace(/(```[\\s\\S]*?```|`[^`\\n]*`)|\\$\\$([\\s\\S]+?)\\$\\$|\\$([^\\s$](?:[^$\\n]*?[^\\s$])?)\\$/g,
    function (m, code, block, inline) {
      if (code) return code;
      math.push([block != null ? block : inline, block != null]);
      return "MDMATH" + (math.length - 1) + "X";
    });
  var html = marked.parse(src).replace(/MDMATH(\\d+)X/g, function (m, i) {
    var t = math[i];
    if (!window.katex) return t[1] ? "$$" + t[0] + "$$" : "$" + t[0] + "$";
    return katex.renderToString(t[0], {displayMode: t[1], throwOnError: false});
  });
  out.innerHTML = html;
  var blocks = out.querySelectorAll("pre > code.language-mermaid");
  if (blocks.length && window.mermaid) {
    blocks.forEach(function (c) { var p = c.parentNode; p.className = "mermaid"; p.textContent = c.textContent; });
    var dark = window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches;
    mermaid.initialize({startOnLoad: false, theme: dark ? "dark" : "default"});
    mermaid.run({querySelector: "pre.mermaid"});
  }
})();
</script>
</body></html>
"""
HOUSEKEEP_S = 600     # see housekeeping()
REPEAT_CHECK_S = 60   # how often repeated messages (review.REPEATS) are checked for being due
NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.+-]*$")   # no leading dot: no "..", no hidden folders


def clean_rel(rel):
    """Normalized 'a/b' for a folder inside ROOT a New agent may create, else None."""
    parts = [p for p in rel.strip().strip("/").split("/") if p]
    if not parts or not all(NAME_RE.match(p) for p in parts) or parts[0] == "www":
        return None
    full = os.path.realpath(os.path.join(ROOT, *parts))
    return "/".join(parts) if full.startswith(ROOT + os.sep) else None


def list_dirs(prefix, limit=40):
    """Autocomplete: existing folders 'parent/name/' matching what has been typed."""
    parent, _, start = prefix.lstrip("/").rpartition("/")
    base = os.path.realpath(os.path.join(ROOT, parent))
    if base != ROOT and not base.startswith(ROOT + os.sep):
        return []
    try:
        names = sorted(n for n in os.listdir(base) if not n.startswith(".") and n.startswith(start)
                       and os.path.isdir(os.path.join(base, n)) and (parent or n != "www"))
    except OSError:
        return []
    return [(parent + "/" if parent else "") + n + "/" for n in names[:limit]]


def rebuild_list():
    subprocess.run([sys.executable, os.path.join(WWW_DIR, "build_index.py"), ROOT],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def housekeeping():
    """The server's repeated work, every HOUSEKEEP_S: check the SLURM jobs pages are waiting on
    (and message their assistants when done), drop week-old thread entries, then rebuild the list page. The list is built
    once at startup by dirai_serve, so the first pass waits a full interval."""
    while True:
        time.sleep(HOUSEKEEP_S)
        for name, task in (("job check", REVIEWS.check_watches), ("thread prune", REVIEWS.prune_threads),
                           ("list rebuild", rebuild_list)):
            try:
                task()
            except Exception as e:      # one failing task mustn't stop the loop
                print("housekeeping: %s failed: %s" % (name, e), flush=True)


def repeats():
    """Send the pages' repeated messages as they come due (every hour/day/week)."""
    while True:
        time.sleep(REPEAT_CHECK_S)
        try:
            REVIEWS.check_repeats()
        except Exception as e:
            print("repeat check failed: %s" % e, flush=True)


class HtmlOnlyHandler(http.server.SimpleHTTPRequestHandler):
    # --- owner check --------------------------------------------------------------------
    def is_owner(self):
        if self.client_address[0] != "127.0.0.1":
            return False
        c = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        return "review_key" in c and c["review_key"].value == KEY

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # --- /_review/* ---------------------------------------------------------------------
    def do_GET(self):
        url = urlparse(self.path)
        if url.path.startswith("/_review/"):
            return self.review_get(url)
        return super().do_GET()

    def do_POST(self):
        url = urlparse(self.path)
        if not url.path.startswith("/_review/") or not self.is_owner() or self.headers.get("X-Review") != "1":
            return self.send_error(404)
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        except ValueError:
            return self.send_json({"error": "bad request"}, 400)
        action = url.path[len("/_review/"):]
        if action == "new":       # New agent: make the folder + starter page, start the task
            rel, task = clean_rel(body.get("dir", "")), (body.get("task") or "").strip()
            if rel is None:
                return self.send_json({"error": "Folder must be a relative path inside the tree "
                                                "(letters, digits, _ . + -; no '..', hidden or www/ folders)."})
            if not task:
                return self.send_json({"error": "Describe the task."})
            if not REVIEWS.new_page(rel, task, body.get("every") or "off"):
                return self.send_json({"error": "The assistant is already working on %s/." % rel})
            threading.Thread(target=rebuild_list, daemon=True).start()
            return self.send_json({"ok": True, "url": "/%s/" % rel})
        if action == "permissions":   # tree-wide, from the list page: "allowlist" or "ask"
            ok = REVIEWS.set_permissions(body.get("mode"))
            return self.send_json({"ok": True} if ok else {"error": "unknown mode"})
        page = self.page_key(body.get("page", ""))
        if page is None:
            return self.send_json({"error": "no such page"}, 404)
        if action == "comment":
            text = (body.get("text") or "").strip()
            sel = body.get("selection")
            sel = ({"text": str(sel.get("text") or "").strip(), "heading": str(sel.get("heading") or "")}
                   if isinstance(sel, dict) else None)
            ok = bool(text) and REVIEWS.comment(page, text, selection=sel if sel and sel["text"] else None)
        elif action == "status" and body.get("status") in ("read", "unread", "closed"):
            ok = REVIEWS.set_status(page, body["status"])
        elif action == "model":
            ok = REVIEWS.set_model(page, body.get("model"))
        elif action == "repeat":
            ok = REVIEWS.set_repeat(page, body.get("every"), body.get("text"))
            if not ok:
                return self.send_json({"error": "Pick hourly, daily or weekly and give the message to repeat."})
        elif action == "compact":
            ok = REVIEWS.compact(page)
        elif action == "newchat":
            ok = REVIEWS.new_chat(page)
        elif action == "cancel":
            ok = REVIEWS.cancel(page)
        elif action == "grant":
            ok = REVIEWS.grant(page, list(body.get("rules", [])), bool(body.get("always")))
        elif action == "answer":      # Allow / Always allow / Deny on a waiting permission prompt
            if REVIEWS.answer(page, str(body.get("id", "")), body.get("choice")):
                return self.send_json({"ok": True})
            return self.send_json({"error": "That request is no longer waiting (the run ended or it was answered)."})
        else:
            return self.send_error(404)
        self.send_json({"ok": True} if ok else {"error": "Claude is still working on this page, or nothing to do."})

    def review_get(self, url):
        q = parse_qs(url.query)
        action = url.path[len("/_review/"):]
        if action == "login" and self.client_address[0] == "127.0.0.1" and q.get("key", [""])[0] == KEY:
            self.send_response(302)
            self.send_header("Set-Cookie", "review_key=%s; Path=/; Max-Age=31536000; HttpOnly; SameSite=Strict" % KEY)
            self.send_header("Location", "/www/index.html")
            self.end_headers()
            return
        if not self.is_owner():
            return self.send_error(404)
        if action == "all":
            return self.send_json(REVIEWS.all_status())
        if action == "usage":     # Claude plan usage, for the list page header
            return self.send_json(claude_usage.usage())
        if action == "load":      # this machine's CPU and memory, for the list page header
            return self.send_json(node_load.load())
        if action == "permissions":
            return self.send_json({"mode": REVIEWS.permissions(), "modes": review.PERMISSION_MODES})
        if action == "dirs":      # folder autocomplete for New agent
            return self.send_json(list_dirs(q.get("prefix", [""])[0]))
        if action == "state":
            page = self.page_key(q.get("page", [""])[0])
            if page is None:
                return self.send_error(404)
            # "ui": the panel scripts' version, so a tab opened before an update can reload itself
            return self.send_json(dict(REVIEWS.state(page), ui=ui_version()))
        if action == "prev":      # the page before the latest run that changed it (panel highlights)
            page = self.page_key(q.get("page", [""])[0])
            try:
                with open(REVIEWS.prev_path(page), "rb") as f:
                    body = f.read()
            except (OSError, TypeError):
                return self.send_error(404)
            self.send_html_headers(len(body))
            self.wfile.write(body)
            return
        if action in ("panel.js", "list.js", "newagent.js"):
            with open(os.path.join(WWW_DIR, "review_" + action), "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    @staticmethod
    def page_key(page):
        """'a/b' for ROOT/a/b/ holding index.html, or None if there is no such page."""
        page = page.strip("/")
        full = os.path.realpath(os.path.join(ROOT, page))
        if not (full == ROOT or full.startswith(ROOT + os.sep)) or not os.path.isdir(full):
            return None
        if os.path.isfile(os.path.join(full, "index.html")):
            return os.path.relpath(full, ROOT) if full != ROOT else ""
        return None

    # --- static files -------------------------------------------------------------------
    def send_head(self):
        path = os.path.realpath(self.translate_path(self.path))
        if path != ROOT and not path.startswith(ROOT + os.sep):
            self.send_error(404)
            return None
        if os.path.isdir(path):
            if not self.path.split("?", 1)[0].endswith("/"):
                return super().send_head()          # redirects to the trailing-slash URL
            md = os.path.join(path, "index.md")
            path = os.path.join(path, "index.html")
            if not os.path.isfile(path) and os.path.isfile(md):
                path = md
        if path.lower().endswith(".md") and os.path.isfile(path):
            return self.send_markdown(path) if self.is_owner() else self.send_error(404)
        if not path.lower().endswith(ALLOWED_EXT) or not os.path.isfile(path):
            self.send_error(404)
            return None
        if os.path.basename(path) == "index.html":
            return self.send_page(path)
        return super().send_head()

    def send_page(self, path):
        """index.html plus a Home button (every visitor) and the chat panel (owner only)."""
        with open(path, "rb") as f:
            html = f.read()
        owner = self.is_owner()
        if path == LIST_PAGE:
            if not owner:
                return io.BytesIO(html) if self.send_html_headers(len(html)) else None
            tag = '<script src="/_review/list.js"></script>' + NEWAGENT_TAG % ""
        else:
            tag = HOME_BUTTON
            if owner:
                page = os.path.relpath(os.path.dirname(path), ROOT)
                page = "" if page == "." else page.replace("&", "&amp;").replace('"', "&quot;")
                tag += '<script src="/_review/panel.js" data-page="%s"></script>' % page
                tag += NEWAGENT_TAG % page
        tag = tag.encode()
        i = html.lower().rfind(b"</body>")
        html = html[:i] + tag + html[i:] if i >= 0 else html + tag
        if path != LIST_PAGE:   # todo + job status bar at the top of the page
            page = os.path.relpath(os.path.dirname(path), ROOT)
            # "Working on" quotes the owner's chat message: owner only
            work = REVIEWS.working("" if page == "." else page) if owner else None
            status = page_status.bar(os.path.dirname(path), work).encode()
            m = re.search(rb"<body[^>]*>", html, re.I)
            j = m.end() if m else 0
            html = html[:j] + status + html[j:]
        self.send_html_headers(len(html))
        return io.BytesIO(html)

    def send_markdown(self, path):
        """A .md file rendered in the browser (MD_PAGE), plus the Home button."""
        with open(path, encoding="utf-8", errors="replace") as f:
            src = f.read()
        title = os.path.relpath(path, ROOT).replace("&", "&amp;").replace("<", "&lt;")
        src = json.dumps(src).replace("</", "<\\/")   # can't end the <script> holding it
        html = (MD_PAGE % {"title": title, "src": src}).replace("</body>", HOME_BUTTON + "</body>").encode()
        self.send_html_headers(len(html))
        return io.BytesIO(html)

    def send_html_headers(self, length):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        return True

    def list_directory(self, path):
        self.send_error(404)
        return None


class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def shutdown(signum, frame):
    """Stop the assistant runs with the server (a restart would otherwise leave them running
    on, still loading Claude or Ollama, with nobody to take their reply)."""
    REVIEWS.stop_all()
    sys.exit(0)


if __name__ == "__main__":
    os.chdir(ROOT)   # Python 3.6's handler serves the current directory
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    threading.Thread(target=housekeeping, daemon=True).start()
    threading.Thread(target=repeats, daemon=True).start()
    with ThreadingServer((BIND, PORT), HtmlOnlyHandler) as httpd:
        print("Serving .html under %s on %s:%d" % (ROOT, BIND, PORT), flush=True)
        httpd.serve_forever()
