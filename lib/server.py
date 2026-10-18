#!/usr/bin/env python3
"""Serve only the HTML files and the images they use under a directory; everything else is 404.

Usage: server.py ROOT PORT [BIND_ADDR]    (BIND_ADDR defaults to 0.0.0.0)

A folder URL serves that folder's index.html (no directory listings). Paths that
resolve outside ROOT (e.g. through symlinks) are refused.

The owner (connecting through the SSH tunnel, with the review_key cookie) also gets the agent's
panel on every index.html and the /_review/* API; see agents.py.

An index.html with no <style> of its own gets the shared index.css (/_dirai/index.css), linked
first in <head>.
"""
import html as htmllib
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
import dirai_config
import node_load
import slurm
import agents

ROOT = os.path.realpath(sys.argv[1])
PORT = int(sys.argv[2])
BIND = sys.argv[3] if len(sys.argv) > 3 else "0.0.0.0"
ALLOWED_EXT = (".html", ".htm", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")
WEB_DIR = dirai_config.WEB_DIR
UI_SCRIPTS = ("panel.js", "agent_list.js", "new_agent.js")    # /_review/<name>, from web/<name>


def ui_version():
    """Newest mtime of the scripts served under /_review/ (they are read from disk per request)."""
    return max(os.path.getmtime(os.path.join(WEB_DIR, n)) for n in UI_SCRIPTS)


def in_root(path):
    """True if the resolved path is ROOT or inside it."""
    return dirai_config.within(path, ROOT)


AGENT_LIST = os.path.join(ROOT, "www", "index.html")
AGENTS = agents.Agents(ROOT)
HOME_BUTTON = ('<a href="/www/index.html" title="All agents" style="position:fixed;left:16px;bottom:16px;'
               'z-index:99999;padding:8px 14px;border-radius:20px;border:1px solid #888;background:#1d1d1f;'
               'color:#fff;font:600 14px system-ui;text-decoration:none">&#8962; Home</a>')
KEY = agents.login_key()
NEWAGENT_TAG = ('<script src="/_review/new_agent.js" data-base="%s" data-root="'
                + htmllib.escape(ROOT) + '"></script>')
INDEX_CSS = os.path.join(WEB_DIR, "index.css")
INDEX_CSS_TAG = b'<link rel="stylesheet" href="/_dirai/index.css">'
HOUSEKEEP_S = 600     # see housekeeping()
REPEAT_CHECK_S = 60   # how often repeated messages (agents.REPEATS) are checked for being due
NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.+-]*$")   # no leading dot: no "..", no hidden folders


def clean_rel(rel):
    """Normalized 'a/b' for a folder inside ROOT a New agent may create, else None."""
    parts = [p for p in rel.strip().strip("/").split("/") if p]
    if not parts or not all(NAME_RE.match(p) for p in parts) or parts[0] == "www":
        return None
    full = os.path.realpath(os.path.join(ROOT, *parts))
    return "/".join(parts) if full != ROOT and in_root(full) else None


def list_dirs(prefix, limit=40):
    """Autocomplete: existing folders 'parent/name/' matching what has been typed."""
    parent, _, start = prefix.lstrip("/").rpartition("/")
    base = os.path.realpath(os.path.join(ROOT, parent))
    if not in_root(base):
        return []
    try:
        names = sorted(n for n in os.listdir(base) if not n.startswith(".") and n.startswith(start)
                       and os.path.isdir(os.path.join(base, n)) and (parent or n != "www"))
    except OSError:
        return []
    return [(parent + "/" if parent else "") + n + "/" for n in names[:limit]]


def agent_param(d):
    """The agent a request names: "agent" in a POST body or query string ({name: value} or
    parse_qs's {name: [values]}), or "page", what panel scripts loaded before 2026-10 send."""
    v = d.get("agent", d.get("page", ""))
    return v[0] if isinstance(v, list) else v


def rebuild_agent_list():
    subprocess.run([sys.executable, os.path.join(dirai_config.LIB_DIR, "agent_list.py"), ROOT],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def housekeeping():
    """The server's repeated work, every HOUSEKEEP_S: check the SLURM jobs agents are waiting on
    (and message those agents when done), drop week-old thread entries, then rebuild the agent list. The list is built
    once at startup by dirai_serve, so the first pass waits a full interval."""
    while True:
        time.sleep(HOUSEKEEP_S)
        for name, task in (("job check", AGENTS.check_job_waits), ("thread prune", AGENTS.prune_threads),
                           ("list rebuild", rebuild_agent_list)):
            try:
                task()
            except Exception as e:      # one failing task mustn't stop the loop
                print("housekeeping: %s failed: %s" % (name, e), flush=True)


def repeats():
    """Send the agents' repeated messages as they come due (every hour/day/week)."""
    while True:
        time.sleep(REPEAT_CHECK_S)
        try:
            AGENTS.check_repeats()
        except Exception as e:
            print("repeat check failed: %s" % e, flush=True)


class HtmlOnlyHandler(http.server.SimpleHTTPRequestHandler):
    # --- owner check --------------------------------------------------------------------
    def is_owner(self):
        if self.client_address[0] != "127.0.0.1":
            return False
        c = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        return "review_key" in c and c["review_key"].value == KEY

    def send_body(self, body, ctype, cache="no-store", code=200):
        self.send_headers(len(body), ctype, cache, code)
        self.wfile.write(body)

    def send_headers(self, length, ctype, cache="no-store", code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", cache)
        self.end_headers()

    def send_file(self, path, ctype, cache="no-store"):
        with open(path, "rb") as f:
            self.send_body(f.read(), ctype, cache)

    def send_json(self, obj, code=200):
        self.send_body(json.dumps(obj).encode(), "application/json", code=code)

    # --- /_review/* ---------------------------------------------------------------------
    def do_GET(self):
        url = urlparse(self.path)
        if url.path.startswith("/_review/"):
            return self.api_get(url)
        if url.path == "/_dirai/index.css":    # every visitor: it styles every index.html
            return self.send_file(INDEX_CSS, "text/css; charset=utf-8", "no-cache")
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
        if action == "new":       # New agent: make the folder + starter index.html, start the task
            rel, task = clean_rel(body.get("dir", "")), (body.get("task") or "").strip()
            if rel is None:
                return self.send_json({"error": "Folder must be a relative path inside the tree "
                                                "(letters, digits, _ . + -; no '..', hidden or www/ folders)."})
            if not task:
                return self.send_json({"error": "Describe the task."})
            if not AGENTS.new_agent(rel, task, body.get("every") or "off"):
                return self.send_json({"error": "The agent in %s/ is already working." % rel})
            threading.Thread(target=rebuild_agent_list, daemon=True).start()
            return self.send_json({"ok": True, "url": "/%s/" % rel})
        if action == "usage_stop":    # agent list slider or Auto: pause new runs at this % (all trees)
            ok = (claude_usage.set_weekly_auto(body["auto"]) if isinstance(body.get("auto"), bool)
                  else claude_usage.set_pause_level(body.get("name"), body.get("percent")))
            if not ok:
                return self.send_json({"error": "bad level"})
            AGENTS.recheck_hold()
            return self.send_json({"ok": True, "stop": claude_usage.pause_levels()})
        if action == "permissions":   # tree-wide, from the agent list: "allowlist" or "ask"
            ok = AGENTS.set_permissions(body.get("mode"))
            return self.send_json({"ok": True} if ok else {"error": "unknown mode"})
        agent = self.agent_key(agent_param(body))
        if agent is None:
            return self.send_json({"error": "no such agent"}, 404)
        if action == "comment":
            text = (body.get("text") or "").strip()
            sel = body.get("selection")
            sel = ({"text": str(sel.get("text") or "").strip(), "heading": str(sel.get("heading") or "")}
                   if isinstance(sel, dict) else None)
            ok = bool(text) and AGENTS.comment(agent, text, selection=sel if sel and sel["text"] else None)
        elif action == "status" and body.get("status") in ("read", "unread", "closed"):
            ok = AGENTS.set_status(agent, body["status"])
        elif action == "model":
            ok = AGENTS.set_model(agent, body.get("model"))
        elif action == "repeat":
            ok = AGENTS.set_repeat(agent, body.get("every"), body.get("text"))
            if not ok:
                return self.send_json({"error": "Pick hourly, daily or weekly and give the message to repeat."})
        elif action == "compact":
            ok = AGENTS.compact(agent)
        elif action == "newchat":
            ok = AGENTS.new_chat(agent)
        elif action == "cancel":
            ok = AGENTS.cancel(agent)
        elif action == "grant":
            ok = AGENTS.grant(agent, list(body.get("rules", [])), bool(body.get("always")))
        elif action == "answer":      # Allow / Always allow / Deny on a waiting permission prompt
            if AGENTS.answer(agent, str(body.get("id", "")), body.get("choice")):
                return self.send_json({"ok": True})
            return self.send_json({"error": "That request is no longer waiting (the run ended or it was answered)."})
        else:
            return self.send_error(404)
        self.send_json({"ok": True} if ok else {"error": "The agent is still working, or there is nothing to do."})

    def api_get(self, url):
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
            return self.send_json(AGENTS.all_status())
        if action == "usage":     # Claude plan usage, for the agent list header
            return self.send_json(claude_usage.usage())
        if action == "load":      # this machine's CPU and memory, for the agent list header
            return self.send_json(node_load.load())
        if action == "permissions":
            return self.send_json({"mode": AGENTS.permissions(), "modes": agents.PERMISSION_MODES})
        if action == "dirs":      # folder autocomplete for New agent
            return self.send_json(list_dirs(q.get("prefix", [""])[0]))
        if action == "state":
            agent = self.agent_key(agent_param(q))
            if agent is None:
                return self.send_error(404)
            # "ui": the panel scripts' version, so a tab opened before an update can reload itself
            return self.send_json(dict(AGENTS.state(agent), ui=ui_version()))
        if action == "prev":      # index.html before the latest run that changed it (panel highlights)
            agent = self.agent_key(agent_param(q))
            try:
                with open(AGENTS.before_run_path(agent), "rb") as f:
                    body = f.read()
            except (OSError, TypeError):
                return self.send_error(404)
            return self.send_body(body, "text/html; charset=utf-8")
        if action in UI_SCRIPTS:
            return self.send_file(os.path.join(WEB_DIR, action), "application/javascript")
        self.send_error(404)

    @staticmethod
    def agent_key(agent):
        """'a/b' for ROOT/a/b/ holding index.html, or None if there is no such agent."""
        agent = agent.strip("/")
        full = os.path.realpath(os.path.join(ROOT, agent))
        if not in_root(full) or not os.path.isdir(full):
            return None
        if os.path.isfile(os.path.join(full, "index.html")):
            return os.path.relpath(full, ROOT) if full != ROOT else ""
        return None

    # --- static files -------------------------------------------------------------------
    def send_head(self):
        path = os.path.realpath(self.translate_path(self.path))
        if not in_root(path):
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
            return self.send_index(path)
        return super().send_head()

    def send_index(self, path):
        """index.html plus a Home button (every visitor) and the chat panel (owner only)."""
        with open(path, "rb") as f:
            html = f.read()
        owner = self.is_owner()
        agent = os.path.relpath(os.path.dirname(path), ROOT)
        agent = "" if agent == "." else agent
        if path == AGENT_LIST:
            if not owner:
                self.send_html_headers(len(html))
                return io.BytesIO(html)
            tag = '<script src="/_review/agent_list.js"></script>' + NEWAGENT_TAG % ""
        else:
            tag = HOME_BUTTON
            if owner:
                attr = htmllib.escape(agent)
                tag += '<script src="/_review/panel.js" data-agent="%s"></script>' % attr
                tag += NEWAGENT_TAG % attr
        tag = tag.encode()
        i = html.lower().rfind(b"</body>")
        html = html[:i] + tag + html[i:] if i >= 0 else html + tag
        if path != AGENT_LIST and not re.search(rb"<style[\s>]", html, re.I):   # shared style, first in <head>
            m = re.search(rb"<head(?:\s[^>]*)?>", html, re.I)
            j = m.end() if m else 0
            html = html[:j] + INDEX_CSS_TAG + html[j:]
        if path != AGENT_LIST:   # work + job status bar at the top of index.html
            # "Working on" quotes the owner's chat message: owner only
            work = AGENTS.working(agent) if owner else None
            status = slurm.status_bar(os.path.dirname(path), work).encode()
            m = re.search(rb"<body[^>]*>", html, re.I)
            j = m.end() if m else 0
            html = html[:j] + status + html[j:]
        self.send_html_headers(len(html))
        return io.BytesIO(html)

    def send_html_headers(self, length):
        self.send_headers(length, "text/html; charset=utf-8")

    def list_directory(self, path):
        self.send_error(404)
        return None


class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def shutdown(signum, frame):
    """Stop the agents' runs with the server (a restart would otherwise leave them running
    on, still loading Claude or Ollama, with nobody to take their reply)."""
    AGENTS.stop_all()
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
