#!/usr/bin/env python3
"""Serve only the HTML files and the images they use under a directory; everything else is 404.

Usage: server.py ROOT PORT [BIND_ADDR]    (BIND_ADDR defaults to 0.0.0.0)

A folder URL serves that folder's index.html (no directory listings). Paths that
resolve outside ROOT (e.g. through symlinks) are refused.

The owner (connecting through the SSH tunnel, with the owner cookie, see COOKIE) also gets the agent's
panel on every index.html and the /_review/* API; see agents.py.

An index.html with no <style> of its own gets the shared index.css (/_dirai/index.css), linked
first in <head>.
"""
import hashlib
import html as htmllib
import http.server
import io
import json
import os
import re
import shutil
import signal
import socketserver
import subprocess
import sys
import threading
import time
import zipfile
from http import cookies
from urllib.parse import parse_qs, quote, urlparse

import attachments
import claude_usage
import codex_engine
import dirai_config
import node_load
import notes
import slurm
import agent_files
import agents
import colleague_search
import colleagues
import remotes
import self_update
import shares
import svg_inline

ROOT = os.path.realpath(sys.argv[1])
PORT = int(sys.argv[2])
BIND = sys.argv[3] if len(sys.argv) > 3 else "0.0.0.0"
ALLOWED_EXT = (".html", ".htm", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")
MAX_BODY = 32 << 20     # bytes per POST: one dropped file (attachments.FILE_MAX) in base64, with room
WEB_DIR = dirai_config.WEB_DIR
TAB_ALERT_TAG = '<script src="/_review/tab_alert.js"></script>'   # agent pages only, before panel.js
UI_SCRIPTS = ("panel.js", "agent_list.js", "agent_tree.js", "new_agent.js", "files.js", "tab_alert.js",
              "share.js")    # /_review/<name>, from web/<name>


def ui_version():
    """Newest mtime of the scripts served under /_review/ (they are read from disk per request)."""
    return max(os.path.getmtime(os.path.join(WEB_DIR, n)) for n in UI_SCRIPTS)


def in_root(path):
    """True if the resolved path is ROOT or inside it."""
    return dirai_config.within(path, ROOT)


AGENT_LIST = os.path.join(ROOT, "www", "index.html")
FAVORITES = os.path.join(ROOT, "www", "favorites.json")   # the agent list's starred agents: ["a/b", ...]
FAVORITES_LOCK = threading.Lock()
AGENTS = agents.Agents(ROOT)
HOME_BUTTON = ('<a href="/www/index.html" title="All agents" style="position:fixed;left:16px;bottom:16px;'
               'z-index:99999;padding:8px 14px;border-radius:20px;border:1px solid #888;background:#1d1d1f;'
               'color:#fff;font:600 14px system-ui;text-decoration:none">&#8962; Home</a>')
HOME_STYLE = ('position:fixed;left:16px;bottom:%dpx;z-index:99999;padding:%s;border-radius:20px;border:1px solid #888;'
              'background:#1d1d1f;color:#fff;font:600 %dpx system-ui;text-decoration:none')
HOST_RE = re.compile(r"[A-Za-z0-9.\-]{1,255}|\[[0-9A-Fa-f:]{2,45}\]")   # a Host header's name, without the port


def home_buttons(headers, here_list=False):
    """The Home button. Through a forwarder (X-DirAI-Home: the top server's port and machine name, see
    remotes.Forwarder) it leads to that server's list, else to this server's list (none on the list itself)."""
    top = remotes.parse_home(headers.get(remotes.HOME.decode()))
    host = re.sub(r":\d+$", "", headers.get("Host") or "")
    if not top or not HOST_RE.fullmatch(host or ""):
        return "" if here_list else HOME_BUTTON
    return '<a href="http://%s:%d/www/index.html" title="The list you came from (%s)" style="%s">&#8962; Home</a>' % (
        host, top[0], htmllib.escape(top[1]), HOME_STYLE % (16, "8px 14px", 14))


KEY = agents.login_key()
# The owner cookie's name carries a fingerprint of this machine's key: browsers keep cookies per host
# name, not per port, so trees on two machines tunnelled to 127.0.0.1 would otherwise overwrite each
# other's login. "review_key", its name before 2026-10, is still accepted.
COOKIE = "review_key_" + hashlib.sha256(KEY.encode()).hexdigest()[:10]
REMOTES = remotes.Remotes(ROOT, KEY, (COOKIE, "review_key"))    # downstream machines (www/machines.json)
REMOTES.port = PORT
SHARES = shares.Shares(ROOT)    # agents shared with other people, and theirs with you (www/shares/)
SHARED = "www/shares/"          # a page under here is someone else's shared agent: read-only, no chat
NEWAGENT_TAG = ('<script src="/_review/new_agent.js" data-base="%s" data-root="'
                + htmllib.escape(ROOT) + '"></script>')
INDEX_CSS = os.path.join(WEB_DIR, "index.css")
INDEX_CSS_TAG = b'<link rel="stylesheet" href="/_dirai/index.css">'
SVG_WATCH = os.path.join(WEB_DIR, "svg_watch.js")   # every visitor: figures a page's script adds, inlined too
SVG_WATCH_TAG = '<script src="/_dirai/svg_watch.js"></script>'
HOUSEKEEP_S = 600     # see housekeeping()
REPEAT_CHECK_S = 60   # how often scheduled messages (agents.check_schedules) are checked for being due
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


HOUSEKEEP_LOCK = threading.Lock()   # the timer's pass and the agent list's Refresh button don't overlap


def housekeep_once():
    """Check the SLURM jobs agents are waiting on (and message those agents when done), drop
    week-old thread entries, then rebuild the agent list."""
    with HOUSEKEEP_LOCK:
        for name, task in (("job check", AGENTS.check_job_waits), ("thread prune", AGENTS.prune_threads),
                           ("engine check", AGENTS.check_engine), ("list rebuild", rebuild_agent_list),
                           # gh and git over the network: on their own thread, not holding up the others
                           ("share fetch", lambda: threading.Thread(target=SHARES.fetch_all, daemon=True).start())):
            try:
                task()
            except Exception as e:      # one failing task mustn't stop the others
                print("housekeeping: %s failed: %s" % (name, e), flush=True)


def housekeeping():
    """The server's repeated work: housekeep_once() every HOUSEKEEP_S. The list is built once at
    startup by dirai_serve, so the first pass waits a full interval."""
    while True:
        time.sleep(HOUSEKEEP_S)
        housekeep_once()


def repeats():
    """Send the agents' scheduled messages (agents.check_schedules) as they come due."""
    while True:
        time.sleep(REPEAT_CHECK_S)
        try:
            AGENTS.check_schedules()
        except Exception as e:
            print("schedule check failed: %s" % e, flush=True)


class HtmlOnlyHandler(http.server.SimpleHTTPRequestHandler):
    # --- owner check --------------------------------------------------------------------
    def is_owner(self):
        if self.client_address[0] != "127.0.0.1":
            return False
        c = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        return any(name in c and c[name].value == KEY for name in (COOKIE, "review_key"))

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

    def attachment_headers(self, name, length=None):
        """Headers that make the browser save the body as name; length None: streamed to the end of
        the connection (a .zip made as it is sent)."""
        self.send_response(200)
        self.send_header("Content-Type", "application/zip" if length is None else "application/octet-stream")
        if length is None:
            self.send_header("Connection", "close")
            self.close_connection = True
        else:
            self.send_header("Content-Length", str(length))
        plain = re.sub(r"[^A-Za-z0-9._+-]", "_", name)
        self.send_header("Content-Disposition", "attachment; filename=\"%s\"; filename*=UTF-8''%s" % (plain, quote(name)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def send_download(self, path):
        """The file at path as an attachment, streamed in 1 MB chunks, any size."""
        try:
            f = open(path, "rb")
        except OSError:
            return self.send_error(404)
        with f:
            self.attachment_headers(os.path.basename(path), os.fstat(f.fileno()).st_size)
            try:
                shutil.copyfileobj(f, self.wfile, 1 << 20)
            except (BrokenPipeError, ConnectionResetError):
                pass                # the browser cancelled

    def send_zip(self, agent, sub):
        """The folder sub of the agent's folder (agent_files.zip_members) as a .zip, written to the
        socket as it is made (zipfile handles an unseekable stream; zip64 for big files), any size."""
        members = agent_files.zip_members(os.path.join(ROOT, agent), sub)
        if members is None:
            return self.send_error(404)
        self.attachment_headers((sub.rsplit("/", 1)[-1] if sub else os.path.basename(agent) or "tree") + ".zip")
        try:
            with zipfile.ZipFile(self.wfile, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:   # (no compresslevel: Python 3.6)
                for path, arc in members:
                    if os.access(path, os.R_OK):
                        z.write(path, arc)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_json(self, obj, code=200):
        self.send_body(json.dumps(obj).encode(), "application/json", code=code)

    # --- /_review/* ---------------------------------------------------------------------
    def do_GET(self):
        url = urlparse(self.path)
        if url.path.startswith("/_review/"):
            return self.api_get(url)
        if url.path == "/_dirai/index.css":    # every visitor: it styles every index.html
            return self.send_file(INDEX_CSS, "text/css; charset=utf-8", "no-cache")
        if url.path == "/_dirai/svg_watch.js":
            return self.send_file(SVG_WATCH, "application/javascript", "no-cache")
        if url.path == "/_dirai/svg":            # every visitor, like the .svg file itself: see send_svg()
            return self.send_svg(parse_qs(url.query))
        return super().do_GET()

    def send_svg(self, q):
        """?path=/a/b/x.svg&n=3: the <svg> the server would inline for that file, for an <img> a page's own
        script added after the page arrived (web/svg_watch.js); 404 if it stays a picture."""
        rel, n = q.get("path", [""])[0].lstrip("/"), q.get("n", ["0"])[0]
        path = os.path.realpath(os.path.join(ROOT, rel))
        if not n.isdigit() or not in_root(path):
            return self.send_error(404)
        folder, name = os.path.split(path)
        svg = svg_inline.inline_one(name, folder, ROOT, "js%s-" % n)
        if svg is None:
            return self.send_error(404)
        self.send_body(svg.encode("utf-8", "surrogateescape"), "image/svg+xml; charset=utf-8", "no-cache")

    def do_POST(self):
        url = urlparse(self.path)
        if not url.path.startswith("/_review/") or not self.is_owner() or self.headers.get("X-Review") != "1":
            return self.send_error(404)
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > MAX_BODY:
                return self.send_json({"error": "Too big: at most %d MB per request." % (MAX_BODY >> 20)}, 413)
            body = json.loads(self.rfile.read(length) or b"{}")
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
            name = str(body.get("name") or "")
            codex = name[:1] == "w" and name[1:].isdigit()     # a Codex window ("w<minutes>"), not "weekly"
            ok = (claude_usage.set_weekly_auto(body["auto"]) if isinstance(body.get("auto"), bool)
                  else codex_engine.set_pause_level(body.get("name"), body.get("percent")) if codex
                  else claude_usage.set_pause_level(body.get("name"), body.get("percent")))
            if not ok:
                return self.send_json({"error": "bad level"})
            AGENTS.recheck_hold()
            return self.send_json({"ok": True, "stop": codex_engine.usage()["stop"] if codex
                                   else claude_usage.pause_levels()})
        if action == "engine":        # the title of the machine's usage widget: Claude Code or Codex (all trees here)
            why = AGENTS.set_engine(body.get("engine"))
            if why:
                return self.send_json({"error": why})
            return self.send_json({"ok": True, "engine": AGENTS.engine()})
        if action == "refresh":       # agent list's Refresh: the housekeeping pass, now
            housekeep_once()
            return self.send_json({"ok": True})
        if action == "remotes":       # the agent list's Machines section: connect, start, hide/show
            return self.send_json(REMOTES.act(body))
        if action == "pull":          # this server's DirAI checkout: git pull --ff-only, then restart when no run goes
            out = self_update.pull()
            if out.get("ok"):
                self_update.restart_when_idle(lambda: AGENTS.running, lambda: REMOTES.act({"op": "restart"}))
            return self.send_json(out)
        if action == "pull_check":    # fetch now, for the "behind" line
            return self.send_json(self_update.status(refresh=True))
        if action == "permissions":   # tree-wide, from the agent list: "allowlist" or "ask"
            ok = AGENTS.set_permissions(body.get("mode"))
            if not ok:
                return self.send_json({"error": "unknown mode"})
            # the owner's click on this (top) server: the same mode on every tree of the Machines map; a call
            # relayed from an upstream server (no "all") sets this tree only
            errors = REMOTES.push_permissions(body["mode"]) if body.get("all") else {}
            return self.send_json({"ok": True, "errors": errors})
        if action == "share":         # the Share pill, and shared repos in the Machines map (shares.py)
            page = self.agent_key(agent_param(body)) if "agent" in body else None
            if page is not None and page.startswith(SHARED):     # someone else's agent: only Copy to my tree
                if body.get("op") != "copy":
                    return self.send_json({"error": "a shared agent is read-only"})
                dest = clean_rel(str(body.get("dest") or ""))
                if dest is None:
                    return self.send_json({"error": "Give a new folder inside your tree, e.g. copies/fit"})
                why = SHARES.copy(page, dest)
                if not why:
                    threading.Thread(target=rebuild_agent_list, daemon=True).start()
                return self.send_json({"error": why} if why else {"ok": True, "url": "/%s/" % dest})
            if body.get("op") == "remove_copy":     # a copy inside copies/ (Copy to my tree) leaves the tree
                if page is None or not SHARES.removable(page):
                    return self.send_json({"error": "only an agent inside copies/ made by Copy to my tree can be removed"})
                running, _ = AGENTS.removal_check(page)
                if running:
                    return self.send_json({"error": "a run is going in this agent: stop it first"})
                why = SHARES.remove_copy(page)
                if not why:
                    AGENTS.drop(page)
                    threading.Thread(target=rebuild_agent_list, daemon=True).start()
                return self.send_json({"error": why} if why else {"ok": True, "url": "/%s/index.html" % dirai_config.DATA})
            return self.send_json(SHARES.act(body, page))
        agent = self.agent_key(agent_param(body))
        # no chat, schedule or grants on someone else's agent (a star in the agent list is fine)
        if agent is None or (agent.startswith(SHARED) and action != "favorite"):
            return self.send_json({"error": "no such agent"}, 404)
        if action == "favorite":      # the agent list's star: add or remove this agent
            with FAVORITES_LOCK:
                favs = [f for f in dirai_config.load_json(FAVORITES, []) if f != agent]
                if body.get("on"):
                    favs.append(agent)
                dirai_config.save_json(FAVORITES, favs)
            return self.send_json({"ok": True, "favorites": favs})
        if action == "notes":         # sticky notes on the page (notes.py): add / edit / delete / state
            got, why = notes.act(os.path.join(ROOT, agent), body)
            return self.send_json({"error": why, "notes": got} if why else {"ok": True, "notes": got})
        if action == "request":       # requests between agents (proposal 77): the owner's Send / Reject / Deliver now
            op, ids = body.get("op"), [str(i) for i in body.get("ids") or [] if isinstance(i, str)][:notes.MAX_NOTES]
            if op == "send" and ids:
                sent, errors = AGENTS.send_request(agent, ids, together=bool(body.get("all")))
                why = "; ".join(errors)
            elif op == "reject":
                why = None if AGENTS.reject_request(agent, str(body.get("id") or ""), str(body.get("reason") or "")) \
                    else "That request is gone or already sent."
            elif op == "deliver":
                why = None if AGENTS.deliver_now(agent, str(body.get("group") or "")) else "No answers are in yet."
            else:
                return self.send_json({"error": "bad request"})
            got = notes.load(os.path.join(ROOT, agent))
            return self.send_json({"error": why, "notes": got} if why else {"ok": True, "notes": got})
        if action == "attach":        # a file dropped on the panel: saved in the agent's pasted/, named in the message
            try:
                path = attachments.save(os.path.join(ROOT, agent), body.get("name"), body.get("data"))
            except ValueError as e:
                return self.send_json({"error": str(e)})
            except OSError as e:
                return self.send_json({"error": "Not saved: %s" % e.strerror})
            return self.send_json({"ok": True, "path": path})
        if action in ("comment", "schedule"):
            text = (body.get("text") or "").strip()
            sel = body.get("selection")
            if isinstance(sel, dict):   # in index.html, or in a file of its folder ("file", "lines": files.js)
                sel = dict({"text": str(sel.get("text") or "").strip(), "heading": str(sel.get("heading") or "")},
                           **({"file": sel["file"], "lines": sel.get("lines"), "rendered": bool(sel.get("rendered")),
                               "svg": bool(sel.get("svg"))}
                              if sel.get("file") else {}))
            sel = sel if sel and sel["text"] else None
            if action == "comment":     # while the agent is busy it waits in the agent's inbox
                # sticky notes (notes.py) going with it, by id: the text may then be empty
                ids = [str(i) for i in body.get("notes") or [] if isinstance(i, str)][:notes.MAX_NOTES]
                ok = bool(text or ids) and AGENTS.comment(agent, text, selection=sel, queue=True, notes=ids or None)
                if ok == "queued":
                    return self.send_json({"ok": True, "queued": True})
                if not ok and ids and not text:
                    return self.send_json({"error": "Not sent: those notes are gone or done, or %d messages are "
                                                    "already waiting for this agent." % agents.INBOX_MAX})
                if not ok and text:
                    return self.send_json({"error": "Not sent: %d messages are already waiting for this agent, "
                                                    "or the selected file isn't one of its files." % agents.INBOX_MAX})
            else:                        # the panel's Schedule…: add or edit one, or op on one
                op = body.get("op")
                if op == "preview":      # the editor's "Next:" line, in the server's time zone
                    why, runs = agents.preview_schedule(body)
                    return self.send_json({"error": why} if why else {"next": runs})
                if op in ("delete", "pause", "resume"):
                    ok = AGENTS.change_schedule(agent, str(body.get("id") or ""), op)
                    return self.send_json({"ok": True} if ok else {"error": "That schedule is gone (sent or deleted)."})
                why = AGENTS.set_schedule(agent, body, selection=sel)
                return self.send_json({"error": why} if why else {"ok": True})
        elif action == "status" and body.get("status") in ("read", "unread", "closed"):
            ok = AGENTS.set_status(agent, body["status"])
        elif action == "model":
            ok = AGENTS.set_model(agent, body.get("model"))
        elif action == "compact":
            ok = AGENTS.compact(agent)
        elif action == "autocompact":
            ok = AGENTS.set_auto_compact(agent, body.get("limit"))
        elif action == "newchat":
            ok = AGENTS.new_chat(agent)
        elif action == "cancel":
            ok = AGENTS.cancel(agent)
        elif action == "inbox":         # the messages waiting for a busy agent: send now, edit or remove one
            if body.get("op") == "send":
                ok = AGENTS.send_inbox(agent)
            elif body.get("op") in ("edit", "remove"):
                text = str(body.get("text") or "").strip() if body["op"] == "edit" else ""
                if not AGENTS.change_inbox(agent, str(body.get("id") or ""), text):
                    return self.send_json({"error": "That message was already sent."})
                ok = True
            else:
                ok = False
        elif action == "undo":        # Undo / Redo one block of the latest run's changes to index.html
            why = AGENTS.undo(agent, int(body.get("block", -1)))
            return self.send_json({"error": why} if why else {"ok": True})
        elif action == "colleague":   # add one by its pasted link, remove one, or set its mode (read/own/all)
            if body.get("remove") is not None:
                ok = AGENTS.remove_colleague(agent, str(body["remove"]))
            elif body.get("mode") is not None:
                why = AGENTS.set_colleague_mode(agent, str(body["mode"]), str(body.get("value") or ""))
                return self.send_json({"error": why} if why else {"ok": True})
            else:
                why = AGENTS.add_colleague(agent, str(body.get("add") or ""))
                return self.send_json({"error": why} if why else {"ok": True})
        elif action == "grant":
            ok = AGENTS.grant(agent, list(body.get("rules", [])), bool(body.get("always")))
        elif action == "ungrant":     # the × after a rule in the card's Permissions list
            if not AGENTS.remove_grant(agent, [str(r) for r in body.get("rules", [])]):
                return self.send_json({"error": "No such permission (already removed?)."})
            ok = True
        elif action == "dismiss":     # clear the refused actions without granting them
            ok = AGENTS.dismiss_denials(agent)
        elif action == "answer":      # Allow / Always allow / Deny on a waiting permission prompt
            if AGENTS.answer(agent, str(body.get("id", "")), body.get("choice")):
                return self.send_json({"ok": True})
            return self.send_json({"error": "That request is no longer waiting (the run ended or it was answered)."})
        elif action == "claude_login":   # the panel's login box while Claude runs wait for an expired login
            op = body.get("op")
            if op == "start":       # `claude auth login` on this server: its sign-in link comes back in state
                return self.send_json(dict(AGENTS.start_login(), ok=True))
            if op == "code":        # the code the sign-in page showed
                if not AGENTS.login_code(str(body.get("code") or "")):
                    return self.send_json({"error": "Paste the whole code the sign-in page shows (it has a # in it), "
                                                    "or press Log in again."})
                return self.send_json({"ok": True})
            if op == "cancel":
                ok = AGENTS.cancel_login()
            elif op == "retry":     # logged in in a terminal: send the held messages now
                AGENTS.retry_login()
                ok = True
            else:
                ok = False
        else:
            return self.send_error(404)
        self.send_json({"ok": True} if ok else {"error": "The agent is still working, or there is nothing to do."})

    def api_get(self, url):
        q = parse_qs(url.query)
        action = url.path[len("/_review/"):]
        if action == "login" and self.client_address[0] == "127.0.0.1" and q.get("key", [""])[0] == KEY:
            self.send_response(302)
            self.send_header("Set-Cookie", "%s=%s; Path=/; Max-Age=31536000; HttpOnly; SameSite=Strict" % (COOKIE, KEY))
            self.send_header("Location", "/www/index.html")
            self.end_headers()
            return
        if not self.is_owner():
            return self.send_error(404)
        if action == "all":
            return self.send_json(AGENTS.all_status())
        if action == "usage":     # Claude plan usage, for the agent list header, with the machine's engine and Codex usage
            return self.send_json(codex_engine.annotate(claude_usage.usage()))
        if action == "usage_history":     # samples for the usage charts
            return self.send_json({"samples": claude_usage.history()})
        if action == "load":      # this machine's CPU and memory, for the agent list header
            return self.send_json(node_load.load())
        if action == "shares":    # repos shared with you, connected here: for the server upstream (remotes.poll_tree)
            return self.send_json(SHARES.report())
        if action == "permissions":
            return self.send_json({"mode": AGENTS.permissions(), "modes": agents.PERMISSION_MODES})
        if action == "remotes":   # downstream machines and their trees (the Machines section; servers upstream)
            via = [v for v in self.headers.get(remotes.VIA, "").split(",") if v]
            rep = REMOTES.report(via)
            if not via:     # the browser's own server only: Pull is never offered for a machine below
                rep["self_update"] = self_update.status()
                rep["shares"] = SHARES.report()      # repos shared with you: the GitHub row and git boxes
            return self.send_json(rep)
        if action == "share":     # the Share pill: your agent's popover, or a shared page's origin
            agent = self.agent_key(agent_param(q))
            if agent is None:
                return self.send_error(404)
            if agent.startswith(SHARED):
                return self.send_json({"shared": SHARES.shared_page(agent)})
            if q.get("quick"):    # the pill's look only: no gh or ssh calls unless cached
                return self.send_json({"origin": SHARES.origin(agent), "ready": SHARES.cached_ready(),
                                       "shared": sorted(SHARES.state()["targets"].get(agent, {}))})
            info = SHARES.copy_info(agent)
            if info:
                info["running"], info["used_by"] = AGENTS.removal_check(agent)
            return self.send_json(dict(SHARES.page_state(agent), origin=SHARES.origin(agent), copy=info))
        if action == "favorites":     # starred agents, for the agent list's Favorites tab
            return self.send_json(dirai_config.load_json(FAVORITES, []))
        if action == "card":      # an agent's summary card, for the hover in the agent list's Tree tab
            agent = self.agent_key(agent_param(q))
            if agent is None:
                return self.send_error(404)
            return self.send_json(AGENTS.card_fields(agent))
        if action == "files":     # the agent's folder, shown at the end of its index.html (files.js)
            agent = self.agent_key(agent_param(q))
            if agent is None:
                return self.send_error(404)
            files = agent_files.folder_files(os.path.join(ROOT, agent), q.get("sub", [""])[0])
            return self.send_json(files) if files is not None else self.send_error(404)
        if action in ("download", "zip"):    # ⤓ in the Files section: one file, or a folder as .zip
            agent = self.agent_key(agent_param(q))
            if agent is None:
                return self.send_error(404)
            if action == "download":
                path = agent_files.file_path(os.path.join(ROOT, agent), q.get("name", [""])[0], any_type=True)
                return self.send_download(path) if path else self.send_error(404)
            return self.send_zip(agent, q.get("sub", [""])[0])
        if action == "ls":        # a folder of the tree by name, for the agent list's Tree tab in Show files mode
            listing = agent_files.dir_listing(ROOT, q.get("path", [""])[0])
            return self.send_json(listing) if listing is not None else self.send_error(404)
        if action == "colleague_search":   # the Colleagues box: agents of this tree matching a keyword
            agent = self.agent_key(agent_param(q))
            if agent is None:
                return self.send_error(404)
            have = set(AGENTS.colleagues(agent))
            found = colleague_search.search(colleague_search.load_index(ROOT), q.get("q", [""])[0], exclude=agent)
            return self.send_json({"results": [dict(r, added=r["path"] in have) for r in found]})
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
            # its diagrams inlined as send_index() does, drawn as they were before that run (agents.py)
            snap = AGENTS.before_run_path(agent) + ".svg"
            body = svg_inline.expand(body.decode("utf-8", "surrogateescape"), os.path.join(ROOT, agent), ROOT,
                                     snapshot=snap if os.path.isdir(snap) else None).encode("utf-8", "surrogateescape")
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
        """index.html plus a Home button and the Colleagues row in its card (every visitor), and the
        chat panel (owner only)."""
        with open(path, "rb") as f:
            html = f.read()
        owner = self.is_owner()
        agent = os.path.relpath(os.path.dirname(path), ROOT)
        agent = "" if agent == "." else agent
        shared = (agent + "/").startswith(SHARED)     # someone else's agent (www/shares/): no chat, no Undo
        if owner and path != AGENT_LIST and not shared:   # where the latest run's changed blocks start: their Undo buttons
            html = AGENTS.page_marks(agent, html)
        if path == AGENT_LIST:
            if not owner:
                self.send_html_headers(len(html))
                return io.BytesIO(html)
            tag = (home_buttons(self.headers, True) + '<script src="/_review/agent_list.js"></script>'
                   '<script src="/_review/agent_tree.js"></script>' + NEWAGENT_TAG % "")
        else:
            tag = home_buttons(self.headers) + SVG_WATCH_TAG
            where ="%s: %s" % (remotes.machine_name(), ROOT.replace(os.path.expanduser("~"), "~", 1) + ("/" + agent if agent else ""))
            tag += ('<div title="The server this page is on" style="position:fixed;right:12px;bottom:16px;z-index:99998;'
                    'padding:2px 8px;border-radius:10px;background:#1d1d1fcc;color:#ddd;font:12px system-ui;'
                    'pointer-events:none">%s</div>' % htmllib.escape(where))
            if owner and shared:     # only the "From … · read-only" pill (share.js)
                tag += '<script src="/_review/share.js" data-agent="%s" data-shared="1"></script>' % htmllib.escape(agent)
            elif owner:
                attr = htmllib.escape(agent)
                tag += '<script src="/_review/share.js" data-agent="%s"></script>' % attr     # the Share pill
                tag += TAB_ALERT_TAG
                tag += '<script src="/_review/files.js" data-agent="%s"></script>' % attr   # its folder, at the end
                tag += '<script src="/_review/panel.js" data-agent="%s"></script>' % attr
                tag += NEWAGENT_TAG % attr
        tag = tag.encode()
        i = html.lower().rfind(b"</body>")
        html = html[:i] + tag + html[i:] if i >= 0 else html + tag
        if path != AGENT_LIST:
            html = colleagues.add_card_row(html, colleagues.card_row(ROOT, AGENTS.colleagues(agent),
                                                                     AGENTS.colleague_modes(agent)))
        if path != AGENT_LIST and not re.search(rb"<style[\s>]", html, re.I):   # shared style, first in <head>
            m = re.search(rb"<head(?:\s[^>]*)?>", html, re.I)
            j = m.end() if m else 0
            html = html[:j] + INDEX_CSS_TAG + html[j:]
        if path != AGENT_LIST:   # each <img src="x.svg"> sent as the <svg> itself: its text selects (svg_inline.py)
            html = svg_inline.expand(html.decode("utf-8", "surrogateescape"), os.path.dirname(path),
                                     ROOT).encode("utf-8", "surrogateescape")
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
    REMOTES.close()
    sys.exit(0)


if __name__ == "__main__":
    os.chdir(ROOT)   # Python 3.6's handler serves the current directory
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    threading.Thread(target=housekeeping, daemon=True).start()
    threading.Thread(target=repeats, daemon=True).start()
    threading.Thread(target=REMOTES.run, daemon=True).start()
    with ThreadingServer((BIND, PORT), HtmlOnlyHandler) as httpd:
        print("Serving .html under %s on %s:%d" % (ROOT, BIND, PORT), flush=True)
        httpd.serve_forever()
