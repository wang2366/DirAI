"""The agents of a tree, for server.py. An agent is a folder holding an index.html, with a chat
thread; each message the owner sends goes to a background `claude -p` session working in that folder.

Status per agent: working (Claude is running) -> unread (new reply) -> read -> closed.
A new message reopens an agent. When a run hits the Claude usage limit, the agent is "queued":
its message is kept (in agents.json, so it survives a restart) and sent again, in the same
session, shortly after the limit resets; no run starts before then. Runs are also held back
(same "queued" status) while plan usage is at or above the owner's pause levels
(claude_usage.pause_levels(): 100 % of the 5-hour session and of the weekly limit unless set lower
with the agent list's sliders), until that limit resets. State for one served root lives in
<root>/www/agents.json.

Only the owner can use any of this: requests must come from 127.0.0.1 (the SSH tunnel
lands on this node's loopback) and carry the secret key cookie (see login_key()).
Everyone else gets 404 for /_review/* and sees index.html files without the panel.

What runs may do is in agent_permissions.py, what they are told in agent_prompts.py, and how a
claude process is driven and read in claude_run.py.
"""
import contextlib
import datetime
import hashlib
import html
import json
import os
import secrets
import shutil
import signal
import subprocess
import threading
import time
import traceback
import urllib.request

import agent_files
import claude_usage
import codex_engine
import colleagues
import dirai_config
import dirai_card
import genai_relay
import page_undo
import slurm
import svg_inline
from claude_run import (SUBMITTED_RE, Login, LiveRun, RunCancelled, auth_error, context_tokens, limit_reset,
                        signal_group, stop_process, submitted_jobs, transcript)
from remotes import machine_name
from dirai_config import load_json
from agent_permissions import (ALWAYS_DENY, DEFAULT_ALLOW, SCRIPT_HINT, always_denied, covered, denial_rules,
                                describe_denial, extra_dirs, is_heredoc, keepable, mcp_config, path_grants,
                                request_denial, shared_grants, unusable)
from agent_prompts import (ANSWERS_PROMPT, APPROVAL, CARD_FIX, GIT_PROMPT, LIMIT_RETRY, NEW_CHAT_MARK, NOTE_CMD, NOTES_FIX, QUEUED_PROMPT, SEL_MAX,
                            STARTER_INDEX, SYSTEM_PROMPT, fresh_prompt, notes_prompt, selection_lines, selection_prompt)
import notes as sticky

KEY_FILE = dirai_config.KEY_FILE
AGENT_RULE_MD = os.path.join(dirai_config.TOOL_DIR, "AGENT_RULE.md")   # agent conventions, appended to every run's instructions
# DIRAI_CLAUDE_CMD (or its old name REVIEW_CLAUDE_CMD): the claude to run, if not the default
CLAUDE_CMD = codex_engine.CLAUDE_CMD
# put ~/.local/bin on each run's PATH: user-installed tools (basecamp) aren't on the server's PATH
USER_BIN = os.path.expanduser("~/.local/bin")
# Background runs use --restricted: user/project/local settings files are ignored (so rules
# granted to interactive sessions never leak in) and file tools stay inside the agent's own folder
# (and everything below it; the tree's top agent: the whole tree) plus the tree's dirai.json
# "read_dirs", which Claude may read; edits need an allow rule (only the agent's folder has one).
# Grants are per agent (st["grants"]): a path the owner names in a comment (path_grants()), or
# "Always allow" on a blocked action (only rules a later command may match: keepable()); "Allow
# once" only reaches the retry it starts (st["once"]); the × in the Permissions list removes one
# (remove_grant()). An agent also gets its colleagues' grants (shared_grants(): not their edits
# unless the colleague is writable; one level, not their colleagues') and may read their folders,
# or edit them per st["coll_mode"] (colleagues.MODES).
TOOLS = "Bash,Read,Edit,Write,Glob,Grep,Skill,TodoWrite,NotebookEdit"
MAX_RUNNING = 5
# A resumed session resends its whole context with every request; warn (panel, list badge) when
# it is this big and offer Compact, which runs Claude Code's /compact on the session.
CONTEXT_WARN = 150000
CONTEXT_HIGH = 300000
COMPACT = "/compact"
# What /compact keeps (manual and automatic): without it the summary may drop the job ids or the
# owner's last request.
COMPACT_KEEP = (COMPACT + " Keep: the objective, open items and job ids, files and paths touched, "
                "decisions the owner made, and the owner's last request.")
FRESH_START = fresh_prompt([], "")[:40]     # how a new session's first message (thread quoted) begins
# Auto compact: when a run ends with the context at or over the limit, /compact is queued at once, while
# the prompt cache is still warm. The limit is per agent (st["auto_compact"], 0 = off) over the tree's
# "auto_compact" in dirai.json; a GenAI Studio model's is capped at AUTO_COMPACT_WINDOW of its window.
# After a compact that didn't shrink the context it pauses (st["auto_compact_paused"]) until the
# context is under the limit again.
AUTO_COMPACT = 200000
AUTO_COMPACT_WINDOW = 0.7
AUTO_COMPACT_CHOICES = [0, 100000, 150000, 200000, 300000]
# Model per agent, picked in the panel (claude --model aliases); Sonnet unless changed, to save tokens.
# The gpt-oss models are served by Ollama on this node (Kuang_work_document/ollama/ollama_ctl.sh
# start); they don't count against the Claude limits, so they also run while the queue is held.
# Purdue RCAC's GenAI Studio (genai.rcac.purdue.edu) serves more models over the same Anthropic-style
# API, with the key made on its site (Settings > Account > API Keys) in GENAI_KEY_FILE. They don't
# count against the Claude limits either. One agent of the user's at a time runs on them, across
# all trees (genai_relay.claim(); one waiting for another tree's is rechecked every GENAI_RECHECK_S),
# and its requests go through genai_relay, which keeps to GenAI Studio's rate limit. They run with --effort medium:
# Claude Code's default "high" is refused by some of them (qwen3.8). Tried 2026-10-18, only these
# finish a Claude Code task: the Ollama-served ones there answer with tool calls written out as text
# (qwen3, qwq, deepseek-r1, qwen3-coder, devstral, llama3.x, mistral, gemma3 ...), and llama4's 16k
# context is less than Claude Code's own prompt. GENAI_MODELS: model -> its context window, which
# Claude Code (assuming 200k for a model it doesn't know) needs to compact in time.
LOCAL_MODELS = ["gpt-oss-20b-t64", "gpt-oss-120b-t64"]
GENAI_MODELS = {"gpt-oss:120b": 131072, "qwen3.8:27b": 65536, "gemma4:26b-a4b": 65536}
NON_CLAUDE = LOCAL_MODELS + list(GENAI_MODELS)
MODELS = ["sonnet", "opus", "fable", "haiku"] + LOCAL_MODELS + list(GENAI_MODELS)
MODEL_LABELS = {"gpt-oss-20b-t64": "gpt-oss 20b (local)", "gpt-oss-120b-t64": "gpt-oss 120b (local)",
                "gpt-oss:120b": "gpt-oss 120b (GenAI Studio)", "qwen3.8:27b": "qwen3.8 27b (GenAI Studio)",
                "gemma4:26b-a4b": "gemma4 26b (GenAI Studio)"}
DEFAULT_MODEL = "sonnet"
OLLAMA_URL = "http://" + os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")
LOCAL_ENV = {"ANTHROPIC_BASE_URL": OLLAMA_URL, "ANTHROPIC_AUTH_TOKEN": "ollama", "ANTHROPIC_API_KEY": "",
             "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
GENAI_URL = os.environ.get("DIRAI_GENAI_URL", "https://genai.rcac.purdue.edu/api")
GENAI_KEY_FILE = os.environ.get("DIRAI_GENAI_KEY_FILE", os.path.expanduser("~/.config/purdue_llm/api_key"))
# The panel offers only the models this machine has (see available_models()), checked this often
MODEL_CHECK_S = 60
GENAI_RECHECK_S = 30
RUN_TIMEOUT_S = 4 * 3600   # working time; time spent waiting for the owner's answers doesn't count
# Permissions, tree-wide (dirai.json "permissions", switched on the agent list; read when a run starts):
# "allowlist": --permission-mode dontAsk: only allowed actions run, the rest are refused and show in
#   the panel (Allow once / Always allow), which grants them for the retry / every later run.
# "ask": an action that isn't allowed waits for the owner in the agent's chat (Allow / Always allow /
#   Deny); the run continues with the answer (--permission-prompt-tool stdio: claude sends its
#   prompts to us over stream-json). ALWAYS_DENY is refused without asking in both modes.
PERMISSION_MODES = ["allowlist", "ask"]
# A run's total time waiting for answers; after that its prompts are denied, so a forgotten one
# doesn't hold a run slot (MAX_RUNNING) for days.
ASK_WAIT_S = 12 * 3600
ASK_DENIED = {
    "deny": "The owner denied this in the agent's chat. Don't ask for it again in this run; "
            "finish and say in your reply what is still needed.",
    "timeout": "No answer from the owner within %d h of waiting, so this was denied. Don't ask again "
               "in this run; finish and say in your reply what is still needed." % (ASK_WAIT_S // 3600),
}
# After a run, the agent stays "working" while SLURM jobs it submitted, or the agent's jobs
# (slurm.job_dirs: its folder plus the folders in its job_dirs.txt), are in the queue (st["job_wait"]);
# when they have all left, the agent is messaged to check the results. server.py's housekeeping
# loop calls check_job_waits(); at most MAX_AUTO automatic
# messages in a row (a comment from the owner resets the count), so a run that keeps resubmitting
# can't loop.
MAX_AUTO = 5
# Schedules: messages the owner set (panel: Schedule…) to be sent to this agent at a clock time
# (st["schedules"]: a list of {"id", "kind", "time": "HH:MM", "date": "YYYY-MM-DD" (once),
# "days": [0-6, Monday 0] (weekly), "text", "selection"? (once), "session": "fresh"|"continue",
# "next": epoch, "paused"?}). kind: once (removed once sent), daily, weekly, hourly (at that minute
# of every hour). Times are the server's local time and next runs come from the calendar, so 15:00
# stays 15:00 across a daylight-saving change. server.py calls check_schedules() every minute; one
# that comes due while the agent is busy (or, for a fresh session, waiting on SLURM jobs) goes once
# it is free, and a server that was down sends a missed run once, not once per miss. A "fresh" run
# starts a new session that reads index.html first; "continue" goes into the current chat like Send.
# They replaced Repeat (st["repeat"]) and Send later (st["later"]) on 2026-10-24: migrate_schedules().
SCHEDULE_KINDS = ("once", "daily", "weekly", "hourly")
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
REPEATS = {"hour": "hourly", "day": "daily", "week": "weekly"}   # the New agent form's Repeat choices
SCHEDULED_PROMPT = (
    "(Scheduled run (%s), set by the owner. This is a fresh session with no earlier conversation: before "
    "acting, read this folder's index.html (its summary card first) for the agent's current state, including "
    "what earlier runs found. index.html is the only memory between runs, so record this run's result in it "
    "with the date and time, next to the earlier runs' results rather than over them, so the next run can "
    "compare.)\n\n")
# Thread entries older than this are dropped (housekeeping, prune_threads()): index.html itself is the
# record, and an hourly repeat would otherwise grow agents.json without end. The last KEEP_LAST
# entries stay whatever their age (a New chat quotes them).
THREAD_KEEP_S = 7 * 86400
KEEP_LAST = 6
# Messages the owner sends while the agent is busy (working or queued) wait in its inbox, st["inbox"]
# ([{"id", "time", "text", "selection"?}], oldest first; shown in the panel, editable until sent), and go
# as the next message when the run ends with a reply: one as it is, several as one numbered message
# (one run). After a run that was cancelled, failed or timed out, or that a server restart cut off, they
# stay until the owner presses Send now (or removes them). Scheduled messages keep their own wait.
INBOX_MAX = 20


def busy(st):
    """True while a run is going or queued; waiting on SLURM jobs doesn't block a new comment."""
    return st.get("status") in ("working", "queued") and not st.get("job_wait")


def is_compact(prompt):
    return prompt == COMPACT or prompt.startswith(COMPACT + " ")


def kilo(n):
    return "?" if n is None else "%dK" % round(n / 1000.0)


def clock(t):
    return time.strftime("%H:%M" if t - time.time() < 20 * 3600 else "%b %d %H:%M", time.localtime(t))


def when(t, zone=False):
    """A schedule's run time for the panel, in the server's time zone: "Fri Oct 30 15:00" (+ " EDT")."""
    return time.strftime("%a %b %d %H:%M" + (" %Z" if zone else ""), time.localtime(t))


def _at(day, hm):
    """Epoch of local date day at "HH:MM" (mktime picks that day's daylight-saving offset)."""
    h, m = map(int, hm.split(":"))
    return time.mktime((day.year, day.month, day.day, h, m, 0, 0, 0, -1))


def next_run(s, after):
    """The first time after `after` (epoch) that schedule s runs; None for a once in the past."""
    if s["kind"] == "once":
        t = _at(datetime.datetime.strptime(s["date"], "%Y-%m-%d").date(), s["time"])
        return t if t > after else None
    if s["kind"] == "hourly":
        lt = time.localtime(after)
        t = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, lt.tm_hour, int(s["time"][3:]), 0, 0, 0, -1))
        while t <= after:
            t += 3600
        return t
    day = datetime.date.fromtimestamp(after)
    for i in range(8):
        d = day + datetime.timedelta(days=i)
        if s["kind"] == "daily" or d.weekday() in s["days"]:
            t = _at(d, s["time"])
            if t > after:
                return t
    return None


def clean_schedule(spec):
    """(schedule without id, None) from the panel's fields, or (None, why not). Text isn't checked."""
    kind = spec.get("kind")
    if kind not in SCHEDULE_KINDS:
        return None, "Pick once, daily, weekly or every hour."
    try:
        h, m = map(int, str(spec.get("time") or "").split(":"))
    except ValueError:
        h = m = -1
    if not (0 <= h < 24 and 0 <= m < 60):
        return None, "Give a time as HH:MM."
    s = {"kind": kind, "time": "%02d:%02d" % (h, m), "text": str(spec.get("text") or "").strip(),
         "session": "continue" if spec.get("session") == "continue" else "fresh"}
    if kind == "once":
        try:
            datetime.datetime.strptime(str(spec.get("date")), "%Y-%m-%d")
        except ValueError:
            return None, "Give a date."
        s["date"] = str(spec["date"])
    if kind == "weekly":
        days = sorted({d for d in spec.get("days") or [] if isinstance(d, int) and 0 <= d < 7})
        if not days:
            return None, "Pick at least one day."
        s["days"] = days
    s["next"] = next_run(s, time.time())
    if s["next"] is None:
        return None, "That time has passed."
    return s, None


def preview_schedule(spec):
    """(None, its next two run times as text) for the panel's editor, or (why not, [])."""
    s, why = clean_schedule(spec)
    if why:
        return why, []
    runs = [s["next"]] if s["kind"] == "once" else [s["next"], next_run(s, s["next"])]
    return None, [when(t, zone=True) for t in runs]


def schedule_label(s):
    """How a schedule repeats: "once", "daily 08:00", "weekly Mon, Fri 15:00", "every hour at :15"."""
    if s["kind"] == "daily":
        return "daily " + s["time"]
    if s["kind"] == "weekly":
        return "weekly %s %s" % (", ".join(DAYS[d] for d in s["days"]), s["time"])
    if s["kind"] == "hourly":
        return "every hour at :" + s["time"][3:]
    return "once"


def migrate_schedules(st):
    """An agent's Repeat and Send later messages (before 2026-10-24) become schedules, keeping their
    next times (one already past goes on the next pass)."""
    rep, later = st.pop("repeat", None), st.pop("later", None) or []
    out = st.get("schedules", [])
    if rep and rep.get("every") in REPEATS:
        lt = time.localtime(rep["next"])
        s = {"id": secrets.token_hex(4), "kind": REPEATS[rep["every"]], "time": time.strftime("%H:%M", lt),
             "text": rep["text"], "session": "fresh", "next": rep["next"]}
        if s["kind"] == "weekly":
            s["days"] = [lt.tm_wday]
        out.append(s)
    for m in later:
        lt = time.localtime(m["at"])
        out.append(dict({"id": m["id"], "kind": "once", "date": time.strftime("%Y-%m-%d", lt),
                         "time": time.strftime("%H:%M", lt), "text": m["text"], "session": "continue",
                         "next": m["at"]}, **({"selection": m["selection"]} if m.get("selection") else {})))
    if out:
        st["schedules"] = out


def soonest(st):
    """The agent's next scheduled run (epoch; paused ones don't count), or None."""
    runs = [s["next"] for s in st.get("schedules", []) if not s.get("paused")]
    return min(runs) if runs else None


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def system_entry(text):
    """A thread entry from the server (not the owner or the agent)."""
    return {"role": "system", "time": now(), "text": text}


def note(st, text):
    st["thread"].append(system_entry(text))


def login_key():
    """The owner's secret, created on first use (0600)."""
    if not os.path.exists(KEY_FILE):
        os.makedirs(os.path.dirname(KEY_FILE), mode=0o700, exist_ok=True)
        fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_urlsafe(24) + "\n")
    with open(KEY_FILE) as f:
        return f.read().strip()


def load_text(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def model_env(model):
    """Environment that points claude at the server for a non-Claude model ({} for Claude's own).
    OSError if the GenAI Studio key file is missing, so the run fails saying so."""
    if model in LOCAL_MODELS:
        return LOCAL_ENV
    if model in GENAI_MODELS:
        key = load_text(GENAI_KEY_FILE).strip()
        if not key:
            raise OSError("no GenAI Studio API key in %s (make one at genai.rcac.purdue.edu, "
                          "Settings > Account > API Keys)" % GENAI_KEY_FILE)
        relay = genai_relay.shared(GENAI_URL, lambda: load_text(GENAI_KEY_FILE).strip())
        return dict(LOCAL_ENV, ANTHROPIC_BASE_URL=relay.url, ANTHROPIC_AUTH_TOKEN=relay.token,
                    CLAUDE_CODE_MAX_CONTEXT_TOKENS=str(GENAI_MODELS[model]))
    return {}


_available = [0, None]     # [checked at, models]
_available_lock = threading.Lock()


def available_models():
    """The models an agent can run on here: Claude's (DirAI needs Claude Code anyway), the local
    ones Ollama has at OLLAMA_URL (none if it isn't running), and GenAI Studio's if there is a key.
    Cached for MODEL_CHECK_S."""
    with _available_lock:
        if _available[1] is None or time.time() - _available[0] > MODEL_CHECK_S:
            try:
                with urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=2) as r:
                    names = {m["name"] for m in json.loads(r.read().decode()).get("models", [])}
            except (OSError, ValueError, KeyError, TypeError):
                names = set()
            local = [m for m in LOCAL_MODELS if m in names or m + ":latest" in names]
            genai = list(GENAI_MODELS) if load_text(GENAI_KEY_FILE).strip() else []
            _available[:] = [time.time(), [m for m in MODELS if m not in NON_CLAUDE] + local + genai]
        return _available[1]


def end_asks(st):
    """The run is over: its unanswered prompts can't be answered any more."""
    for e in st.get("thread", []):
        if e.get("role") == "ask" and not e.get("answer"):
            e["answer"] = "ended"
    st.pop("asking", None)


def save_json(path, data):
    dirai_config.save_json(path, data, indent=1, ensure_ascii=False)


# Claude Code's login expired (claude_run.auth_error): the message goes back to the front of the queue
# and Claude runs wait (hold_reason LOGIN_REASON) until the login works again. Every LOGIN_RECHECK_S
# the stored login is compared with the one that failed (login_signature()); once it changed and
# `claude auth status` says logged in, the held messages are sent (a failure holds them again).
# start_login() (`claude auth login` over pipes) and retry_login() are for a Log in / Retry on the agent list.
LOGIN_REASON = "Claude login expired"
LOGIN_RECHECK_S = 30
# Claude refused for its usage limit (hold_reason LIMIT_REASON): the stated reset time holds the queue, but
# the limit may end sooner (reset by Anthropic, another account). LIMIT_FIRST_RECHECK_S after the refusal
# (past the 60 s usage cache), then every LIMIT_RECHECK_S, a usage reading taken after the refusal with the
# session and weekly windows below 100% ends the hold (limit_lifted). After such a release the next one
# waits LIMIT_RECHECK_S, so a limit the endpoint doesn't show costs at most one refused run per LIMIT_RECHECK_S.
LIMIT_REASON = "Claude usage limit hit"
LIMIT_FIRST_RECHECK_S = 65
LIMIT_RECHECK_S = 300
LOGIN_HELP = ("Claude login expired on {host}. To log in again, press Log in in the red box below, or in a "
              "terminal on {host}: run `claude`, then type /login (or run `claude auth login`).\n"
              "Your message is kept and is sent again when the login works.\n(Claude Code said: {text})")


def limit_lifted(u, since):
    """True if usage reading u (claude_usage.usage()) was taken after since, has no error, isn't stale,
    and shows the session window, and the weekly one if given, below 100%."""
    if u.get("error") or u.get("stale") or (u.get("checked") or 0) <= since or not u.get("session"):
        return False
    return all(w["percent"] < 100 for w in (u.get("session"), u.get("weekly")) if w)


def login_signature():
    """A digest of Claude Code's stored login (credentials file or macOS Keychain item, and
    CLAUDE_CODE_OAUTH_TOKEN), to see that it changed; None if there is none."""
    try:
        c = claude_usage._credentials().get("claudeAiOauth") or {}
        parts = [c.get("accessToken"), c.get("refreshToken")]
    except Exception:       # no file, no Keychain item, bad JSON
        parts = []
    parts.append(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"))
    if not any(parts):
        return None
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()


def auth_status():
    """`claude auth status --json` (no tokens used): {"loggedIn", "configDirectory", ...}, or {}
    if it can't be run or read (an older claude)."""
    try:
        p = subprocess.run([CLAUDE_CMD, "auth", "status", "--json"], stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, env=claude_env(), timeout=30)
        return json.loads(p.stdout.decode())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}


def claude_env(**extra):
    """The server's environment with ~/.local/bin on PATH, as runs get it."""
    path = os.environ.get("PATH", "")
    if USER_BIN not in path.split(os.pathsep):
        path = USER_BIN + os.pathsep + path
    return dict(os.environ, PATH=path, **extra)


GIT_MISSING = ("git not found: agents run without git (no commit/push, no DirAI pull). "
               "Install it: sudo apt-get install -y git")


def in_git(path):
    if not shutil.which("git"):     # no git, no repo: run without the git section of the prompt
        return False
    return subprocess.run(["git", "-C", path, "rev-parse", "--is-inside-work-tree"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


ALL = object()      # Agents._edit(): the whole state, not one agent


class Agents:
    def __init__(self, root):
        self.root = root
        self.config = dirai_config.tree_config(root)
        self.path = os.path.join(root, "www", "agents.json")
        self._migrate()
        self.lock = threading.Lock()
        self.running = 0
        self.queue = []
        self.genai_agent = None  # the agent running on a GenAI Studio model (one at a time)
        self.genai_claim = None  # its genai_relay.claim(), so other trees' servers wait for it
        self.genai_timer = None
        self.procs = {}         # agent -> its running claude process (for Cancel)
        self.live = {}          # agent -> its run's LiveRun (stdin, prompts waiting for the owner)
        self.cancelled = set()  # agents whose run the owner cancelled
        self.hold_until = 0     # no Claude run starts before this (usage limit, login)
        self.hold_reason = ""
        self.limit_hit_at = 0       # when Claude last refused for its usage limit (readings before don't count)
        self.limit_released_at = 0  # when a usage reading last ended such a hold early
        self.codex_hold_until = 0  # no Codex run starts before this (Codex refused for its limit)
        self.codex_hold_reason = ""
        self.engine_seen = None     # the machine's engine at the last queue check (another tree's server may switch it)
        self.login = None       # while held for an expired login: {"since", "text", "sig", "host", "config_dir"}
        self.login_proc = None  # the agent list's Log in: a claude_run.Login
        self.timer = None
        self.cards = {}         # index.html path -> (mtime, its summary card's problems)
        self.summaries = {}     # index.html path -> (mtime, its summary card's fields, for the Tree tab's hover)
        self.git_warned = set()  # agents told GIT_MISSING since this server started
        if not shutil.which("git"):
            print("WARNING " + GIT_MISSING, flush=True)
        with self._edit() as data:
            for agent, st in data.items():           # runs don't survive a restart
                if "watch" in st:                    # its name before 2026-10
                    st["job_wait"] = st.pop("watch")
                migrate_schedules(st)
                end_asks(st)
                if st.get("status") == "queued" and st.get("pending"):   # queued ones do
                    self.queue.append((agent, st["pending"]))
                    if (st.get("queued_reason") or "").startswith("Codex"):
                        if (st.get("queued_until") or 0) > self.codex_hold_until:
                            self.codex_hold_until, self.codex_hold_reason = st["queued_until"], st["queued_reason"]
                    elif (st.get("queued_until") or 0) > self.hold_until:
                        self.hold_until, self.hold_reason = st["queued_until"], st.get("queued_reason", "")
                        self.limit_hit_at = time.time()
                elif st.get("status") == "working" and not st.get("job_wait"):   # job waits resume
                    st["status"] = "unread"
                    note(st, "The server restarted while this was running; "
                             "the run was lost. Comment again to retry.")
        if self.queue:
            self._start_queued()

    # --- state ------------------------------------------------------------------------
    def _migrate(self):
        """Files of a tree served before 2026-10, renamed: reviews.json and page_prev/."""
        www = os.path.dirname(self.path)
        for old, new in (("reviews.json", "agents.json"), ("page_prev", "before_run")):
            if os.path.exists(os.path.join(www, old)) and not os.path.exists(os.path.join(www, new)):
                os.replace(os.path.join(www, old), os.path.join(www, new))

    def _load(self):
        return load_json(self.path, {})

    def _save(self, data):
        save_json(self.path, data)

    def before_run_path(self, agent):
        """The agent's index.html as it was before the latest run that changed it (the panel
        highlights what differs from it)."""
        name = agent.replace("/", "%2F") if agent else "%top"
        return os.path.join(self.root, "www", "before_run", name + ".html")

    @staticmethod
    def _blank():
        return {"status": "read", "thread": [], "session_id": None, "denials": [], "grants": []}

    def _agent(self, data, agent):
        return data.setdefault(agent, self._blank())

    @contextlib.contextmanager
    def _edit(self, agent=ALL):
        """Lock the state and yield it for changing: one agent's entry (created if missing) or, with
        no agent, all of it ({agent: entry}). Saved when the block ends, if anything changed (a block
        that returns early without changing anything writes nothing); an exception discards it."""
        with self.lock:
            with self._changes(agent) as st:
                yield st

    @contextlib.contextmanager
    def _changes(self, agent=ALL):
        """_edit for a caller that already holds the lock."""
        data = self._load()
        before = json.dumps(data, sort_keys=True)
        if agent is ALL:
            yield data
        else:
            new = agent not in data
            yield self._agent(data, agent)
            if new and data[agent] == self._blank():
                del data[agent]      # only looked at
        if json.dumps(data, sort_keys=True) != before:
            self._save(data)

    def all_status(self):
        with self.lock:
            data = self._load()
        return {p: {"status": s["status"], "updated": (s["thread"][-1]["time"] if s["thread"] else ""),
                    "context": context_tokens(s.get("session_id")),
                    "schedule": soonest(s) and time.strftime("%a %H:%M", time.localtime(soonest(s))),
                    "schedules": len(s.get("schedules", [])), "asking": bool(s.get("asking")),
                    "denied": len(s.get("denials", [])), "inbox": len(s.get("inbox", [])),
                    "requests": s.get("drafts", 0),
                    "card": len(self.card_problems(p))}
                for p, s in data.items()}

    def card_problems(self, agent):
        """dirai_card.problems() of the agent's summary card, cached until index.html changes."""
        path = os.path.join(self.root, agent, "index.html")
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return []
        hit = self.cards.get(path)
        if not hit or hit[0] != mtime:
            hit = self.cards[path] = (mtime, dirai_card.problems(path))
        return hit[1]

    def card_fields(self, agent):
        """dirai_card.extract() of the agent's summary card ({} if it has none), cached until index.html changes."""
        path = os.path.join(self.root, agent, "index.html")
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return {}
        hit = self.summaries.get(path)
        if not hit or hit[0] != mtime:
            hit = self.summaries[path] = (mtime, dirai_card.extract(path) or {})
        return hit[1]

    def permissions(self):
        """The tree's permission mode for new runs (dirai.json, so a hand edit counts too)."""
        mode = dirai_config.tree_config(self.root).get("permissions")
        return mode if mode in PERMISSION_MODES else PERMISSION_MODES[0]

    def set_permissions(self, mode):
        if mode not in PERMISSION_MODES:
            return False
        dirai_config.set_tree_option(self.root, "permissions", mode)
        return True

    def state(self, agent):
        available = available_models()     # may ask Ollama, so outside the lock
        login = self.login_state()          # takes the lock itself
        with self.lock:
            st = self._load().get(agent) or {"status": "none", "thread": [], "denials": [], "grants": []}
            st = dict(st)
            st["login"] = login             # the panel's Log in / Retry box while Claude runs are held for it
            granted = DEFAULT_ALLOW + self.config["allow"] + self._grants(self._load(), agent, st)
            # "granted": the rule is already allowed yet was refused anyway (built-in safety check,
            # e.g. ".." in a path), so another grant can't help
            st["context"] = context_tokens(st.get("session_id"))
            st["context_warn"], st["context_high"] = CONTEXT_WARN, CONTEXT_HIGH
            st["auto_compact"] = self._compact_limit(st)
            st["auto_compact_choices"] = AUTO_COMPACT_CHOICES
            st["model"] = st.get("model") or DEFAULT_MODEL
            # the agent's own model stays in the list even if it's gone (Ollama stopped)
            st["models"] = [m for m in MODELS if m in available or m == st["model"]]
            st["model_labels"] = MODEL_LABELS
            st["permissions"] = self.permissions()
            st["engine"] = codex_engine.engine()    # this machine's: the panel says which one runs the agent
            st["watching"] = (st.get("job_wait") or {}).get("jobs", [])
            st["card"] = self.card_problems(agent)
            st["colleagues"] = colleagues.info(self.root, st.get("colleagues", []), st.get("coll_mode"))
            # this agent's schedules, soonest first, with their times as the server's clock reads them
            st["schedules"] = [dict(s, when=when(s["next"]), label=schedule_label(s))
                               for s in sorted(st.get("schedules", []), key=lambda s: s["next"])]
            st["now"], st["tz"] = time.strftime("%Y-%m-%d %H:%M"), time.strftime("%Z")
            # its own grants, for the Permissions list in its summary card (not the defaults, nor colleagues');
            # unusable: why no later command can match it (a line of an inline script), for its × to remove it
            st["grant_info"] = [{"rule": r, "denied": always_denied(r), "unusable": unusable(r)}
                                for r in st.get("grants", [])]
            denials = []
            for d in st.get("denials", []):
                rules = denial_rules(d)
                # keep: what Always allow keeps (the rest is allowed for the retry only)
                denials.append({"text": describe_denial(d), "rules": rules, "keep": keepable(rules),
                                "blocked": any(always_denied(r) for r in rules),
                                "granted": covered(granted, d)})
            st["denials"] = denials
        st["notes"] = sticky.load(os.path.join(self.root, agent))   # its sticky notes (notes.py), outside the lock
        # its drafts' agents: who else has requests open there, shown before you send (R12, proposal 77)
        st["request_info"] = {to: sorted({y["from"] for y in sticky.load(os.path.join(self.root, to))
                                          if y.get("from") and y["from"] != agent and y.get("state") in ("open", "sent")})
                              for to in {x["to"] for x in st["notes"] if x.get("to") and x.get("state") == "draft"}}
        return st

    def working(self, agent):
        """(what, started, until) if Claude is working on the agent or it is queued, else None.
        started is None while waiting; until is when a usage-limit wait ends (or None)."""
        with self.lock:
            st = self._load().get(agent)
            if not st or st.get("status") not in ("working", "queued"):
                return None
            until = st.get("queued_until") if st["status"] == "queued" else None
            return st.get("working_on") or "", st.get("started"), until, st.get("queued_reason") or ""

    def set_model(self, agent, model):
        """The model for this agent's next runs (the session continues; only the model changes)."""
        if model not in available_models():
            return False
        with self._edit(agent) as st:
            st["model"] = model
        if model in NON_CLAUDE:
            self._start_queued()    # an agent queued for the Claude limits can start now
        return True

    def set_schedule(self, agent, spec, selection=None):
        """Add a schedule from the panel's fields (clean_schedule), or replace the one with spec["id"].
        selection: text the owner selected, kept for a once only. None if done, else why not."""
        s, why = clean_schedule(spec)
        if why:
            return why
        if not s["text"]:
            return "Write the message to send."
        with self._edit(agent) as st:
            lst = st.setdefault("schedules", [])
            old = next((x for x in lst if x["id"] == spec.get("id")), None) if spec.get("id") else None
            if spec.get("id") and old is None:
                return "That schedule is gone (sent or deleted)."
            selection = selection or (old or {}).get("selection")
            if selection and s["kind"] == "once":
                s["selection"] = selection
            if old:
                s["id"] = old["id"]
                lst[lst.index(old)] = s
            else:
                s["id"] = secrets.token_hex(4)
                lst.append(s)
            note(st, "Scheduled (%s), next %s:\n%s" % (schedule_label(s), when(s["next"]), s["text"]))
        return None

    def change_schedule(self, agent, sid, op):
        """op: "delete", "pause" or "resume" (from now: a repeating one's next run is recomputed).
        False if there is no such schedule or op."""
        if op not in ("delete", "pause", "resume"):
            return False
        with self._edit(agent) as st:
            lst = st.get("schedules", [])
            s = next((x for x in lst if x["id"] == sid), None)
            if s is None:
                return False
            if op == "delete":
                lst.remove(s)
                note(st, "Schedule deleted (%s):\n%s" % (schedule_label(s), s["text"]))
            elif op == "pause":
                s["paused"] = True
                note(st, "Schedule paused (%s):\n%s" % (schedule_label(s), s["text"]))
            else:
                s.pop("paused", None)
                if s["kind"] != "once":
                    s["next"] = next_run(s, time.time())
                note(st, "Schedule resumed (%s), next %s:\n%s" % (schedule_label(s), when(s["next"]), s["text"]))
            return True

    def check_schedules(self):
        """Send each agent's scheduled message that has come due (its earliest one), if the agent is free."""
        t = time.time()
        with self.lock:
            due = []
            for p, st in self._load().items():
                ready = [s for s in st.get("schedules", []) if not s.get("paused") and s["next"] <= t
                         and not busy(st) and not (s["session"] == "fresh" and st.get("job_wait"))]
                if ready:
                    due.append((p, min(ready, key=lambda s: s["next"])))
        for agent, s in due:
            with self._edit(agent) as st:     # move it on first, so it is sent once
                lst = st.get("schedules", [])
                if s not in lst:
                    continue                  # changed meanwhile
                if s["kind"] == "once":
                    lst.remove(s)
                else:
                    lst[lst.index(s)] = dict(s, next=next_run(s, t))   # a missed run goes once, not once per miss
            label = "%s%s" % (schedule_label(s) if s["kind"] != "once" else "set for " + when(s["next"]),
                              " · fresh chat" if s["session"] == "fresh" else "")
            if self.comment(agent, s["text"], selection=s.get("selection"), scheduled=label,
                            fresh=s["session"] == "fresh"):
                continue
            with self._edit(agent) as st:     # became busy meanwhile, or its selection's file is gone
                lst = st.setdefault("schedules", [])
                if not busy(st):
                    note(st, "Couldn't send the message scheduled for %s (its selected file is gone):\n%s"
                         % (when(s["next"]), s["text"]))
                elif s["kind"] == "once":
                    lst.append(s)
                else:
                    for i, x in enumerate(lst):
                        if x["id"] == s["id"]:
                            lst[i] = dict(x, next=s["next"])   # try again next pass

    def prune_threads(self):
        """Drop thread entries older than THREAD_KEEP_S, keeping each agent's last KEEP_LAST."""
        cutoff = datetime.datetime.fromtimestamp(time.time() - THREAD_KEEP_S).strftime("%Y-%m-%d %H:%M:%S")
        with self._edit() as data:
            for st in data.values():
                th = st.get("thread", [])
                st["thread"] = [m for m in th[:-KEEP_LAST] if m.get("time", "") >= cutoff] + th[-KEEP_LAST:]

    def set_status(self, agent, status):
        with self._edit(agent) as st:
            if st["status"] in ("working", "queued"):
                return False
            st["status"] = status
            return True

    def cancel(self, agent):
        """Stop the agent's run, or drop its message from the queue, or stop waiting on its SLURM
        jobs (the jobs themselves keep running). The session is kept, so the next message
        continues it, with whatever model is picked by then."""
        with self._edit(agent) as st:
            if st["status"] not in ("working", "queued"):
                return False
            queued = [i for i in self.queue if i[0] == agent]
            if queued or st.get("job_wait") or st["status"] == "queued":
                for item in queued:
                    self.queue.remove(item)
                for k in ("job_wait", "queued_until", "pending", "queued_reason"):
                    st.pop(k, None)
                st["status"] = "unread"
                note(st, "Cancelled by the owner.")
                return True
            # running (or about to start): _run sees the flag, stops the process and records it
            self.cancelled.add(agent)
            p = self.procs.get(agent)
        if p:
            stop_process(p)
        return True

    def stop_all(self):
        """Server shutting down: stop every run and the commands it started. Each run has its
        own process group, so nothing else would stop it, and its reply would be lost anyway
        (the next server marks the run lost)."""
        with self.lock:
            procs = list(self.procs.values())
        for sig, wait in ((signal.SIGTERM, 5), (signal.SIGKILL, 0)):
            for p in procs:
                signal_group(p, sig)
            end = time.time() + wait
            while time.time() < end and any(p.poll() is None for p in procs):
                time.sleep(0.2)

    # --- running Claude ---------------------------------------------------------------
    def new_agent(self, agent, task, every="off"):
        """Create ROOT/agent/ with a starter index.html if it has none, then start the agent there
        on task (and repeat it every hour/day/week if asked). False if that agent is already
        working."""
        full = os.path.join(self.root, agent)
        os.makedirs(full, exist_ok=True)
        index = os.path.join(full, "index.html")
        created = not os.path.exists(index)
        if created:
            title = html.escape(os.path.basename(agent) or agent, quote=False)
            with open(index, "w", encoding="utf-8") as f:
                f.write(STARTER_INDEX.format(title=title, task=html.escape(task, quote=False), date=now()[:10]))
        prompt = task
        if created:
            prompt = ("This folder and its index.html were just created for this task (index.html is a "
                      "placeholder). Do the task, and turn index.html into the report of it.\n\n"
                      "Task: " + task)
        if not self.comment(agent, task, prompt):
            return False
        if every in REPEATS:     # again from the next hour / day / week, at this time
            t = time.localtime()
            self.set_schedule(agent, {"kind": REPEATS[every], "time": time.strftime("%H:%M", t),
                                      "days": [t.tm_wday], "text": task, "session": "fresh"})
        return True

    def after_run_path(self, agent):
        """The agent's index.html as its latest run that changed it left it (page_undo.py)."""
        return os.path.join(self.root, "www", "after_run", os.path.basename(self.before_run_path(agent)))

    def undo(self, agent, block):
        """Undo block number block of the latest run's changes to index.html, or redo it if it is
        undone (page_undo.py). None if done, else why not."""
        with self._edit(agent) as st:
            if busy(st):
                return "The agent is working; try again when it is done."
            os.makedirs(os.path.dirname(self.after_run_path(agent)), exist_ok=True)
            undone = page_undo.toggle(os.path.join(self.root, agent, "index.html"), self.before_run_path(agent),
                                      self.after_run_path(agent), st.get("undone", []), block)
            if isinstance(undone, str):
                return undone
            redo = len(undone) < len(st.get("undone", []))
            st["undone"] = undone
            note(st, "%s change %d of the latest run in index.html." % ("Redid" if redo else "Undid", block + 1))
            st["page_note"] = ("(The owner undid or redid some of your latest changes to index.html; "
                               "re-read it before editing.)\n\n")
            return None

    def page_marks(self, agent, page):
        """page (index.html, for the owner) marked where each block of the latest run's changes
        starts, for the panel's Undo / Redo buttons (page_undo.mark)."""
        with self.lock:
            undone = (self._load().get(agent) or {}).get("undone", [])
            if not os.path.isfile(self.before_run_path(agent)):
                return page
            os.makedirs(os.path.dirname(self.after_run_path(agent)), exist_ok=True)
            st = page_undo.state(os.path.join(self.root, agent, "index.html"), self.before_run_path(agent),
                                 self.after_run_path(agent), undone)
        if st is None:
            return page
        return page_undo.mark(page.decode(**page_undo.ENC), st[2], set(undone)).encode(**page_undo.ENC)

    def new_chat(self, agent):
        """Next message starts a fresh Claude session (the thread stays, with a divider)."""
        with self._edit(agent) as st:
            if busy(st) or not (st.get("session_id") or st.get("codex_session")):
                return False
            st["session_id"], st["denials"] = None, []
            st.pop("codex_session", None)
            note(st, NEW_CHAT_MARK)
            return True

    def _compact_limit(self, st):
        """The context size (tokens) at which this agent compacts by itself; 0 = never."""
        limit = st.get("auto_compact")
        if limit is None:
            limit = self.config.get("auto_compact", AUTO_COMPACT)
        window = GENAI_MODELS.get(st.get("model") or DEFAULT_MODEL)
        if limit and window:
            limit = min(limit, int(window * AUTO_COMPACT_WINDOW))
        return limit if isinstance(limit, int) and limit > 0 else 0

    def set_auto_compact(self, agent, limit):
        """This agent's own auto compact limit (one of AUTO_COMPACT_CHOICES; 0 = off)."""
        if isinstance(limit, bool) or limit not in AUTO_COMPACT_CHOICES:
            return False
        with self._edit(agent) as st:
            st["auto_compact"] = limit
            st.pop("auto_compact_paused", None)
        return True

    def _auto_compact(self, agent, prompt):
        """A run ended with a reply: queue /compact if the context is at the limit. True if queued.
        Not after a compact, nor while SLURM jobs are awaited (compact() would drop that wait: it
        is checked again when the jobs' results have been handled)."""
        if is_compact(prompt) or codex_engine.engine() == "codex":
            return False
        with self.lock:
            st = self._load().get(agent) or {}
            model = st.get("model") or DEFAULT_MODEL
            session, limit = st.get("session_id"), self._compact_limit(st)
            if (not session or not limit or model in LOCAL_MODELS or st.get("job_wait") or busy(st)
                    or st.get("asking")):
                return False
            paused = st.get("auto_compact_paused")
        ctx = context_tokens(session)
        if ctx is None:
            return False
        if ctx < limit:
            if paused:
                with self._edit(agent) as st:
                    st.pop("auto_compact_paused", None)
            return False
        if paused:
            return False
        return self.compact(agent, "Auto compact (%s >= %s)." % (kilo(ctx), kilo(limit)))

    def _auto_compact_done(self, agent, before, after, ran=True):
        """An automatic compact ended: pause auto compact for the agent if the context didn't shrink.
        ran: False when it was cancelled or failed; that says nothing about shrinking, so no pause
        (a pause from it would never lift: the context only grows until something compacts it)."""
        with self._edit(agent) as st:
            if not st.pop("auto_compacting", None) or not ran:
                return
            if after is None or before is None or after >= before:
                st["auto_compact_paused"] = True
                note(st, "Auto compact didn't shrink the context; it stays off for this agent until the "
                         "context is below the limit again.")

    def compact(self, agent, why=None):
        """Run /compact on the agent's session (queued like a message). why: the note for an automatic one.
        Claude Code only: on Codex there is no /compact (New chat starts afresh)."""
        if codex_engine.engine() == "codex":
            return False
        with self._edit(agent) as st:
            if busy(st) or not st.get("session_id"):
                return False
            st.pop("job_wait", None)   # the run re-checks the queue when it ends
            if why:
                st["auto_compacting"] = True
                note(st, why)
            else:
                note(st, "Compact requested (context %s tokens)." % kilo(context_tokens(st["session_id"])))
            st["denials"] = []
            st["status"] = "working"
            st["working_on"], st["started"] = "Compact the conversation", None
        self._enqueue(agent, COMPACT_KEEP)
        return True

    def _selection(self, agent, selection):
        """The selection as a message carries it: with its source lines found now, cut to size. False if
        its file isn't one of the agent's (comment())."""
        md = selection.get("file")
        if md and selection.get("svg"):   # in a diagram the server put inline (svg_inline.py): its lines in x.svg
            path = agent_files.file_path(os.path.join(self.root, agent), md, any_type=True)
            if path is not None and md.lower().endswith(".svg"):
                return {"text": selection["text"][:SEL_MAX], "heading": selection.get("heading", "")[:200],
                        "lines": selection_lines(path, selection["text"]), "file": md, "svg": True}
            md = None    # not a file of its folder (e.g. ../other/x.svg): placed by its heading only
        if md:
            path = agent_files.file_path(os.path.join(self.root, agent), md)
            if path is None:
                return False
            if selection.get("rendered"):   # a rendered .md: its blocks' lines, narrowed to the text
                lines = agent_files.rendered_lines(path, selection.get("lines"), selection["text"])
            else:
                lines = agent_files.selected_lines(path, selection.get("lines"))
        else:
            lines = selection_lines(os.path.join(self.root, agent, "index.html"), selection["text"])
        return dict({"text": selection["text"][:SEL_MAX], "heading": selection.get("heading", "")[:200],
                     "lines": lines}, **({"file": md} if md else {}))

    def _notes(self, agent, ids, message):
        """The sticky notes ids (notes.py) that can go, marked sent, as (prompt quoting them with message,
        [{n, text, note}] for the thread), or (None, []) if none can."""
        taken = sticky.take(os.path.join(self.root, agent), ids)
        if not taken:
            return None, []
        sels = []
        for x in taken:     # its lines found now; a file gone since: the quote and heading alone
            if x.get("from"):       # a request from another agent (proposal 77): no place on this page
                sels.append((x["n"], None, x, []))
                continue
            sel = self._selection(agent, x) or {"text": x["text"][:SEL_MAX], "heading": x.get("heading", "")}
            sels.append((x["n"], sel, x.get("note", ""), x.get("thread") or []))
        return notes_prompt(sels, message), [dict({"n": x["n"], "text": x["text"][:300], "note": x.get("note", "")},
                                                  **({"from": x["from"]} if x.get("from") else {})) for x in taken]

    def comment(self, agent, text, prompt=None, selection=None, scheduled=None, fresh=False, queue=False,
                catch_up=False, notes=None, from_agent=None):
        """selection: {"text", "heading"} of index.html text the owner selected, quoted in the prompt,
        or {"text", "heading", "file", "lines"} of text in a file of the agent's folder (shown raw at the
        end of index.html, with its line numbers). False if file isn't one of those.
        scheduled: the schedule that sends it, when check_schedules() does (shown in the thread).
        fresh: start a fresh session, its prompt pointing at index.html instead of the thread.
        queue: if the agent is busy, keep the message in its inbox (returns "queued") instead of False.
        catch_up: a given prompt still gets the earlier thread quoted when the session is new (send_inbox).
        notes: ids of the owner's sticky notes (notes.py) that go with it, each quoted; text may then be
        empty. They are marked sent (also while queued), and back to open if it isn't sent.
        from_agent: the message comes from that agent, sent by the owner (proposal 77): a request to
        this agent, or the answers to this agent's requests; the thread shows it as from that agent."""
        raw = selection
        if selection:
            selection = self._selection(agent, selection)
            if selection is False:
                return False
        shown_notes = []
        if notes and prompt is None:   # (a given prompt has them quoted already: send_inbox)
            prompt, shown_notes = self._notes(agent, notes, selection_prompt(selection, text) if selection else text)
            if not shown_notes and not text:
                return False
        if selection:
            prompt = prompt or selection_prompt(selection, text)
        ok = self._comment(agent, text, prompt, raw, selection, scheduled, fresh, queue, catch_up, shown_notes,
                           notes if shown_notes else None, from_agent)
        if not ok and shown_notes:
            sticky.unsend(os.path.join(self.root, agent), notes)
        return ok

    def _comment(self, agent, text, prompt, raw, selection, scheduled, fresh, queue, catch_up, shown_notes, note_ids,
                 from_agent=None):
        frm = {"from": from_agent} if from_agent else {}
        if fresh:
            prompt = SCHEDULED_PROMPT % scheduled + (prompt or text)
        with self._edit(agent) as st:
            if busy(st):
                box = st.setdefault("inbox", [])
                if not queue or len(box) >= INBOX_MAX:
                    if not box:
                        st.pop("inbox")
                    return False
                # the selection as sent: its lines are found again when the message goes
                box.append(dict({"id": secrets.token_hex(4), "time": now(), "text": text}, **frm,
                                **({"selection": raw} if raw else {}),
                                **({"notes": note_ids, "shown_notes": shown_notes} if note_ids else {})))
                return "queued"
            st.pop("job_wait", None)   # the run re-checks the queue when it ends
            st["auto_runs"] = 0
            # the session of the engine that will run it (codex_engine: the machine's switch)
            skey = "codex_session" if codex_engine.engine() == "codex" else "session_id"
            if fresh and st.get(skey):
                st[skey] = None
                note(st, NEW_CHAT_MARK)
            elif not fresh and not st.get(skey) and st["thread"] and (prompt is None or selection or catch_up):
                prompt = fresh_prompt(st["thread"], prompt or text)   # New chat: catch up from index.html and the thread
            st["thread"].append(dict({"role": "user", "time": now(), "text": text}, **frm,
                                     **({"selection": selection} if selection else {}),
                                     **({"notes": shown_notes} if shown_notes else {}),
                                     **({"scheduled": scheduled} if scheduled else {})))
            agent_dir = os.path.join(self.root, agent)
            named = [r for r in path_grants(text, self.root, agent_dir)
                     if r not in st.get("grants", [])]
            if named:
                st["grants"] = sorted(set(st.get("grants", [])) | set(named))
                note(st, "Read access for this agent (named in your message): " + ", ".join(named))
            st["denials"] = []
            st["status"] = "working"   # waiting for a free slot counts as working
            st["working_on"] = (text if not from_agent else "from %s: %s" % (from_agent, text)) if text else \
                "%s%d sticky note%s" % ("from %s: " % from_agent if from_agent else "", len(shown_notes),
                                        "" if len(shown_notes) == 1 else "s")
            st["started"] = None
            page_note = st.pop("page_note", "")
        prompt = page_note + (prompt or text)
        self._enqueue(agent, prompt)
        return True

    def send_inbox(self, agent):
        """Send the agent's queued messages now: one as it is, several as one numbered message. True if
        sent; False if there are none or the agent is busy (they stay)."""
        with self._edit(agent) as st:
            box = st.get("inbox") or []
            if not box or busy(st):
                return False
            st.pop("inbox")
        if len(box) == 1:
            m = box[0]
            # its selected file may be gone since: then the text alone
            sent = self.comment(agent, m["text"], selection=m.get("selection"), notes=m.get("notes"),
                                from_agent=m.get("from")) or \
                (m.get("selection") and self.comment(agent, m["text"], notes=m.get("notes")))
        else:
            parts = []
            for i, m in enumerate(box, 1):
                sel = m.get("selection") and self._selection(agent, m["selection"])
                msg = selection_prompt(sel, m["text"]) if sel else m["text"]
                if m.get("notes"):      # its sticky notes, quoted again now (their lines may have moved)
                    msg = self._notes(agent, m["notes"], msg)[0] or msg
                parts.append("%d) %s" % (i, msg))
            shown = "\n\n".join("%d) %s" % (i, m["text"] + (" [sticky notes %s]" % ", ".join(
                str(x["n"]) for x in m["shown_notes"]) if m.get("shown_notes") else ""))
                for i, m in enumerate(box, 1))
            sent = self.comment(agent, shown, prompt=QUEUED_PROMPT % (len(box), "\n\n".join(parts)), catch_up=True)
        if not sent:        # became busy meanwhile: back in front of anything queued since
            with self._edit(agent) as st:
                st["inbox"] = box + st.get("inbox", [])
        return bool(sent)

    # --- requests between agents (proposal 77, improvement/agent-notes) ---------------------------------
    # An agent drafts (dirai_note.py ask: notes.ask); only the owner sends (send_request); the asked agent
    # answers on its copy of the note; when its run ends the answer goes back (_requests_answered) and is
    # given to the asker (_deliver): one by one, or, after Send all, together when all are in.
    def _adir(self, agent):
        return os.path.join(self.root, agent)

    def _count_drafts(self, agent, drafts=None):
        """The agent list's "N requests waiting" (all_status "requests")."""
        if drafts is None:
            drafts = [x for x in sticky.load(self._adir(agent)) if x.get("to") and x.get("state") == "draft"]
        with self._edit(agent) as st:
            if drafts:
                st["drafts"] = len(drafts)
            else:
                st.pop("drafts", None)

    def send_request(self, agent, ids, together=False):
        """The owner's Send ▸ To on the agent's drafts ids: each is copied into the asked agent's notes and
        sent to it (queued if it is busy). together (Send all, 2 or more): their answers are given to the
        agent as one message when all are in. Returns (how many went, [why each other one didn't])."""
        mine = {x["id"]: x for x in sticky.load(self._adir(agent))}
        todo = [mine[i] for i in ids if i in mine and mine[i].get("to") and mine[i].get("state") == "draft"]
        group = secrets.token_hex(3) if together and len(todo) > 1 else None
        sent, errors = 0, ["that request is gone or already sent"] if len(todo) < len(ids) else []
        for x in todo:
            to, link = x["to"], x["link"]
            if to == agent or not os.path.isfile(os.path.join(self._adir(to), "index.html")):
                errors.append("%s isn't an agent of this tree" % to)
                continue
            mark = {"group": group} if group else {}
            with self._edit(agent) as st:      # the send record (R1): only the server writes agents.json
                st.setdefault("requests", {})[link] = dict(
                    {"to": to, "time": now(), "hash": hashlib.sha256(x["note"].encode()).hexdigest()[:16]}, **mark)
            sticky.update(self._adir(agent), lambda n: n.get("to") == to and n.get("link") == link,
                          state="sent", sent=now()[:16], **mark)
            copy = sticky.receive(self._adir(to), agent, x)
            if not self.comment(to, "", notes=[copy["id"]], queue=True, from_agent=agent):   # R8: B's inbox full
                sticky.remove(self._adir(to), copy["id"])
                sticky.update(self._adir(agent), lambda n: n.get("to") == to and n.get("link") == link,
                              state="draft", sent=None, group=None)
                with self._edit(agent) as st:
                    st["requests"].pop(link, None)
                errors.append("%s has %d messages waiting already: the request stays a draft; send it later"
                              % (to, INBOX_MAX))
                continue
            sent += 1
        self._count_drafts(agent)
        return sent, errors

    def reject_request(self, agent, nid, reason=""):
        """The owner's Reject on a draft: it stays on the note, greyed, with the reason; the agent is told
        with its next message (R9). False if it isn't a draft (any more)."""
        reason = (reason or "").strip()[:500]
        x = sticky.update(self._adir(agent), lambda n: n["id"] == nid and n.get("to") and n.get("state") == "draft",
                          state="rejected", reason=reason or None)
        if x is None:
            return False
        with self._edit(agent) as st:
            st["page_note"] = st.get("page_note", "") + "(The owner rejected your request %d to %s%s; it wasn't sent.)\n\n" % (
                x["n"], x["to"], ": " + reason if reason else "")
        self._count_drafts(agent)
        return True

    def _requests_answered(self, agent, result):
        """When the agent's run ends: each request it was sent goes back to the agent that asked, onto
        that agent's entry (R5), if the owner's send record has it (R1); then it is given to the asker."""
        ids = {r["id"] for r in result or []}
        for x in [x for x in sticky.load(self._adir(agent)) if x["id"] in ids and x.get("from")]:
            asker, link = x["from"], x["link"]
            with self._edit(asker) as st:
                rec = (st.get("requests") or {}).get(link)
            if not rec or rec["to"] != agent or rec["hash"] != hashlib.sha256(x["note"].encode()).hexdigest()[:16]:
                continue
            thread = [dict(e, who=agent) if e.get("who") == "agent" else e for e in x.get("thread") or []]
            got = sticky.update(self._adir(asker), lambda n: n.get("to") == agent and n.get("link") == link,
                                state=x["state"], answer=x.get("answer") or "(no answer)", at=x.get("at"),
                                thread=thread, noanswer=True if x.get("noanswer") else None,
                                arrived=now()[:16], delivered=None)
            if got:
                self._deliver(asker, got.get("group"))

    def _deliver(self, agent, group=None, now_=False):
        """Give the agent the answers to its requests that are in and not given yet: those sent one by
        one, or those of group (Send all) once all of it is in (now_: Deliver now, what is in so far).
        One message (queued if the agent is busy). True if one went."""
        mine = [x for x in sticky.load(self._adir(agent)) if x.get("to")]
        members = [x for x in mine if x.get("group") == group] if group else []
        if group and not now_ and any(not x.get("arrived") for x in members):
            return False        # "2 of 3 in": wait for the rest
        out = [x for x in mine if x.get("arrived") and not x.get("delivered") and x.get("group") == group]
        if not out:
            return False
        parts = ["Request %d to %s: %s\n%s's answer (%s): %s%s" % (
            x["n"], x["to"], x["note"], x["to"], "no answer" if x.get("noanswer") else x["state"], x["answer"],
            " (see %s on its page, %s/index.html)" % (x["at"], x["to"]) if x.get("at") else "") for x in out]
        whom = sorted({x["to"] for x in out})
        text = ANSWERS_PROMPT % ("%s answered" % ", ".join(whom), "\n\n".join(parts))
        for x in out:
            sticky.update(self._adir(agent), lambda n, i=x["id"]: n["id"] == i, delivered=now()[:16])
        if now_:    # the rest of the group comes one by one
            for x in members:
                if not x.get("arrived"):
                    sticky.update(self._adir(agent), lambda n, i=x["id"]: n["id"] == i, group=None)
        if self.comment(agent, text, queue=True, from_agent=", ".join(whom)):
            return True
        for x in out:       # its inbox is full: given with a later answer, or by Deliver now
            sticky.update(self._adir(agent), lambda n, i=x["id"]: n["id"] == i, delivered=None)
        with self._edit(agent) as st:
            note(st, "Answers from %s are in, but %d messages already wait for this agent: they go later."
                 % (", ".join(whom), INBOX_MAX))
        return False

    def deliver_now(self, agent, group):
        """The owner's Deliver now on a Send all group: the answers in so far, the rest one by one."""
        return self._deliver(agent, group, now_=True)

    def change_inbox(self, agent, mid, text=None):
        """Change one queued message's text, or remove it (text None or empty). False if it is gone (sent)."""
        with self._edit(agent) as st:
            box = st.get("inbox") or []
            m = next((x for x in box if x["id"] == mid), None)
            if m is None:
                return False
            if text:
                m["text"] = text
            else:
                box.remove(m)
                if not box:
                    st.pop("inbox")
            return True

    def dismiss_denials(self, agent):
        """Clear the refused actions without granting anything (drops the list's needs-you badge)."""
        with self._edit(agent) as st:
            if busy(st) or not st.get("denials"):
                return False
            st["denials"] = []
            return True

    def grant(self, agent, rules, always):
        rules = [r for r in rules if r and not always_denied(r)]
        if not rules:
            return False
        # Always keeps only the rules a later command may match; lines of an inline script go once
        keep = keepable(rules) if always else []
        once = [r for r in rules if r not in keep]
        with self._edit(agent) as st:
            if busy(st) or not st.get("session_id"):
                return False
            st.pop("job_wait", None)
            st["auto_runs"] = 0
            if keep:
                self._save_grants(st, keep)
            if once:
                st["once"] = sorted(set(st.get("once", [])) | set(once))
                note(st, ("Allowed once (this retry; can't recur, so not kept): " if always
                          else "Allowed once (this retry): ") + ", ".join(once))
            st["denials"] = []
            st["status"] = "working"   # waiting for a free slot counts as working
            st["working_on"], st["started"] = "Retry with granted: " + ", ".join(rules), None
        self._enqueue(agent, "The owner granted these permissions: %s. Retry what was blocked "
                            "and finish the task.%s" % (", ".join(rules),
                                                        " " + SCRIPT_HINT if any(unusable(r) for r in rules) else ""))
        return True

    def remove_grant(self, agent, rules):
        """Take rules out of the agent's grants (the × in its Permissions list), from its next run
        on (and its colleagues' next runs). Returns how many it removed."""
        with self._edit(agent) as st:
            have = st.get("grants", [])
            gone = [r for r in have if r in set(rules)]
            if gone:
                st["grants"] = [r for r in have if r not in set(gone)]
                note(st, "Permission removed: " + gone[0] if len(gone) == 1 else "Permissions removed (%d): %s%s" % (
                    len(gone), ", ".join(gone[:5]), ", …" if len(gone) > 5 else ""))
        return len(gone)

    def removal_check(self, agent):
        """(a run is going there, the agents that list it as a colleague) for Remove this copy."""
        with self.lock:
            data = self._load()
            running = (data.get(agent) or {}).get("status") in ("working", "queued")
            used = sorted(a for a, st in data.items() if a != agent and agent in (st.get("colleagues") or []))
        return running, used

    def drop(self, agent):
        """Forget a removed agent: its state, and its place in other agents' colleagues."""
        with self.lock:
            data = self._load()
            data.pop(agent, None)
            for st in data.values():
                if agent in (st.get("colleagues") or []):
                    st["colleagues"] = [c for c in st["colleagues"] if c != agent]
                    (st.get("coll_mode") or {}).pop(agent, None)
            self._save(data)

    def colleagues(self, agent):
        """The agents this one may read (colleagues.py), as paths relative to the tree."""
        with self.lock:
            return list((self._load().get(agent) or {}).get("colleagues", []))

    def add_colleague(self, agent, link):
        """Let the agent read the agent a pasted link names, from its next run on: None, or why not."""
        rel, why = colleagues.parse_link(link, self.root, agent)
        if why:
            return why
        with self._edit(agent) as st:
            if rel in st.get("colleagues", []):
                return "%s is already a colleague." % (rel or "The top agent")
            st["colleagues"] = st.get("colleagues", []) + [rel]
            note(st, "Colleague added (read-only, from the next run): " + colleagues.folder(self.root, rel))
        return None

    def remove_colleague(self, agent, rel):
        with self._edit(agent) as st:
            if rel not in st.get("colleagues", []):
                return False
            st["colleagues"] = [c for c in st["colleagues"] if c != rel]
            (st.get("coll_mode") or {}).pop(rel, None)
            if st.get("coll_mode") == {}:
                st.pop("coll_mode")
            note(st, "Colleague removed: " + colleagues.folder(self.root, rel))
        return True

    def colleague_modes(self, agent):
        """{rel: "own" | "all"} for its writable colleagues (the rest are read-only)."""
        with self.lock:
            return dict((self._load().get(agent) or {}).get("coll_mode") or {})

    def set_colleague_mode(self, agent, rel, mode):
        """What the agent may do in a colleague's folder from its next run (colleagues.MODES; the
        panel's chip sends the state info() calls next). None, or why not."""
        if mode not in colleagues.MODES:
            return "Unknown colleague state: %s" % mode
        with self._edit(agent) as st:
            if rel not in st.get("colleagues", []):
                return "%s isn't a colleague." % (rel or "The top agent")
            modes = st.setdefault("coll_mode", {})
            if modes.get(rel, "read") == mode:
                return None
            if mode == "read":
                modes.pop(rel)
            else:
                modes[rel] = mode
            if not modes:
                st.pop("coll_mode")
            note(st, "Colleague %s (from the next run): %s" % (colleagues.MODE_SAYS[mode], colleagues.folder(self.root, rel)))
        return None

    @staticmethod
    def _save_grants(st, rules):
        """Keep rules for this agent (and the agents that list it as a colleague); caller holds the lock."""
        st["grants"] = sorted(set(st.get("grants", [])) | set(rules))
        note(st, "Granted (this agent): " + ", ".join(rules))

    def _grants(self, data, agent, st):
        """The rules an agent's runs get beyond the defaults: its own grants and its colleagues'
        (their edits too for a writable colleague)."""
        rules, modes = list(st.get("grants", [])), st.get("coll_mode") or {}
        for rel in st.get("colleagues", []):
            if rel != agent:
                rules += [r for r in shared_grants(data.get(rel, {}).get("grants", []), modes.get(rel, "read"))
                          if r not in rules]
        return rules

    # --- permission prompts (ask mode) ---------------------------------------------------
    def _ask(self, agent, live, rid, req):
        """A permission prompt from the run: put it in the agent's thread for the owner. Answered
        at once when the owner chose Always allow for the same action earlier in this run, or
        when the run has used up its ASK_WAIT_S of waiting."""
        d = request_denial(req)
        rules = denial_rules(d)
        keep = keepable(rules)   # what Always allow keeps; the lines of an inline script can't recur
        with self._edit(agent) as st:
            choice = ("allow" if covered(live.granted, d)
                      else "timeout" if live.waiting() >= ASK_WAIT_S else None)
            entry = {"role": "ask", "time": now(), "id": rid, "text": describe_denial(d),
                     "detail": json.dumps(d["tool_input"], indent=1)[:4000], "rules": keep, "answer": choice}
            if len(keep) < len(rules):
                entry["once_only"] = unusable(next(r for r in rules if r not in keep))
            if d["tool_name"] == "Bash" and is_heredoc(d["tool_input"].get("command", "")):
                entry["heredoc"] = True
            st["thread"].append(entry)
            if not choice:
                live.hold(rid, req)
                st["asking"] = True
        if choice:
            self._respond(live, rid, req, choice)

    def answer(self, agent, rid, choice):
        """The owner's answer to a waiting prompt: allow, always (allow, and keep the rule like
        the Always allow button), deny; the watchdog answers timeout."""
        if choice not in ("allow", "always", "deny", "timeout"):
            return False
        with self._edit(agent) as st:
            live = self.live.get(agent)
            req = live.release(rid) if live else None
            if req is None:
                return False
            rules = []
            for e in st["thread"]:
                if e.get("role") == "ask" and e.get("id") == rid and not e.get("answer"):
                    e["answer"], rules = choice, e.get("rules", [])
            also = []
            if choice == "always":
                rules = [r for r in rules if not always_denied(r)]
                live.granted |= set(rules)
                self._save_grants(st, rules)
                # prompts already waiting for what was just granted (parallel tool calls) go too
                for other, oreq in list(live.pending.items()):
                    if covered(live.granted, request_denial(oreq)):
                        also.append((other, live.release(other)))
                for e in st["thread"]:
                    if e.get("role") == "ask" and e.get("id") in dict(also) and not e.get("answer"):
                        e["answer"] = "allow"
            st["asking"] = bool(live.pending)
        self._respond(live, rid, req, choice)
        for other, oreq in also:
            self._respond(live, other, oreq, "allow")
        return True

    def _withdraw(self, agent, live, rid):
        """claude took a prompt back (e.g. the turn was interrupted)."""
        with self._edit(agent) as st:
            if live.release(rid) is None:
                return
            for e in st["thread"]:
                if e.get("role") == "ask" and e.get("id") == rid and not e.get("answer"):
                    e["answer"] = "withdrawn"
            st["asking"] = bool(live.pending)

    @staticmethod
    def _respond(live, rid, req, choice):
        if choice in ("allow", "always"):
            r = {"behavior": "allow", "updatedInput": req.get("input") or {}}
        else:   # a refused inline script: say how to do it instead
            script = req.get("tool_name") == "Bash" and is_heredoc((req.get("input") or {}).get("command", ""))
            r = {"behavior": "deny", "message": ASK_DENIED[choice] + (" " + SCRIPT_HINT if script else "")}
        live.send({"type": "control_response",
                   "response": {"subtype": "success", "request_id": rid, "response": r}})

    def _watchdog(self, agent, live):
        """Stop a run after RUN_TIMEOUT_S of working time (waiting for answers doesn't count),
        and deny its prompts once it has waited ASK_WAIT_S in total."""
        start = time.time()
        while live.proc.poll() is None:
            time.sleep(5)
            if time.time() - start - live.waiting() > RUN_TIMEOUT_S:
                live.timed_out = True
                stop_process(live.proc)
                return
            if live.pending and live.waiting() >= ASK_WAIT_S:
                for rid in list(live.pending):
                    self.answer(agent, rid, "timeout")

    def _drive(self, agent, live, check=None):
        """Read the run's messages until its result (returned; {} if it died first), handing
        permission prompts to the owner. Closing stdin then lets claude exit.
        check(reply): after a successful result, a follow-up message to send in the same session, or
        None. At most one is sent; the run's reply stays the first result's, the follow-up's reply
        goes in "followup" (cost and denials cover both)."""
        p, err = live.proc, []
        reader = threading.Thread(target=lambda: err.append(p.stderr.read()), daemon=True)
        reader.start()
        threading.Thread(target=self._watchdog, args=(agent, live), daemon=True).start()
        out = {}
        for line in p.stdout:
            try:
                m = json.loads(line)
            except ValueError:
                continue
            kind = m.get("type")
            if kind == "control_request" and (m.get("request") or {}).get("subtype") == "can_use_tool":
                self._ask(agent, live, m.get("request_id"), m["request"])
            elif kind == "control_cancel_request":
                self._withdraw(agent, live, m.get("request_id"))
            elif kind == "assistant" and m.get("error"):   # e.g. "authentication_failed"
                live.error = m["error"]
            elif kind == "result":
                if out:     # the follow-up's result
                    out = dict(m, result=out.get("result"), followup=m.get("result") or "",
                               permission_denials=out.get("permission_denials", []) + m.get("permission_denials", []),
                               total_cost_usd=self._cost(out.get("total_cost_usd"), m.get("total_cost_usd")))
                    break
                out = m
                msg = check(m.get("result") or "") if check and not m.get("is_error") else None
                if not msg:
                    break
                live.send({"type": "user", "message": {"role": "user", "content": msg}})
        live.close()
        try:
            p.wait(timeout=60)
        except subprocess.TimeoutExpired:
            stop_process(p)
        reader.join(5)
        live.err = b"".join(e for e in err if e).decode("utf-8", "replace")
        return out

    @staticmethod
    def _cost(a, b):
        """Cost of a run and its follow-up: claude reports it per session (b >= a) or per turn."""
        if a is None or b is None:
            return a if b is None else b
        return b if b >= a else a + b

    def _enqueue(self, agent, prompt):
        with self.lock:
            self.queue.append((agent, prompt))
        self._start_queued()

    def _start_queued(self):
        # the machine's engine, set only by the owner (codex_engine); its own limits hold the queue,
        # the other engine's don't, and it never stands in for the other
        engine = codex_engine.engine()
        if engine == "codex":
            until, reason = codex_engine.pause_until() if self.queue else (0, "")
        else:
            if self.login and self.hold_until <= time.time():
                self._recheck_login()       # runs claude auth status, so outside the lock
            if self.queue and self.hold_until > time.time() and self.hold_reason.startswith(LIMIT_REASON):
                self._recheck_limit()       # may read the usage endpoint, so outside the lock
            if self.queue and self.hold_until <= time.time():
                until, reason = claude_usage.pause_until()     # network, so outside the lock (cached 60 s)
            else:
                until, reason = 0, ""
        with self.lock:
            self.engine_seen = engine
            if engine == "codex":
                if until > self.codex_hold_until:
                    self.codex_hold_until, self.codex_hold_reason = until, reason
                hold_until, hold_reason = self.codex_hold_until, self.codex_hold_reason
            else:
                if until > self.hold_until:
                    self.hold_until, self.hold_reason = until, reason
                hold_until, hold_reason = self.hold_until, self.hold_reason
            wait = hold_until - time.time()
            data = self._load()
            for item in list(self.queue):
                if self.running >= MAX_RUNNING:
                    break
                model = self._model(data, item[0])
                if engine == "codex":
                    if wait > 0:
                        continue    # every run on this machine goes to Codex: all wait for its limit
                elif wait > 0 and model not in NON_CLAUDE:
                    continue    # local and GenAI Studio agents don't use the Claude limits: they start anyway
                if engine == "claude" and model in GENAI_MODELS:
                    if self.genai_agent:
                        continue    # one at a time: it starts when the running one ends
                    self.genai_claim = genai_relay.claim()
                    if not self.genai_claim:     # another tree's agent is on GenAI Studio
                        self._recheck_genai()
                        continue
                    self.genai_agent = item[0]
                self.queue.remove(item)
                self.running += 1
                threading.Thread(target=self._run, args=item, daemon=True).start()
            if wait > 0:
                self._queue_on_hold(engine, hold_until, hold_reason)
                if self.timer:
                    self.timer.cancel()
                if engine == "claude" and hold_reason.startswith(LIMIT_REASON):
                    wait = min(wait, self._limit_recheck_in())
                self.timer = threading.Timer(wait, self._start_queued)
                self.timer.daemon = True
                self.timer.start()

    def _recheck_limit(self):
        """Held because Claude refused for its usage limit: end the hold if a usage reading taken after
        the refusal shows the limit lifted (LIMIT_REASON). The held message then confirms it."""
        if time.time() - self.limit_released_at < LIMIT_RECHECK_S:
            return
        u = claude_usage.usage()
        with self.lock:
            if (self.hold_reason.startswith(LIMIT_REASON) and self.hold_until > time.time()
                    and limit_lifted(u, self.limit_hit_at)):
                self.hold_until, self.hold_reason = 0, ""
                self.limit_released_at = time.time()

    def _limit_recheck_in(self):
        """Seconds until the next usage reading while held for a limit hit; caller holds the lock."""
        now = time.time()
        first = self.limit_hit_at + LIMIT_FIRST_RECHECK_S
        at = max(first if first > now else now + LIMIT_RECHECK_S, self.limit_released_at + LIMIT_RECHECK_S)
        return max(1, at - now)

    def _recheck_genai(self):
        """Try the queue again in GENAI_RECHECK_S (another process holds the GenAI claim, and its
        run ending doesn't tell us); caller holds the lock."""
        if not (self.genai_timer and self.genai_timer.is_alive()):
            self.genai_timer = threading.Timer(GENAI_RECHECK_S, self._start_queued)
            self.genai_timer.daemon = True
            self.genai_timer.start()

    def _genai_done(self, agent):
        """agent's run ended: free the GenAI Studio slot if it had it; caller holds the lock."""
        if self.genai_agent == agent:
            self.genai_agent = None
            self.genai_claim.close()
            self.genai_claim = None

    @staticmethod
    def _model(data, agent):
        return (data.get(agent) or {}).get("model") or DEFAULT_MODEL

    def recheck_hold(self):
        """The owner moved a usage pause level: drop a wait that came from the old level (not one
        from Claude actually refusing) and let the queue start again if usage allows."""
        with self.lock:
            if self.hold_until > time.time() and self.hold_reason.startswith("Claude usage at"):
                self.hold_until, self.hold_reason = 0, ""
            if self.codex_hold_until > time.time() and self.codex_hold_reason.startswith("Codex usage at"):
                self.codex_hold_until, self.codex_hold_reason = 0, ""
        self._start_queued()

    def engine(self):
        return codex_engine.engine()

    def set_engine(self, name):
        """The owner's switch (agent list): this machine's runs go to name from now on, held ones too.
        None if done, else why not."""
        why = codex_engine.set_engine(name, self.permissions())
        if not why:
            self._start_queued()
        return why

    def check_engine(self):
        """Housekeeping: another tree's server on this machine may have switched the engine; then let
        this queue start on the new one now rather than when its old hold ends."""
        with self.lock:
            changed = self.queue and self.engine_seen not in (None, codex_engine.engine())
        if changed:
            self._start_queued()

    def _queue_on_hold(self, engine="claude", hold_until=None, hold_reason=None):
        """Mark every queued message as waiting for the engine's usage limit; caller holds the lock.
        (On Claude, a GenAI Studio one still queued waits for the GenAI agent running, not for the limit.)"""
        hold_until = self.hold_until if hold_until is None else hold_until
        hold_reason = self.hold_reason if hold_reason is None else hold_reason
        login = self.login if engine == "claude" and hold_reason == LOGIN_REASON else None
        # held for the login, the recheck moves hold_until every LOGIN_RECHECK_S: not saved as queued_until
        until = 0 if login else hold_until
        with self._changes() as data:
            for agent, prompt in self.queue:
                if engine == "claude" and self._model(data, agent) in NON_CLAUDE:
                    continue
                st = self._agent(data, agent)
                if st["status"] != "queued":
                    note(st, LOGIN_HELP.format(host=login["host"], text=login["text"]) if login else
                             "%s. Queued: this message will be sent automatically at %s."
                             % (hold_reason or ("Codex" if engine == "codex" else "Claude") + " usage limit",
                                clock(hold_until)))
                if st["status"] != "queued" or st.get("queued_until") != until or st.get("queued_reason") != hold_reason:
                    st["status"], st["queued_until"], st["pending"] = "queued", until, prompt
                    st["queued_reason"], st["started"] = hold_reason, None

    def _command(self, agent_dir, model, grants, session, colls=(), modes=None, local=None):
        """The claude command line for a run in agent_dir: its permissions, folders, MCP servers
        and instructions. colls: its colleagues, which it may read, and edit as modes says ("own":
        not the folders of the agents inside, which --disallowedTools keeps read-only). local: the
        agent's own grants among grants (default all): only they, not colleagues', add working
        directories, so a colleague's Read(//tmp/**) doesn't make /tmp look like a place to work."""
        modes = modes or {}
        coll_dirs = [(c, colleagues.folder(self.root, c)) for c in colls]
        coll_dirs = [(c, d) for c, d in coll_dirs if os.path.isdir(d)]
        base = DEFAULT_ALLOW + self.config["allow"] + ["Edit(/%s/**)" % agent_dir]
        folders = ["Read(/%s/**)" % d for _, d in coll_dirs] + \
            ["Edit(/%s/**)" % d for c, d in coll_dirs if modes.get(c) in ("own", "all")]
        allow = base + grants + folders
        deny = list(ALWAYS_DENY)
        for c, d in coll_dirs:
            if modes.get(c) == "own":
                deny += ["Edit(/%s/**)" % n for n in colleagues.nested_agents(self.root, c, agent_dir)]
        read_dirs = [agent_dir] + self.config["read_dirs"]
        dirs = read_dirs + extra_dirs(base + (grants if local is None else local) + folders, agent_dir, read_dirs)
        mode = self.permissions()
        mcp_file = mcp_config(agent_dir, self.root)
        # stream-json both ways in both modes: the prompt goes in on stdin, and in ask mode so
        # do the owner's answers to claude's permission prompts
        cmd = [CLAUDE_CMD, "-p", "--model", model, "--input-format", "stream-json",
               "--output-format", "stream-json", "--verbose"] + (
               ["--permission-mode", "manual", "--permission-prompt-tool", "stdio"] if mode == "ask"
               else ["--permission-mode", "dontAsk"]) + [
               "--restricted", "--strict-mcp-config"] + (["--mcp-config", mcp_file] if mcp_file else []) + [
               "--tools", TOOLS, "--add-dir"] + dirs + [
               "--append-system-prompt", self._instructions(agent_dir, colls, modes, mode),
               "--allowedTools"] + allow + ["--disallowedTools"] + deny
        if model in GENAI_MODELS:
            cmd += ["--effort", "medium"]
        if session:
            cmd += ["--resume", session]
        return cmd

    def _instructions(self, agent_dir, colls, modes, mode):
        """DirAI's instructions for a run in agent_dir: Claude Code gets them as --append-system-prompt,
        Codex at the start of a new session's first message."""
        return (SYSTEM_PROMPT.format(root=self.root,
                    index_file=os.path.join(agent_dir, "index.html"), agent_dir=agent_dir, scope=agent_dir,
                    git=GIT_PROMPT.format(agent_dir=agent_dir) if in_git(agent_dir) else "",
                    approval=APPROVAL[mode], always_denied=", ".join(ALWAYS_DENY), agent_rule_path=AGENT_RULE_MD,
                    agent_rm=os.path.join(dirai_config.SCRIPTS_DIR, "agent_rm.sh"),
                    card_py=os.path.join(dirai_config.LIB_DIR, "dirai_card.py"), note_cmd=NOTE_CMD)
                + colleagues.prompt_block(self.root, list(colls), os.path.join(dirai_config.LIB_DIR, "dirai_card.py"), modes)
                + "\n\n" + load_text(AGENT_RULE_MD))

    def _codex_dirs(self, agent_dir, grants, colls, modes, local):
        """Folders besides agent_dir that a Codex run may write: the colleagues the agent may edit and
        the folders of its own Edit/Write grants (Codex's sandbox can't tell reads from writes in a rule)."""
        out = [colleagues.folder(self.root, c) for c in colls if (modes or {}).get(c) in ("own", "all")]
        for r in (grants if local is None else local):
            if r.startswith(("Edit(/", "Write(/")) and r.endswith("/**)"):
                out.append(r[r.index("(") + 2:-4])
        return [d for d in dict.fromkeys(out) if os.path.isdir(d)]

    def _codex_prompt(self, agent_dir, prompt, session, thread, colls, modes):
        """The prompt as a Codex run gets it: DirAI's instructions ahead of a new session's first message,
        and the turns it missed (run on Claude Code meanwhile) quoted."""
        if not prompt.startswith(FRESH_START):     # comment() already quoted the thread for a new session
            prompt = codex_engine.handoff_prompt(thread, prompt, "codex")
        if session:
            return prompt
        return ("Instructions for this agent (they hold for the whole conversation):\n\n"
                + self._instructions(agent_dir, colls, modes, "allowlist")
                + "\n\nYou run in Codex's sandbox: you may write only in your folder and the folders "
                  "you were granted; reads are not confined, but keep to the folders named above.\n\n"
                  "--- the owner's message ---\n" + prompt)

    def _run(self, agent, prompt):
        """One message to the agent, from its slot in the queue to its reply in the thread; then its
        inbox, if the run ended with a reply."""
        replied = False
        try:
            session, grants, model, colls, modes, local, engine, thread = self._begin(agent)
            agent_dir = os.path.join(self.root, agent)
            sent = prompt       # what the run gets; prompt itself is kept for a retry
            if engine == "codex":
                sent = self._codex_prompt(agent_dir, prompt, session, thread, colls, modes)
            elif session and not is_compact(prompt):    # back on Claude: the turns Codex ran meanwhile
                sent = codex_engine.handoff_prompt(thread, prompt, "claude")
            before = context_tokens(session) if engine == "claude" else None
            path = transcript(session) if engine == "claude" else None
            offset = os.path.getsize(path) if path and os.path.exists(path) else 0
            index, snap = os.path.join(agent_dir, "index.html"), self.before_run_path(agent) + ".run"
            os.makedirs(os.path.dirname(snap), exist_ok=True)
            try:
                shutil.copyfile(index, snap)
            except OSError:
                pass
            svg_snap = snap + ".svg"    # the diagrams it shows too: a run that only redraws one still marks it
            svg_inline.snapshot(index, agent_dir, self.root, svg_snap)
            if engine == "codex":
                entry, card_note, denials, session = self._attempt_codex(agent, sent, grants, session, agent_dir,
                                                                         snap, colls, modes, local)
            else:
                entry, card_note, denials, session = self._attempt(agent, sent, model, grants, session, agent_dir,
                                                                   snap, colls, modes, local)
            login = entry.pop("auth", False)
            submitted = entry.pop("jobs", None)
            if engine == "codex":
                until = entry.pop("limit_until", None)
            else:
                until = limit_reset(entry["text"]) if entry["role"] == "claude" and model not in NON_CLAUDE and not login else None
            held = until or login
            replied = entry["role"] == "claude" and not held    # not cancelled, failed, timed out or cut off
            if is_compact(prompt) and entry["role"] == "claude" and not held:
                after = context_tokens(session)
                entry = system_entry("Conversation compacted: %s -> %s tokens." % (
                    kilo(before), kilo(after)) if after != before else "Compact finished: " + entry["text"])
            if not held:    # the run changed index.html or a diagram: highlight against the copies from before it
                try:
                    with open(snap, "rb") as a, open(index, "rb") as b:
                        if a.read() != b.read() or svg_inline.changed(svg_snap, agent_dir):
                            os.replace(snap, self.before_run_path(agent))
                            shutil.rmtree(self.before_run_path(agent) + ".svg", ignore_errors=True)
                            if os.path.isdir(svg_snap):
                                os.replace(svg_snap, self.before_run_path(agent) + ".svg")
                            os.makedirs(os.path.dirname(self.after_run_path(agent)), exist_ok=True)
                            shutil.copyfile(index, self.after_run_path(agent))
                            with self._edit(agent) as st:   # new blocks to undo, none undone
                                st.pop("undone", None)
                except OSError:
                    pass
            if os.path.exists(snap):
                os.remove(snap)
            shutil.rmtree(svg_snap, ignore_errors=True)
            if until:
                self._retry_after_limit(agent, prompt, entry, session, until, engine)
                return
            if login:
                self._hold_for_login(agent, prompt, entry, session)
                return
            ids = [] if entry["text"] == "Cancelled by the owner." else self._jobs_to_wait_for(
                agent_dir, session, offset, submitted)
            self._finish(agent, entry, card_note, denials, session, ids, engine, sticky.prompt_notes(prompt))
            if is_compact(prompt) and not until:
                self._auto_compact_done(agent, before, context_tokens(session), replied)
        except Exception as e:      # any crash: say so in the thread, never leave the agent "working"
            replied = False
            traceback.print_exc()
            try:
                with self._edit(agent) as st:
                    note(st, "Run failed: %s: %s (details in www/serve_node.log)." % (type(e).__name__, e))
                    if st.get("status") == "working":
                        st["status"] = "unread"
            except Exception:
                traceback.print_exc()
        finally:
            with self.lock:
                self.running -= 1
                self._genai_done(agent)
                self.procs.pop(agent, None)
                self.cancelled.discard(agent)
                if self.live.pop(agent, None):
                    with self._changes() as data:
                        if agent in data:
                            end_asks(data[agent])
            self._start_queued()
            if replied:     # after the clean-up above, so it can't touch the next run's process
                if not self._auto_compact(agent, prompt):
                    self.send_inbox(agent)

    def _begin(self, agent):
        """Mark the agent working as its run starts: (session, its grants with its colleagues' and
        the once-only ones, which this run uses up; model; colleagues; their modes; its own grants
        and once-only ones, without the colleagues')."""
        with self._edit() as data:
            st = self._agent(data, agent)
            st["status"] = "working"
            st["started"] = time.time()
            if agent not in self.git_warned and not shutil.which("git"):   # once per server start
                self.git_warned.add(agent)
                st.setdefault("thread", []).append(system_entry(GIT_MISSING))
            for k in ("queued_until", "pending", "queued_reason"):
                st.pop(k, None)
            grants = self._grants(data, agent, st)
            once = st.pop("once", [])
            grants += [r for r in once if r not in grants]
            local = list(st.get("grants", [])) + [r for r in once if r not in st.get("grants", [])]
            # the machine's engine as the run starts (codex_engine: the owner's switch); each keeps its own session
            engine = codex_engine.engine()
            session = st.get("codex_session") if engine == "codex" else st.get("session_id")
            return (session, grants, st.get("model") or DEFAULT_MODEL,
                    list(st.get("colleagues", [])), dict(st.get("coll_mode") or {}), local,
                    engine, list(st.get("thread", [])))

    def _attempt_codex(self, agent, prompt, grants, session, agent_dir, snap, colls=(), modes=None, local=None):
        """Run Codex on prompt until it replies, is cancelled, times out or fails to start: (thread entry,
        summary-card note or None, denials (none: Codex's sandbox refuses inside the run), session).
        The entry carries "jobs" (ids sbatch printed) and, if Codex refused for its limit, "limit_until".
        A run that left the summary card broken gets one follow-up in the same session (CARD_FIX)."""
        index = os.path.join(agent_dir, "index.html")
        card_note = None
        add_dirs = self._codex_dirs(agent_dir, grants, colls, modes, local)
        path = os.environ.get("PATH", "")
        if USER_BIN not in path.split(os.pathsep):
            path = USER_BIN + os.pathsep + path
        env = dict(os.environ, PATH=path, DIRAI_AGENT_DIR=agent_dir)
        start = time.time()

        def one(text, sess):
            cmd = codex_engine.command(agent_dir, text, sess, add_dirs)
            p = subprocess.Popen(cmd, cwd=agent_dir, env=env, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            with self.lock:
                self.procs[agent] = p
                if agent in self.cancelled:
                    stop_process(p)
            err = []
            reader = threading.Thread(target=lambda: err.append(p.stderr.read()), daemon=True)
            reader.start()
            timer = threading.Timer(max(1, RUN_TIMEOUT_S - (time.time() - start)), stop_process, args=(p,))
            timer.daemon = True
            timer.start()
            out = codex_engine.read_events(line.decode("utf-8", "replace") for line in p.stdout)
            try:
                p.wait(timeout=60)
            except subprocess.TimeoutExpired:
                stop_process(p)
            timer.cancel()
            reader.join(5)
            with self.lock:
                self.procs.pop(agent, None)
                if agent in self.cancelled:
                    raise RunCancelled()
            if time.time() - start >= RUN_TIMEOUT_S:
                raise subprocess.TimeoutExpired(cmd, RUN_TIMEOUT_S)
            out["stderr"] = b"".join(e for e in err if e).decode("utf-8", "replace")
            return out

        try:
            out = one(prompt, session)
            session = out["session_id"] or session
            jobs = [j for c in out["commands"] for j in SUBMITTED_RE.findall(c)]
            if session:
                codex_engine.record_usage(session)
            reply = out["result"] or out["error"] or out["stderr"][-2000:] or "(no reply)"
            if out["is_error"] and out["error"]:
                until = codex_engine.limit_until(session, out["error"])
                if until:
                    entry = {"role": "claude", "time": now(), "text": "Codex: " + out["error"], "engine": "codex",
                             "model": "codex", "limit_until": until}
                    return entry, None, [], session
            elif not out["is_error"]:
                asked = {}
                fix = self._followups(index, snap, agent_dir, sticky.prompt_notes(prompt), asked)(out["result"] or "")
                if fix and session:
                    more = one(fix, session)
                    jobs += [j for c in more["commands"] for j in SUBMITTED_RE.findall(c)]
                    if asked.get("card"):
                        left = dirai_card.problems(index, now()[:10])
                        card_note = system_entry("The summary card needed fixing; " + (
                            "the agent fixed it." if not left else "it still has problems: " + "; ".join(left) + "."))
            model = (codex_engine.usage().get("model") or "codex")
            entry = {"role": "claude", "time": now(), "text": reply, "engine": "codex", "model": "codex:" + model
                     if model != "codex" else "codex", "jobs": list(dict.fromkeys(jobs))}
            if out.get("usage"):
                entry["tokens"] = out["usage"]
            return entry, card_note, [], session
        except RunCancelled:
            return system_entry("Cancelled by the owner."), None, [], session
        except subprocess.TimeoutExpired:
            return system_entry("Run timed out after %d h." % (RUN_TIMEOUT_S // 3600)), None, [], session
        except (ValueError, OSError) as e:
            return system_entry("Codex run failed: %s" % e), None, [], session

    def _attempt(self, agent, prompt, model, grants, session, agent_dir, snap, colls=(), modes=None, local=None):
        """Run claude on prompt until it replies, is cancelled, times out or fails to start:
        (thread entry, summary-card note or None, permission denials, session)."""
        index = os.path.join(agent_dir, "index.html")
        card_note = None
        try:
            cmd = self._command(agent_dir, model, grants, session, colls, modes, local)
            path = os.environ.get("PATH", "")
            if USER_BIN not in path.split(os.pathsep):
                path = USER_BIN + os.pathsep + path
            env = dict(os.environ, PATH=path, DIRAI_AGENT_DIR=agent_dir, **model_env(model))
            p = subprocess.Popen(cmd, cwd=agent_dir, env=env, stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 start_new_session=True)   # its own group, so Cancel stops its commands too
            live = LiveRun(p)
            with self.lock:
                self.procs[agent], self.live[agent] = p, live
                if agent in self.cancelled:      # cancelled before it started
                    stop_process(p)
            live.send({"type": "control_request", "request_id": "init", "request": {"subtype": "initialize"}})
            live.send({"type": "user", "message": {"role": "user", "content": prompt}})
            asked = {}
            out = self._drive(agent, live, None if is_compact(prompt) else
                              self._followups(index, snap, agent_dir, sticky.prompt_notes(prompt), asked))
            with self.lock:
                self.procs.pop(agent, None)
                if agent in self.cancelled:
                    raise RunCancelled()
            if live.timed_out:
                raise subprocess.TimeoutExpired(cmd, RUN_TIMEOUT_S)
            reply = out.get("result") or live.err[-2000:] or "(no reply)"
            entry = {"role": "claude", "time": now(), "text": reply, "model": model, "engine": "claude"}
            if model not in NON_CLAUDE and auth_error(reply, live.error):
                entry["auth"] = True        # _run holds the message for the login, not as a reply
            if "followup" in out and asked.get("card"):
                left = dirai_card.problems(index, now()[:10])
                card_note = system_entry("The summary card needed fixing; " + (
                    "the agent fixed it." if not left else "it still has problems: " + "; ".join(left) + "."))
            if out.get("total_cost_usd") is not None and model not in NON_CLAUDE:
                entry["cost"] = round(out["total_cost_usd"], 3)
            return entry, card_note, out.get("permission_denials", []), out.get("session_id") or session
        except RunCancelled:
            return system_entry("Cancelled by the owner."), None, [], session
        except subprocess.TimeoutExpired:
            return system_entry("Run timed out after %d h." % (RUN_TIMEOUT_S // 3600)), None, [], session
        except (ValueError, OSError) as e:
            return system_entry("Run failed: %s" % e), None, [], session

    def _retry_after_limit(self, agent, prompt, entry, session, until, engine="claude"):
        """Claude (or Codex) refused for the usage limit: keep the message and send it again after the
        reset, in the same session, ahead of the rest of the queue. Only that engine's runs wait."""
        retry = prompt if is_compact(prompt) or prompt.startswith(LIMIT_RETRY) else LIMIT_RETRY + prompt
        with self.lock:
            if engine == "codex":
                if until > self.codex_hold_until:
                    self.codex_hold_until, self.codex_hold_reason = until, "Codex usage limit hit (%s)" % entry["text"]
            else:
                self.limit_hit_at = time.time()
                if until > self.hold_until:
                    self.hold_until, self.hold_reason = until, "%s (%s)" % (LIMIT_REASON, entry["text"])
            self.queue.insert(0, (agent, retry))
            with self._changes(agent) as st:
                st["codex_session" if engine == "codex" else "session_id"] = session

    def _hold_for_login(self, agent, prompt, entry, session):
        """The run failed for an expired login: keep the message at the front of the queue, in the
        same session, and hold Claude runs until the login works (_recheck_login)."""
        with self.lock:
            if not self.login:
                self.login = {"since": time.time(), "text": entry["text"], "sig": login_signature(),
                              "host": machine_name(), "config_dir": None}
            self.hold_until = max(self.hold_until, time.time() + LOGIN_RECHECK_S)
            self.hold_reason = LOGIN_REASON
            self.queue.insert(0, (agent, prompt))
            with self._changes(agent) as st:
                st["session_id"] = session

    def _recheck_login(self):
        """Held for the login and the wait is over: release the queue if the stored login changed and
        claude says it is logged in, else wait LOGIN_RECHECK_S more. The held message itself then
        confirms it (a failed run costs no tokens; it just holds the queue again)."""
        login = self.login
        if not login:
            return
        sig = login_signature()
        status = auth_status() if sig != login["sig"] else {}
        with self.lock:
            if self.login is not login:
                return
            login["config_dir"] = status.get("configDirectory") or login["config_dir"]
            if sig != login["sig"] and status.get("loggedIn", True):
                self._clear_login()
            else:
                self.hold_until, self.hold_reason = time.time() + LOGIN_RECHECK_S, LOGIN_REASON

    def _clear_login(self):
        """Caller holds the lock."""
        self.login = None
        if self.hold_reason == LOGIN_REASON:
            self.hold_until, self.hold_reason = 0, ""

    def retry_login(self):
        """Retry now (agent list), or Log in succeeded: send the held messages; if the login still
        fails they are held again."""
        with self.lock:
            self._clear_login()
        self._start_queued()

    def start_login(self):
        """Log in (agent list): start `claude auth login` here, unless one is already waiting.
        Its status: {"state", "url", "message"}."""
        with self.lock:
            if not (self.login_proc and self.login_proc.running()):
                self.login_proc = Login([CLAUDE_CMD], env=claude_env(),
                                        done=lambda state: state == "ok" and self.retry_login())
            return self.login_proc.status()

    def login_code(self, code):
        """The code the sign-in page showed, for the waiting Log in; False if none waits or it is malformed."""
        with self.lock:
            lp = self.login_proc
        return bool(lp and lp.running() and lp.send_code(code))

    def cancel_login(self):
        with self.lock:
            lp, self.login_proc = self.login_proc, None
        if lp:
            lp.cancel()
        return True

    def login_state(self):
        """For /_review/usage (agent list, Machines box): None, or {"held", "since", "text", "host",
        "config_dir", "proc": the Log in's status or None}."""
        with self.lock:
            lp = self.login_proc.status() if self.login_proc else None
            if not self.login and not (lp and lp["state"] in ("starting", "waiting")):
                return None
            d = dict(self.login or {}, held=bool(self.login), proc=lp)
            d.pop("sig", None)
            return d

    def _finish(self, agent, entry, card_note, denials, session, ids, engine="claude", nums=()):
        """Put the run's reply in the thread, and wait for the SLURM jobs ids if there are any.
        nums: the sticky notes the run was sent (notes.py): the ones still unanswered are reopened, and the
        reply gets "notes_result" (the chat shows a pointer to the notes, E3a) without per-note lines."""
        replied = entry.get("role") == "claude"
        result = sticky.finish_run(os.path.join(self.root, agent), list(nums), entry.get("text") or "", replied)
        if result and replied:
            entry["notes_result"] = result
            entry["text"] = sticky.strip_reply(entry.get("text") or "", list(nums))
        # requests the run drafted (dirai_note.py ask): the reply links to them, for the owner to read and send
        drafts = [x for x in sticky.load(os.path.join(self.root, agent)) if x.get("to") and x.get("state") == "draft"]
        with self._edit(agent) as st:
            new = [x for x in drafts if x["id"] not in st.get("drafts_seen", [])]
            if new:
                entry["requests"] = [{"id": x["id"], "n": x["n"], "to": x["to"]} for x in new]
            if drafts:
                st["drafts"], st["drafts_seen"] = len(drafts), [x["id"] for x in drafts]
            else:
                st.pop("drafts", None), st.pop("drafts_seen", None)
            st["thread"].append(entry)
            if card_note:
                st["thread"].append(card_note)
            st["denials"] = denials
            st["codex_session" if engine == "codex" else "session_id"] = session
            st["status"] = "unread"
            if ids and st.get("auto_runs", 0) >= MAX_AUTO:
                note(st, "SLURM jobs %s are still queued, but the agent has already been "
                         "messaged automatically %d times in a row; not watching them. Comment "
                         "to continue." % (", ".join(ids), MAX_AUTO))
            elif ids:
                self._start_job_wait(st, ids)
        if result:      # requests from other agents in this run: back to them (proposal 77)
            self._requests_answered(agent, result)

    # --- waiting on SLURM jobs ------------------------------------------------------------
    def _followups(self, index, snap, agent_dir, nums, asked):
        """check(reply) for a run: its one follow-up in the same session, CARD_FIX and/or NOTES_FIX (sticky
        notes nums it was sent and hasn't answered yet, E2a) as one message, or None; asked records which."""
        def check(reply):
            msgs = []
            card = self._card_fix(index, snap)
            if card:
                msgs.append(card)
                asked["card"] = True
            left = sticky.unanswered(agent_dir, nums, reply)
            if left:
                msgs.append(NOTES_FIX % ("" if len(left) == 1 else "s", ", ".join(map(str, left)),
                                         "has" if len(left) == 1 else "have", NOTE_CMD))
                asked["notes"] = left
            return "\n\n".join(msgs) or None
        return check

    @staticmethod
    def _card_fix(index, snap):
        """CARD_FIX for a run that changed index.html (index vs its copy from before the run, snap)
        and left the summary card incomplete, else None."""
        try:
            with open(index, "rb") as a, open(snap, "rb") as b:
                if a.read() == b.read():
                    return None
        except OSError:
            pass    # no copy from before: a new agent
        left = dirai_card.problems(index, now()[:10])
        return CARD_FIX % "; ".join(left) if left else None

    def _jobs_to_wait_for(self, agent_dir, session, offset, submitted=None):
        """Jobs still queued that this run submitted, plus the owner's jobs in the agent's folder.
        submitted: the job ids a Codex run printed (else read from Claude's transcript)."""
        live = slurm.live_ids()
        if live is None:
            return []
        ids = [i for i in (submitted_jobs(session, offset) if submitted is None else submitted) if i in live]
        for j in slurm.agent_jobs(agent_dir, fresh=True):
            if slurm.base_id(j["id"]) not in ids:
                ids.append(slurm.base_id(j["id"]))
        return ids

    def _start_job_wait(self, st, ids):
        """Keep the agent "working" until jobs ids leave the queue; caller holds the lock."""
        st["status"], st["started"] = "working", time.time()
        st["job_wait"] = {"jobs": ids, "since": st["started"]}
        st["working_on"] = self._waiting_text(ids)
        note(st, "Waiting for SLURM jobs %s. When they have all left the queue, the agent will be "
                 "asked to check the results and update index.html." % ", ".join(ids))

    @staticmethod
    def _waiting_text(ids):
        shown = ", ".join(ids[:6]) + (" and %d more" % (len(ids) - 6) if len(ids) > 6 else "")
        return "Waiting for %d SLURM job%s (%s); the agent is messaged when they finish" % (
            len(ids), "" if len(ids) == 1 else "s", shown)

    def check_job_waits(self):
        """One pass over the agents waiting on SLURM jobs: message each agent
        whose jobs have all left the queue."""
        with self.lock:
            watched = {p: st["job_wait"]["jobs"] for p, st in self._load().items() if st.get("job_wait")}
        if not watched:
            return
        active = slurm.active_jobs()
        if active is None:
            return
        live = {slurm.base_id(j["id"]) for j in active}
        done, waiting = {}, {}
        for p, ids in watched.items():
            mine = [i for i in ids if i in live]
            for j in slurm.agent_jobs(os.path.join(self.root, p), all_jobs=active):
                if slurm.base_id(j["id"]) not in mine:
                    mine.append(slurm.base_id(j["id"]))
            (waiting if mine else done)[p] = mine or ids
        with self._edit() as data:     # keep the status bar's "Waiting for ..." line current
            for p, mine in waiting.items():
                st = data.get(p)
                if st and st.get("job_wait"):
                    st["working_on"] = self._waiting_text(mine)
        for agent, ids in done.items():
            report = slurm.job_report(ids)
            with self._edit(agent) as st:
                if not st.get("job_wait"):
                    continue
                st.pop("job_wait")
                st["auto_runs"] = st.get("auto_runs", 0) + 1
                note(st, "SLURM jobs finished:\n" + report)
                st["working_on"], st["started"] = "Check the finished SLURM jobs %s" % ", ".join(ids), None
                text = ("(Automatic message from the DirAI server, not the owner.) The SLURM jobs you were "
                        "waiting on have left the queue:\n%s\n\nCheck their output and logs, update index.html "
                        "and its summary card with the results, and reply with a short summary. If you submit new "
                        "jobs, end your reply; you will be messaged again when they finish." % report)
                prompt = text if st.get("session_id") or not st["thread"] else fresh_prompt(st["thread"], text)
            self._enqueue(agent, prompt)
