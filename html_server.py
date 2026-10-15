#!/usr/bin/env python3
"""Serve only HTML pages and the images they use under a directory; everything else is 404.

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
LIST_PAGE = os.path.join(ROOT, "www", "index.html")
REVIEWS = review.Reviews(ROOT)
HOME_BUTTON = ('<a href="/www/index.html" title="All pages" style="position:fixed;left:16px;bottom:16px;'
               'z-index:99999;padding:8px 14px;border-radius:20px;border:1px solid #888;background:#1d1d1f;'
               'color:#fff;font:600 14px system-ui;text-decoration:none">&#8962; Home</a>')
KEY = review.login_key()
NEWAGENT_TAG = ('<script src="/_review/newagent.js" data-base="%s" data-root="'
                + ROOT.replace("&", "&amp;").replace('"', "&quot;") + '"></script>')
HOUSEKEEP_S = 600     # see housekeeping()
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
    (and message their assistants when done), then rebuild the list page. The list is built
    once at startup by dirai_serve, so the first pass waits a full interval."""
    while True:
        time.sleep(HOUSEKEEP_S)
        for name, task in (("job check", REVIEWS.check_watches), ("list rebuild", rebuild_list)):
            try:
                task()
            except Exception as e:      # one failing task mustn't stop the loop
                print("housekeeping: %s failed: %s" % (name, e), flush=True)


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
            if not REVIEWS.new_page(rel, task):
                return self.send_json({"error": "The assistant is already working on %s/." % rel})
            threading.Thread(target=rebuild_list, daemon=True).start()
            return self.send_json({"ok": True, "url": "/%s/" % rel})
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
        elif action == "compact":
            ok = REVIEWS.compact(page)
        elif action == "newchat":
            ok = REVIEWS.new_chat(page)
        elif action == "cancel":
            ok = REVIEWS.cancel(page)
        elif action == "grant":
            ok = REVIEWS.grant(page, list(body.get("rules", [])), bool(body.get("always")))
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
        if action == "dirs":      # folder autocomplete for New agent
            return self.send_json(list_dirs(q.get("prefix", [""])[0]))
        if action == "state":
            page = self.page_key(q.get("page", [""])[0])
            return self.send_json(REVIEWS.state(page)) if page is not None else self.send_error(404)
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
            path = os.path.join(path, "index.html")
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
    with ThreadingServer((BIND, PORT), HtmlOnlyHandler) as httpd:
        print("Serving .html under %s on %s:%d" % (ROOT, BIND, PORT), flush=True)
        httpd.serve_forever()
