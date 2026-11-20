"""Codex CLI as the second agent engine (proposal 17, improvement/other-engines).

The engine is a hard switch per machine: ENGINE_FILE says "claude" (the default; "codex" by default on a
machine without Claude Code where Codex is signed in) or "codex", and only the owner changes it (the title of the machine's usage widget on the agent list: set_engine()).
Every tree served on the machine uses it; the queue reads it whenever it starts a run, so held and
new messages go to the engine in force then. A paused engine means waiting: the other one is never
used as a fallback.

A Codex run: `codex exec --json --sandbox workspace-write -C <agent dir> [--add-dir <dir>]... [resume
<thread id>] <prompt>` (command()). Its JSONL events are read by read_events(): the thread id (the
session, for `exec resume`), the agent's last message (the reply), the token usage, the commands it
ran (for "Submitted batch job N"), and an error. Codex's sandbox confines writes to the agent's
folder and --add-dir (network on, so sbatch works); it doesn't confine reads, and `exec` never asks
the owner, so Codex runs only in allowlist mode (the switch refuses ask mode).

Plan usage: `codex exec --json` doesn't carry it, and Codex has no usage command (its /status only
links to chatgpt.com), but each session's log ~/.codex/sessions/YYYY/MM/DD/rollout-*-<thread id>.jsonl
has "rate_limits" records: primary/secondary windows {used_percent, window_minutes, resets_at}, plan
type and credits. The last one seen is kept in USAGE_FILE ("as of the last Codex run"). The windows
depend on the plan (Free: one 30-day window; Plus: 5-hour and weekly; Pro: no 5-hour), so usage()
reports whatever windows there are, named by their length ("w300", "w10080", "w43200"), each with a
pause level (PAUSE_FILE, 100 % unless set lower on the agent list).
"""
import glob
import json
import os
import shutil
import threading
import time

import dirai_config

ENGINES = ("claude", "codex")
ENGINE_FILE = os.path.join(dirai_config.CONFIG_DIR, "engine.json")
USAGE_FILE = os.path.join(dirai_config.CONFIG_DIR, "codex_usage.json")
PAUSE_FILE = os.path.join(dirai_config.CONFIG_DIR, "codex_usage_stop.json")
CODEX_HOME = os.path.expanduser(os.environ.get("CODEX_HOME", "~/.codex"))
_USER_CODEX = os.path.expanduser("~/.local/bin/codex")
# DIRAI_CODEX_CMD: the codex to run, if not ~/.local/bin/codex (or codex on PATH)
CODEX_CMD = os.environ.get("DIRAI_CODEX_CMD") or (
    _USER_CODEX if os.path.exists(_USER_CODEX) else shutil.which("codex") or _USER_CODEX)
# DIRAI_CLAUDE_CMD (or its old name REVIEW_CLAUDE_CMD): the claude to run, if not ~/.local/bin/claude
# (agents.CLAUDE_CMD is this one)
CLAUDE_CMD = (os.environ.get("DIRAI_CLAUDE_CMD") or os.environ.get("REVIEW_CLAUDE_CMD")
              or os.path.expanduser("~/.local/bin/claude"))
RESUME_MARGIN_S = 120
LIMIT_FALLBACK_S = 1800      # a limit refusal whose reset time can't be found: retry after this
WINDOW_LABELS = {300: "5-hour", 1440: "Daily", 10080: "Weekly", 43200: "30-day"}
LIMIT_WORDS = ("usage limit", "rate limit", "hit your", "reached your", "limit reached")

_lock = threading.Lock()


# --- the switch -------------------------------------------------------------------------------
def engine():
    """The machine's engine: the one the owner last switched to, else "claude", or "codex" on a
    machine without Claude Code where Codex is signed in."""
    e = (dirai_config.load_json(ENGINE_FILE, {}) or {}).get("engine")
    if e in ENGINES:
        return e
    return "codex" if not claude_installed() and logged_in() else "claude"


def claude_installed():
    return os.path.exists(CLAUDE_CMD)


def installed():
    return os.path.exists(CODEX_CMD)


def logged_in():
    """True if Codex is installed and has a login here (ChatGPT sign-in or API key)."""
    return installed() and os.path.exists(os.path.join(CODEX_HOME, "auth.json"))


def set_engine(name, permissions="allowlist"):
    """Switch the machine to name. None if done, else why not."""
    if name not in ENGINES:
        return "unknown engine: %s" % name
    if name == "claude" and not claude_installed():
        return "Claude Code isn't installed on this machine (%s)." % CLAUDE_CMD
    if name == "codex":
        if not installed():
            return "Codex isn't installed on this machine (%s)." % CODEX_CMD
        if not logged_in():
            return "Codex isn't signed in on this machine: run `codex login` (or `codex`) once in a terminal."
        if permissions == "ask":
            return ("Codex can't ask for permissions (it runs in allowlist mode only). Switch this tree's "
                    "Permissions to allowlist first.")
    with _lock:
        dirai_config.save_json(ENGINE_FILE, {"engine": name, "since": int(time.time())})
    return None


# --- a run ------------------------------------------------------------------------------------
def command(agent_dir, prompt, session=None, add_dirs=(), model=None):
    """The codex command line for one run in agent_dir. add_dirs: more folders it may write."""
    cmd = [CODEX_CMD, "exec", "--json", "--skip-git-repo-check", "--sandbox", "workspace-write",
           "-c", "sandbox_workspace_write.network_access=true", "-C", agent_dir]
    for d in add_dirs:
        if os.path.isdir(d) and os.path.realpath(d) != os.path.realpath(agent_dir):
            cmd += ["--add-dir", d]
    if model:
        cmd += ["-m", model]
    if session:
        cmd += ["resume", session]
    return cmd + [prompt]


def read_events(lines, on_event=None):
    """Read a run's JSONL events: {"session_id", "result" (its last message), "usage", "commands":
    [their output], "error", "is_error"}. on_event(event) is called for each one."""
    out = {"session_id": None, "result": "", "usage": None, "commands": [], "error": None, "is_error": False}
    for line in lines:
        try:
            m = json.loads(line)
        except ValueError:
            continue
        if not isinstance(m, dict):
            continue
        if on_event:
            on_event(m)
        kind, item = m.get("type"), m.get("item") or {}
        if kind == "thread.started":
            out["session_id"] = m.get("thread_id") or out["session_id"]
        elif kind == "item.completed" and item.get("type") == "agent_message":
            out["result"] = item.get("text") or out["result"]
        elif kind == "item.completed" and item.get("type") == "command_execution":
            out["commands"].append(item.get("aggregated_output") or "")
        elif kind == "turn.completed":
            out["usage"] = m.get("usage")
        elif kind == "turn.failed":
            out["error"] = (m.get("error") or {}).get("message") or "turn failed"
            out["is_error"] = True
        elif kind == "error" and not str(m.get("message", "")).startswith("Reconnecting"):
            out["error"] = m.get("message") or out["error"]
    return out


def is_limit(text):
    t = (text or "").lower()
    return any(w in t for w in LIMIT_WORDS)


def session_log(session):
    """Path of a Codex session's log (rollout file), or None."""
    if not session:
        return None
    paths = glob.glob(os.path.join(CODEX_HOME, "sessions", "*", "*", "*", "rollout-*-%s.jsonl" % session))
    return max(paths, key=os.path.getmtime) if paths else None


def _find(d, key):
    """The first value of key in nested dict d (depth-first), or None."""
    if isinstance(d, dict):
        if key in d:
            return d[key]
        for v in d.values():
            r = _find(v, key)
            if r is not None:
                return r
    return None


def read_rate_limits(session):
    """The last rate_limits record in the session's log, with the session's "model", or None."""
    path = session_log(session)
    if not path:
        return None
    last, model = None, None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"rate_limits"' not in line and '"model"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                m = _find(d, "model")
                model = m if isinstance(m, str) else model
                rl = _find(d, "rate_limits")
                if isinstance(rl, dict):
                    last = rl
    except OSError:
        return None
    return dict(last, model=model) if last else None


def _label(mins):
    if mins in WINDOW_LABELS:
        return WINDOW_LABELS[mins]
    return "%d-hour" % (mins // 60) if mins and mins % 60 == 0 else "%d-min" % mins


def record_usage(session):
    """After a Codex run: keep the session log's last rate limits as the machine's Codex usage."""
    rl = read_rate_limits(session)
    if not rl:
        return None
    windows = []
    for key in ("primary", "secondary"):
        w = rl.get(key)
        if isinstance(w, dict) and w.get("used_percent") is not None:
            mins = int(w.get("window_minutes") or 0)
            windows.append({"name": "w%d" % mins, "minutes": mins, "label": _label(mins),
                            "percent": float(w["used_percent"]), "resets": w.get("resets_at")})
    u = {"windows": windows, "plan": rl.get("plan_type"), "model": rl.get("model"),
         "credits": rl.get("credits"), "reached": rl.get("rate_limit_reached_type"), "checked": int(time.time())}
    with _lock:
        dirai_config.save_json(USAGE_FILE, u)
    return u


# --- usage and pause levels -------------------------------------------------------------------
def pause_levels():
    saved = dirai_config.load_json(PAUSE_FILE, {}) or {}
    return {k: int(v) for k, v in saved.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool) and 1 <= v <= 100}


def set_pause_level(name, percent):
    """The pause level for one Codex window ("w<minutes>"), 1-100. False if invalid."""
    try:
        percent = int(percent)
    except (TypeError, ValueError):
        return False
    if not (isinstance(name, str) and name[:1] == "w" and name[1:].isdigit() and 1 <= percent <= 100):
        return False
    with _lock:
        cur = pause_levels()
        cur[name] = percent
        dirai_config.save_json(PAUSE_FILE, cur)
    return True


def usage():
    """The machine's Codex usage as of its last run: {"windows": [{"name", "label", "percent",
    "resets", "minutes"}], "plan", "model", "credits", "checked", "stop": {name: %}} (no "windows"
    before the first run), with "installed" and "logged_in"."""
    u = dirai_config.load_json(USAGE_FILE, {}) or {}
    levels = pause_levels()
    now = time.time()
    for w in u.get("windows", []):
        if w.get("resets") and w["resets"] < now:      # that window has reset since the reading
            w["percent"], w["stale"] = 0.0, True
    u["stop"] = {w["name"]: levels.get(w["name"], 100) for w in u.get("windows", [])}
    u["installed"], u["logged_in"] = installed(), logged_in()
    return u


def pause_until():
    """(until, reason) if Codex runs should wait for a window to reset, else (0, "")."""
    u = usage()
    until, reason = 0, ""
    for w in u.get("windows", []):
        stop = u["stop"].get(w["name"], 100)
        if w["percent"] >= stop and w.get("resets"):
            t = w["resets"] + RESUME_MARGIN_S
            if t > until:
                until, reason = t, "Codex usage at %.0f%% of the %s limit (pause at %d%%)" % (
                    w["percent"], w["label"].lower(), stop)
    return until, reason


def limit_until(session, text):
    """A run that failed on Codex's limit: when to try again (the window's reset), else None."""
    if not is_limit(text):
        return None
    u = record_usage(session) or {}
    resets = [w["resets"] for w in u.get("windows", []) if w.get("resets") and w["percent"] >= 100]
    return (max(resets) + RESUME_MARGIN_S) if resets else time.time() + LIMIT_FALLBACK_S


def annotate(u):
    """The agent list's usage payload (Claude's) with the machine's engine and Codex usage added."""
    u = dict(u or {})
    u["engine"] = engine()
    try:
        u["codex"] = usage()
    except Exception as e:
        u["codex"] = {"error": "%s: %s" % (type(e).__name__, e)}
    return u


# --- context when the engine changes -----------------------------------------------------------
def entry_engine(e):
    """The engine a thread entry came from ("claude" for replies from before engines existed)."""
    return e.get("engine") or ("claude" if e.get("role") == "claude" else None)


def handoff_prompt(thread, prompt, now_engine, keep=6, limit=1500):
    """The agent's session on now_engine missed the turns run on the other engine since it last ran:
    quote them (at most keep, each cut to limit characters) ahead of the new message. thread ends
    with the new message itself. prompt unchanged if nothing was missed."""
    earlier = thread[:-1]
    last = max([i for i, e in enumerate(earlier) if entry_engine(e) == now_engine] or [-1])
    missed = [e for e in earlier[last + 1:] if e.get("role") in ("user", "claude")]
    if not any(entry_engine(e) not in (None, now_engine) for e in missed):
        return prompt
    missed = missed[-keep:]
    other = "Codex" if now_engine == "claude" else "Claude Code"
    quoted = "\n\n".join("[%s, %s]\n%s" % ("owner" if e["role"] == "user" else other, e.get("time", ""),
                                          e["text"][:limit] + ("..." if len(e["text"]) > limit else ""))
                         for e in missed)
    return ("While you were away, this agent ran on %s. Its messages since your last turn follow; read "
            "this folder's index.html again before acting, as it may have changed.\n\n--- meanwhile ---\n%s\n"
            "--- end ---\n\n%s" % (other, quoted, prompt))
