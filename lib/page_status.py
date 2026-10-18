"""Status bar html_server.py puts at the top of every page: what the assistant is working on and
the owner's SLURM jobs whose working directory is inside that folder (open items are in the page's
summary card).
"""
import html
import os
import re
import subprocess
import threading
import time

from dirai_config import within

SQUEUE_TTL_S = 30
# Jobs come from sacct (the accounting database), not squeue: on this cluster squeue --me takes
# seconds and sometimes hangs, sacct answers in milliseconds. With --state and no start time,
# sacct lists the jobs in those states right now.
ACTIVE = "PENDING,RUNNING,REQUEUED,SUSPENDED,RESIZING"
_lock = threading.Lock()
_cache = {"time": 0.0, "jobs": []}


def seconds(d):
    """[D-]HH:MM:SS (or MM:SS) to seconds; None for UNLIMITED and the like."""
    m = re.match(r"(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+)$", d or "")
    if not m:
        return None
    days, h, mi, sec = (int(x or 0) for x in m.groups())
    return ((days * 24 + h) * 60 + mi) * 60 + sec


def duration(n):
    days, rest = divmod(n, 86400)
    return ("%d-" % days if days else "") + "%02d:%02d:%02d" % (rest // 3600, rest // 60 % 60, rest % 60)


def active_jobs():
    """The owner's pending/running jobs as dicts, or None if sacct failed."""
    try:
        p = subprocess.run(["sacct", "-X", "-n", "-P", "--state=" + ACTIVE,
                            "-o", "JobID,JobName,State,Elapsed,Timelimit,NodeList,Reason,WorkDir"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode:
        return None
    out = []
    for line in p.stdout.decode("utf-8", "replace").splitlines():
        f = line.split("|", 7)
        if len(f) != 8:
            continue
        jid, name, state, elapsed, limit, nodes, reason, workdir = f
        state = state.split()[0]                        # "CANCELLED by 123" style suffixes
        left = None
        if seconds(limit) is not None and seconds(elapsed) is not None:
            left = duration(max(0, seconds(limit) - seconds(elapsed)))
        out.append({"id": jid, "name": name, "state": state, "time": elapsed, "left": left or limit,
                    "where": nodes if state == "RUNNING" else "(%s)" % reason, "workdir": workdir})
    return out


def jobs(fresh=False):
    """The owner's jobs as dicts, cached for SQUEUE_TTL_S seconds."""
    with _lock:
        if fresh or time.time() - _cache["time"] > SQUEUE_TTL_S:
            got = active_jobs()
            if got is not None:
                _cache["jobs"] = got
            _cache["time"] = time.time()
        return list(_cache["jobs"])


def job_dirs(page_dir):
    """Folders whose jobs belong to the page: the page folder, plus the absolute paths listed in
    its job_dirs.txt (one per line, # comments) for work it runs elsewhere, e.g. a test sweep
    in another checkout."""
    dirs = [os.path.realpath(page_dir)]
    try:
        with open(os.path.join(page_dir, "job_dirs.txt"), encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if line.startswith("/"):
                    dirs.append(os.path.realpath(line))
    except OSError:
        pass
    return dirs


def page_jobs(page_dir, fresh=False, all_jobs=None):
    """The page's jobs (see job_dirs); sub is the working directory relative to the page
    folder, or absolute when it is elsewhere."""
    page_dir = os.path.realpath(page_dir)
    dirs = job_dirs(page_dir)
    out = []
    for j in jobs(fresh) if all_jobs is None else all_jobs:
        wd = os.path.realpath(j["workdir"])
        if any(within(wd, d) for d in dirs):
            out.append(dict(j, sub=os.path.relpath(wd, page_dir) if within(wd, page_dir) else wd))
    return out


def base_id(job_id):
    """123 for 123, 123_4 and 123_[5-9] (array tasks belong to the job sbatch printed)."""
    return job_id.split("_", 1)[0]


def live_ids():
    """Base ids of the owner's jobs still in the queue, or None if sacct failed (so a
    hiccup never looks like every job finished)."""
    got = active_jobs()
    return None if got is None else {base_id(j["id"]) for j in got}


def job_report(ids):
    """One line per job from sacct: id, name, final state, elapsed, exit code."""
    try:
        out = subprocess.run(["sacct", "-j", ",".join(ids), "-X", "-n", "-P",
                              "-o", "JobID,JobName,State,Elapsed,ExitCode"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30).stdout.decode()
    except (OSError, subprocess.SubprocessError):
        out = ""
    lines = ["  ".join(l.split("|")) for l in out.splitlines() if l.strip()]
    return "\n".join(lines) or "(sacct had no record of jobs %s)" % ", ".join(ids)


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
    """HTML for the status bar of the page in page_dir (work = Reviews.working(page) or None): what
    the assistant is working on and the SLURM jobs, each only when there is one; "" when there is
    neither (the page's summary card says what is open)."""
    parts = [working_html(work)] if work else []
    js = page_jobs(page_dir)
    if js:
        parts.append("<div><b>Jobs in the queue:</b><ul style=\"margin:2px 0 0;padding-left:22px\">%s</ul></div>" % "".join(
            "<li><code>%s</code> %s &middot; %s %s%s &middot; %s%s</li>" % (
                html.escape(j["id"]), html.escape(j["name"]), html.escape(j["state"]),
                html.escape(j["time"]),
                (" (%s left)" % html.escape(j["left"])) if j["state"] == "RUNNING" else "",
                html.escape(j["where"]),
                (" &middot; in <code>%s/</code>" % html.escape(j["sub"])) if j["sub"] != "." else "")
            for j in js))
    if not parts:
        return ""
    return ('<div id="page-status" style="margin:0 0 12px;padding:8px 14px;border-bottom:1px solid '
            'rgba(128,128,128,.4);background:rgba(128,128,128,.08);font:13px/1.45 system-ui;color:inherit">'
            '%s</div>' % "".join(parts))
