"""Status bar html_server.py puts at the top of every page: the page's open todo items
(from todo.md in its folder) and the owner's SLURM jobs whose working directory is
inside that folder.

todo.md format: one item per line, "- [ ] open item" or "- [x] done item" (done items
are not shown); plain "- item" lines count as open.
"""
import html
import os
import re
import subprocess
import threading
import time

SQUEUE_TTL_S = 30
_lock = threading.Lock()
_cache = {"time": 0.0, "jobs": []}


def jobs():
    """The owner's jobs as dicts, from squeue, cached for SQUEUE_TTL_S seconds."""
    with _lock:
        if time.time() - _cache["time"] > SQUEUE_TTL_S:
            try:
                out = subprocess.run(
                    ["squeue", "--me", "-h", "-o", "%i|%j|%T|%M|%L|%R|%Z"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15).stdout.decode()
                rows = [l.split("|", 6) for l in out.splitlines() if l.count("|") == 6]
                _cache["jobs"] = [dict(zip(("id", "name", "state", "time", "left", "where", "workdir"), r))
                                  for r in rows]
            except (OSError, subprocess.SubprocessError):
                pass
            _cache["time"] = time.time()
        return list(_cache["jobs"])


def page_jobs(page_dir):
    page_dir = os.path.realpath(page_dir)
    out = []
    for j in jobs():
        wd = os.path.realpath(j["workdir"])
        if wd == page_dir or wd.startswith(page_dir + os.sep):
            j = dict(j, sub=os.path.relpath(wd, page_dir))
            out.append(j)
    return out


def open_todos(page_dir):
    try:
        with open(os.path.join(page_dir, "todo.md"), encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    items = []
    for line in lines:
        m = re.match(r"\s*[-*]\s+(\[( |x|X)\]\s+)?(.*\S)", line)
        if m and (m.group(2) or " ") == " ":
            items.append(m.group(3))
    return items


def working_html(work):
    what, started, until, reason = work
    what = what if len(what) <= 300 else what[:300] + "..."
    if until and until > time.time():
        when = "queued: %s; sends at %s" % (html.escape(reason or "Claude usage limit"),
                                            time.strftime("%b %d %H:%M", time.localtime(until)))
    elif started:
        mins = int((time.time() - started) // 60)
        when = "since %s, %s" % (time.strftime("%H:%M", time.localtime(started)),
                                 "%d min" % mins if mins < 120 else "%.1f h" % (mins / 60))
    else:
        when = "waiting for a free slot"
    return '<div style="margin-bottom:4px"><b>Working on:</b> <span style="opacity:.7">(%s)</span> %s</div>' % (
        when, html.escape(what))


def bar(page_dir, work=None):
    """HTML for the status bar of the page in page_dir; work = Reviews.working(page) or None."""
    todos = open_todos(page_dir)
    if todos is None:
        todo_html = '<span style="opacity:.6">none recorded (add a todo.md)</span>'
    elif not todos:
        todo_html = '<span style="opacity:.6">none</span>'
    else:
        todo_html = "<ol style=\"margin:2px 0 0;padding-left:22px\">%s</ol>" % "".join(
            "<li>%s</li>" % html.escape(t) for t in todos)
    js = page_jobs(page_dir)
    if not js:
        job_html = '<span style="opacity:.6">none</span>'
    else:
        job_html = "<ul style=\"margin:2px 0 0;padding-left:22px\">%s</ul>" % "".join(
            "<li><code>%s</code> %s &middot; %s %s%s &middot; %s%s</li>" % (
                html.escape(j["id"]), html.escape(j["name"]), html.escape(j["state"]),
                html.escape(j["time"]),
                (" (%s left)" % html.escape(j["left"])) if j["state"] == "RUNNING" else "",
                html.escape(j["where"]),
                (" &middot; in <code>%s/</code>" % html.escape(j["sub"])) if j["sub"] != "." else "")
            for j in js)
    return ('<div id="page-status" style="margin:0 0 12px;padding:8px 14px;border-bottom:1px solid '
            'rgba(128,128,128,.4);background:rgba(128,128,128,.08);font:13px/1.45 system-ui;color:inherit">'
            '%s<div><b>Remaining todo:</b> %s</div><div style="margin-top:4px"><b>Jobs in the queue:</b> %s</div>'
            '</div>' % (working_html(work) if work else "", todo_html, job_html))
