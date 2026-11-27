"""Every kind of background job an agent can leave running, behind one interface (agents.py waits on
them, slurm.status_bar lists them). Three backends:

- slurm: the owner's queued jobs from sacct (slurm.py). A machine without sacct simply has none,
  which is not a failure; a failing sacct is (slurm_active() -> None: "unknown", never "all done").
- local: processes started with scripts/dirai_job.py (`python3 dirai_job.py run -- cmd ...`), or
  adopted by the server at the end of a run (adopt_strays: a process the run left behind). Each is a
  record <folder>/.dirai_jobs/L<n>.json (id, name, cmd, workdir, log, pid, start, started) in the
  agent's folder; dirai_job writes <id>.exit ("<code> <epoch>") when the command ends. A job is
  running while its pid is alive with the recorded start time (a reused pid doesn't count).
- modal: Modal function calls (fc-... ids a run printed, e.g. from .spawn()). The server records them
  as <folder>/.dirai_jobs/fc-....json and polls them (scripts/modal_poll.py, run by a Python that has
  modal: $DIRAI_MODAL_PYTHON, else the nearest .venv with bin/modal above the agent's folder, else
  the modal on PATH) at most every MODAL_POLL_S. An id Modal no longer knows counts as ended.

Job ids are strings: SLURM "123" (base id; array tasks 123_4 belong to it), local "L17", Modal
"fc-<26 characters>". Records sit in the agent folder (a dot-folder: the Files section skips it and
DirAI's .gitignore lines keep it out of commits), and in the folders of its job_dirs.txt.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

import dirai_config
import slurm
from dirai_config import within

JOBS_DIR = ".dirai_jobs"
MODAL_POLL_S = 240          # a Modal call's state is asked at most this often
MODAL_TIMEOUT_S = 90
LOG_TAIL = 15               # lines of a local job's log in the report
FC_RE = re.compile(r"\bfc-[0-9A-Za-z]{26}\b")
LOCAL_RE = re.compile(r"^L\d+$")
POLL_SCRIPT = os.path.join(dirai_config.SCRIPTS_DIR, "modal_poll.py")
_lock = threading.Lock()
_modal_cache = {}           # id -> (time asked, state, detail)


def kind(job_id):
    if LOCAL_RE.match(job_id):
        return "local"
    if job_id.startswith("fc-"):
        return "modal"
    return "slurm"


def base_id(job_id):
    return slurm.base_id(job_id) if kind(job_id) == "slurm" else job_id


# --- processes ----------------------------------------------------------------------------------
def _stat(pid):
    """(ppid, sid, tty_nr, start ticks) of a live process from /proc, or None."""
    try:
        with open("/proc/%d/stat" % int(pid), "rb") as f:
            s = f.read().decode("utf-8", "replace")
    except (OSError, ValueError):
        return None
    rest = s[s.rfind(")") + 2:].split()      # after "pid (comm) "; comm may hold spaces and ')'
    if len(rest) < 20 or rest[0] == "Z":       # a zombie has finished
        return None
    return int(rest[1]), int(rest[3]), int(rest[4]), rest[19]


def proc_start(pid):
    """An opaque start stamp of a live process (its /proc start time), "" where there is no /proc
    but the process exists, None if it doesn't."""
    st = _stat(pid)
    if st:
        return st[3]
    if os.path.isdir("/proc"):
        return None
    try:
        os.kill(int(pid), 0)
        return ""
    except (OSError, ValueError):
        return None


def alive(pid, start):
    now = proc_start(pid)
    return now is not None and (not start or not now or now == start)


def _boot_time():
    try:
        with open("/proc/stat") as f:
            for line in f:
                if line.startswith("btime "):
                    return int(line.split()[1])
    except OSError:
        pass
    return None


def _ticks_to_epoch(ticks, btime=None):
    btime = btime if btime is not None else _boot_time()
    return None if btime is None else btime + int(ticks) / os.sysconf("SC_CLK_TCK")


# --- records ------------------------------------------------------------------------------------
def records_dir(folder):
    return os.path.join(folder, JOBS_DIR)


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write(path, rec):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=1)
    os.replace(tmp, path)


def records(folder):
    """All job records in folder's .dirai_jobs, oldest first."""
    d = records_dir(folder)
    try:
        names = sorted(n for n in os.listdir(d) if n.endswith(".json"))
    except OSError:
        return []
    out = [r for r in (_read(os.path.join(d, n)) for n in names) if r and r.get("id")]
    return sorted(out, key=lambda r: r.get("started") or 0)


def find(job_id, folders):
    for f in folders:
        rec = _read(os.path.join(records_dir(f), job_id + ".json"))
        if rec:
            return f, rec
    return None, None


def new_local_id(folder):
    """The next free L<n> in folder (created exclusively, so two launches can't share one)."""
    d = records_dir(folder)
    os.makedirs(d, exist_ok=True)
    n = 1 + max([int(x[1:-5]) for x in os.listdir(d) if re.match(r"^L\d+\.json$", x)] or [0])
    while True:
        try:
            os.close(os.open(os.path.join(d, "L%d.json" % n), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return "L%d" % n
        except FileExistsError:
            n += 1


def local_exit(folder, job_id):
    """(exit code, end epoch) once dirai_job recorded them, else None."""
    try:
        with open(os.path.join(records_dir(folder), job_id + ".exit")) as f:
            code, ended = f.read().split()[:2]
        return int(code), float(ended)
    except (OSError, ValueError):
        return None


def local_state(folder, rec):
    """RUNNING, COMPLETED (exit 0), FAILED (other exit) or ENDED (gone, no exit code: adopted or killed)."""
    ex = local_exit(folder, rec["id"])
    if ex:
        return "COMPLETED" if ex[0] == 0 else "FAILED"
    return "RUNNING" if alive(rec.get("pid"), rec.get("start")) else "ENDED"


# --- adopting what a run left behind ------------------------------------------------------------
def adopt_strays(agent_dir, since, run_sids=(), exclude_sids=()):
    """Processes a run left running become local jobs of the agent, so it stays "working" for them:
    those in the run's own sessions (run_sids: the pids of the processes the server started for it,
    each a session leader), and session leaders started during the run (since, epoch) with no
    terminal and a working directory in agent_dir (setsid nohup ... &), unless they belong to
    another run of the server (exclude_sids). Already recorded ones are skipped. Returns new ids."""
    if not os.path.isdir("/proc"):
        return []
    agent_dir = os.path.realpath(agent_dir)
    btime, uid, me = _boot_time(), os.getuid(), os.getsid(0)
    known = set()
    for rec in records(agent_dir):
        known.add(rec.get("pid"))
        known.add(rec.get("sid"))
    groups = {}
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        pid = int(name)
        try:
            if os.stat("/proc/" + name).st_uid != uid:
                continue
        except OSError:
            continue
        st = _stat(pid)
        if not st:
            continue
        ppid, sid, tty, start = st
        t = _ticks_to_epoch(start, btime)
        if tty != 0 or sid == me or sid in exclude_sids or t is None or t < since - 2:
            continue
        if sid not in run_sids:
            if pid != sid:
                continue
            try:
                cwd = os.path.realpath(os.readlink("/proc/%d/cwd" % pid))
            except OSError:
                continue
            if not within(cwd, agent_dir):
                continue
        groups.setdefault(sid, []).append((t, pid, start))
    new = []
    for sid, procs in sorted(groups.items()):
        t, pid, start = min(procs)
        if pid in known or sid in known:
            continue
        try:
            with open("/proc/%d/cmdline" % pid, "rb") as f:
                cmd = f.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
            cwd = os.readlink("/proc/%d/cwd" % pid)
        except OSError:
            continue
        jid = new_local_id(agent_dir)
        _write(os.path.join(records_dir(agent_dir), jid + ".json"), {
            "id": jid, "kind": "local", "name": os.path.basename(cmd.split(" ")[0]) if cmd else "process",
            "cmd": cmd, "workdir": cwd, "log": None, "pid": pid, "sid": sid, "start": start,
            "started": t, "adopted": True})
        new.append(jid)
    return new


# --- Modal ----------------------------------------------------------------------------------------
def modal_python(start_dir):
    """A Python that can import modal, for start_dir's agent: see the module docstring. None if none."""
    env = os.environ.get("DIRAI_MODAL_PYTHON")
    if env:
        return env
    d = os.path.realpath(start_dir)
    while True:
        if os.path.exists(os.path.join(d, ".venv", "bin", "modal")):
            py = os.path.join(d, ".venv", "bin", "python")
            if os.path.exists(py):
                return py
        up = os.path.dirname(d)
        if up == d:
            break
        d = up
    m = shutil.which("modal")
    if m:
        py = os.path.join(os.path.dirname(os.path.realpath(m)), "python")
        return py if os.path.exists(py) else None
    return None


def modal_poll(ids, python):
    """{id: (state, detail)} for Modal call ids: running, finished, failed or unknown (Modal doesn't
    know it, e.g. a week old). Calls that can't be asked (no Python, the helper failed) are left out."""
    if not ids or not python:
        return {}
    try:
        p = subprocess.run([python, POLL_SCRIPT] + list(ids), stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, timeout=MODAL_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return {}
    out = {}
    for line in p.stdout.decode("utf-8", "replace").splitlines():
        try:
            m = json.loads(line)
            out[m["id"]] = (m["state"], m.get("detail") or "")
        except (ValueError, KeyError, TypeError):
            continue
    return out


def _modal_states(folder, recs, fresh=False):
    """Bring the Modal records in folder up to date (at most every MODAL_POLL_S per id, unless fresh);
    ended ones get state, detail and ended written into their record."""
    due, now = [], time.time()
    with _lock:
        for r in recs:
            c = _modal_cache.get(r["id"])
            if r.get("ended") is None and (fresh or not c or now - c[0] >= MODAL_POLL_S):
                due.append(r)
    if not due:
        return
    got = modal_poll([r["id"] for r in due], due[0].get("python") or modal_python(folder))
    with _lock:
        for r in due:
            if r["id"] not in got:
                continue
            state, detail = got[r["id"]]
            _modal_cache[r["id"]] = (now, state, detail)
            if state != "running":
                r.update(state=state, detail=detail, ended=now)
                _write(os.path.join(records_dir(folder), r["id"] + ".json"), r)


def register_modal(agent_dir, ids):
    """Record the Modal call ids a run printed; the ones still running are watched. Returns those."""
    ids = [i for i in dict.fromkeys(ids) if not os.path.exists(os.path.join(records_dir(agent_dir), i + ".json"))]
    if not ids:
        return []
    py = modal_python(agent_dir)
    got = modal_poll(ids, py)
    running, now = [], time.time()
    for i in ids:
        state, detail = got.get(i, (None, ""))
        if state != "running":
            continue        # already over (or not ours to ask): nothing to wait for
        with _lock:
            _modal_cache[i] = (now, state, detail)
        _write(os.path.join(records_dir(agent_dir), i + ".json"), {
            "id": i, "kind": "modal", "name": "Modal call", "workdir": os.path.realpath(agent_dir),
            "started": now, "python": py})
        running.append(i)
    return running


# --- the merged view --------------------------------------------------------------------------------
def slurm_active():
    """The owner's queued SLURM jobs; [] on a machine without sacct; None if sacct failed."""
    if not shutil.which("sacct"):
        return []
    return slurm.active_jobs()


def _elapsed(t0, t1=None):
    return slurm.duration(int(max(0, (t1 or time.time()) - (t0 or time.time()))))


def other_jobs(dirs, fresh=False, poll=True):
    """Running local and Modal jobs recorded in dirs, as job dicts. poll=False: Modal calls as last
    known, without asking Modal (a page view must not wait on it)."""
    out = []
    for d in dirs:
        recs = records(d)
        if poll:
            _modal_states(d, [r for r in recs if r.get("kind") == "modal"], fresh)
        for r in recs:
            if r.get("kind") == "modal":
                if r.get("ended") is not None:
                    continue
                out.append({"id": r["id"], "name": r.get("name") or "Modal call", "state": "RUNNING",
                            "time": _elapsed(r.get("started")), "left": None, "where": "Modal",
                            "workdir": r.get("workdir") or d, "kind": "modal"})
            elif local_state(d, r) == "RUNNING":
                out.append({"id": r["id"], "name": r.get("name") or "job", "state": "RUNNING",
                            "time": _elapsed(r.get("started")), "left": None,
                            "where": "pid %s" % r.get("pid"), "workdir": r.get("workdir") or d,
                            "kind": "local", "log": r.get("log")})
    return out


def agent_jobs(agent_dir, fresh=False, slurm_jobs=None, poll=True):
    """The agent's running jobs of every kind (slurm.agent_jobs for SLURM: by working directory in
    its folder or its job_dirs.txt; local and Modal: the records there), each with sub, the working
    directory relative to the agent's folder (absolute when elsewhere)."""
    agent_dir = os.path.realpath(agent_dir)
    out = [dict(j, kind="slurm") for j in slurm.agent_jobs(agent_dir, fresh, slurm_jobs)]
    for j in other_jobs(slurm.job_dirs(agent_dir), fresh, poll):
        wd = os.path.realpath(j["workdir"])
        out.append(dict(j, sub=os.path.relpath(wd, agent_dir) if within(wd, agent_dir) else wd))
    return out


def _tail(path, n=LOG_TAIL):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 16384))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except (OSError, TypeError):
        return None
    return "\n".join("    " + l for l in lines[-n:])


def report(ids, agent_dir):
    """What became of jobs ids: sacct's line for SLURM jobs; state, exit code, elapsed and the log's
    last lines for local ones; state and the returned value (or error) for Modal calls."""
    dirs = slurm.job_dirs(agent_dir)
    lines = []
    sl = [i for i in ids if kind(i) == "slurm"]
    if sl:
        lines.append(slurm.job_report(sl) if shutil.which("sacct") else "(no sacct here for SLURM jobs %s)" % ", ".join(sl))
    for i in ids:
        k = kind(i)
        if k == "slurm":
            continue
        folder, rec = find(i, dirs)
        if not rec:
            lines.append("%s  (no record)" % i)
        elif k == "local":
            ex = local_exit(folder, i)
            state = local_state(folder, rec)
            code = "exit %d" % ex[0] if ex else "no exit code (%s)" % (
                "adopted process, not started with dirai_job" if rec.get("adopted") else "killed?")
            lines.append("%s  %s  %s  %s  %s" % (i, rec.get("name") or "job", state,
                                                  _elapsed(rec.get("started"), ex[1] if ex else None), code))
            lines.append("    command: %s" % (rec.get("cmd") or "?"))
            tail = _tail(rec.get("log")) if rec.get("log") else None
            if tail:
                lines.append("    last lines of %s:\n%s" % (rec["log"], tail))
        else:
            lines.append("%s  Modal call  %s  %s" % (i, (rec.get("state") or "?").upper(),
                                                     _elapsed(rec.get("started"), rec.get("ended"))))
            if rec.get("detail"):
                lines.append("    %s" % rec["detail"])
    return "\n".join(lines) or "(no record of jobs %s)" % ", ".join(ids)


def cancel(job_id, agent_dir):
    """Stop a job: scancel, or SIGTERM a local job's process group. Returns a message."""
    k = kind(job_id)
    if k == "slurm":
        r = subprocess.run(["scancel", job_id], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return r.stdout.decode("utf-8", "replace").strip() or "scancel %s sent" % job_id
    folder, rec = find(job_id, slurm.job_dirs(agent_dir))
    if not rec:
        return "no record of %s" % job_id
    if k == "modal":
        return "Modal calls are cancelled in Modal (FunctionCall.from_id(%r).cancel())" % job_id
    if not alive(rec.get("pid"), rec.get("start")):
        return "%s is not running" % job_id
    import signal
    try:
        os.killpg(os.getpgid(rec["pid"]), signal.SIGTERM)
    except OSError as e:
        return "could not stop %s: %s" % (job_id, e)
    return "%s stopped (SIGTERM)" % job_id


if __name__ == "__main__":      # python3 jobs.py <agent folder>: its running jobs
    for j in agent_jobs(sys.argv[1] if len(sys.argv) > 1 else ".", fresh=True):
        print(json.dumps(j))
