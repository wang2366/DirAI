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
import html
import json
import os
import secrets
import shutil
import signal
import subprocess
import threading
import time
import urllib.request

import agent_files
import claude_usage
import dirai_config
import dirai_card
import genai_relay
import slurm
from claude_run import (LiveRun, RunCancelled, context_tokens, limit_reset, signal_group, stop_process,
                        submitted_jobs, transcript)
from dirai_config import load_json
from agent_permissions import (ALWAYS_DENY, DEFAULT_ALLOW, always_denied, denial_rules, describe_denial,
                                extra_dirs, is_read_rule, mcp_config, path_grants, read_scope,
                                request_denial)
from agent_prompts import (APPROVAL, CARD_FIX, GIT_PROMPT, LIMIT_RETRY, NEW_CHAT_MARK, SEL_MAX,
                            STARTER_INDEX, SYSTEM_PROMPT, fresh_prompt, selection_lines, selection_prompt)

KEY_FILE = dirai_config.KEY_FILE
PERMS_FILE = dirai_config.PERMS_FILE
AGENT_RULE_MD = os.path.join(dirai_config.TOOL_DIR, "AGENT_RULE.md")   # agent conventions, appended to every run's instructions
# DIRAI_CLAUDE_CMD (or its old name REVIEW_CLAUDE_CMD): the claude to run, if not the default
CLAUDE_CMD = (os.environ.get("DIRAI_CLAUDE_CMD") or os.environ.get("REVIEW_CLAUDE_CMD")
              or os.path.expanduser("~/.local/bin/claude"))
# Background runs use --restricted: user/project/local settings files are ignored (so rules
# granted to interactive sessions never leak in) and file tools stay inside the agent's read scope
# (read_scope(): its own repo, or its own folder outside any repo) plus the tree's dirai.json
# "read_dirs", which Claude may read; edits still need an allow rule (only the agent's folder has
# one). Other folders of the tree need a grant: a path the owner names in a comment (path_grants())
# or "Allow" on a blocked read, both kept for that agent only.
TOOLS = "Bash,Read,Edit,Write,Glob,Grep,Skill,TodoWrite,NotebookEdit"
MAX_RUNNING = 5
# A resumed session resends its whole context with every request; warn (panel, list badge) when
# it is this big and offer Compact, which runs Claude Code's /compact on the session.
CONTEXT_WARN = 150000
CONTEXT_HIGH = 300000
COMPACT = "/compact"
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
#   the panel (Allow once / Always allow), which grants them for the next run.
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
# Repeat: the owner can have an agent's message sent again every hour, day or week (st["repeat"]:
# {"every", "text", "next"}). server.py calls check_repeats() every minute; a run that comes
# due while the agent is busy (or waiting on SLURM jobs) goes once it is free, and the next one
# keeps the original time of day. A server that was down sends a missed run once, not once per miss.
# Each scheduled run starts a fresh session (no earlier conversation) that reads index.html first.
REPEATS = {"hour": 3600, "day": 86400, "week": 7 * 86400}
# Thread entries older than this are dropped (housekeeping, prune_threads()): index.html itself is the
# record, and an hourly repeat would otherwise grow agents.json without end. The last KEEP_LAST
# entries stay whatever their age (a New chat quotes them).
THREAD_KEEP_S = 7 * 86400
KEEP_LAST = 6


def busy(st):
    """True while a run is going or queued; waiting on SLURM jobs doesn't block a new comment."""
    return st.get("status") in ("working", "queued") and not st.get("job_wait")


def kilo(n):
    return "?" if n is None else "%dK" % round(n / 1000.0)


def clock(t):
    return time.strftime("%H:%M" if t - time.time() < 20 * 3600 else "%b %d %H:%M", time.localtime(t))


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


def in_git(path):
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
        self.hold_until = 0     # no run starts before this (usage limit)
        self.hold_reason = ""
        self.timer = None
        self.cards = {}         # index.html path -> (mtime, its summary card's problems)
        with self._edit() as data:
            for agent, st in data.items():           # runs don't survive a restart
                if "watch" in st:                    # its name before 2026-10
                    st["job_wait"] = st.pop("watch")
                end_asks(st)
                if st.get("status") == "queued" and st.get("pending"):   # queued ones do
                    self.queue.append((agent, st["pending"]))
                    if (st.get("queued_until") or 0) > self.hold_until:
                        self.hold_until, self.hold_reason = st["queued_until"], st.get("queued_reason", "")
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
                    "repeat": (s.get("repeat") or {}).get("every"), "asking": bool(s.get("asking")),
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
        with self.lock:
            st = self._load().get(agent) or {"status": "none", "thread": [], "denials": [], "grants": []}
            st = dict(st)
            st["always"] = load_json(PERMS_FILE, {"always": []})["always"]
            granted = set(st["always"]) | set(st.get("grants", []))
            # "granted": the rule is already allowed yet was refused anyway (built-in safety check,
            # e.g. ".." in a path), so another grant can't help
            st["context"] = context_tokens(st.get("session_id"))
            st["context_warn"], st["context_high"] = CONTEXT_WARN, CONTEXT_HIGH
            st["model"] = st.get("model") or DEFAULT_MODEL
            # the agent's own model stays in the list even if it's gone (Ollama stopped)
            st["models"] = [m for m in MODELS if m in available or m == st["model"]]
            st["model_labels"] = MODEL_LABELS
            st["permissions"] = self.permissions()
            st["watching"] = (st.get("job_wait") or {}).get("jobs", [])
            st["card"] = self.card_problems(agent)
            denials = []
            for d in st.get("denials", []):
                rules = denial_rules(d)
                denials.append({"text": describe_denial(d), "rules": rules,
                                "blocked": any(always_denied(r) for r in rules),
                                "granted": all(r in granted for r in rules)})
            st["denials"] = denials
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

    def set_repeat(self, agent, every, text=""):
        """Send text to the agent every hour/day/week from now on ("off" stops it)."""
        text = (text or "").strip()
        if every != "off" and (every not in REPEATS or not text):
            return False
        with self._edit(agent) as st:
            if every == "off":
                if not st.pop("repeat", None):
                    return False
                note(st, "Repeat turned off.")
            else:
                st["repeat"] = {"every": every, "text": text, "next": time.time() + REPEATS[every]}
                note(st, "Repeats every %s, next at %s:\n%s" % (every,
                         clock(st["repeat"]["next"]), text))
            return True

    def check_repeats(self):
        """Send each agent's repeated message that has come due, if the agent is free."""
        t = time.time()
        with self.lock:
            due = [(p, dict(st["repeat"])) for p, st in self._load().items()
                   if st.get("repeat") and st["repeat"]["next"] <= t and not busy(st) and not st.get("job_wait")]
        for agent, rep in due:
            prompt = ("(Scheduled run: the owner set this message to be sent every %s. This is a fresh "
                      "session with no earlier conversation: before acting, read this folder's index.html "
                      "(its summary card first) for the agent's current state, including what earlier runs found. "
                      "index.html is the only memory between runs, so record this run's result in it with the "
                      "date and time, next to the earlier runs' results rather than over them, so the "
                      "next run can compare.)\n\n%s" % (rep["every"], rep["text"]))
            if not self.comment(agent, rep["text"], prompt=prompt, scheduled=rep["every"]):
                continue    # became busy meanwhile: try again next pass
            with self._edit(agent) as st:
                if st.get("repeat"):
                    nxt, step = st["repeat"]["next"], REPEATS[st["repeat"]["every"]]
                    while nxt <= t:
                        nxt += step
                    st["repeat"]["next"] = nxt

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
        if every in REPEATS:
            self.set_repeat(agent, every, task)
        return True

    def new_chat(self, agent):
        """Next message starts a fresh Claude session (the thread stays, with a divider)."""
        with self._edit(agent) as st:
            if busy(st) or not st.get("session_id"):
                return False
            st["session_id"], st["denials"] = None, []
            note(st, NEW_CHAT_MARK)
            return True

    def compact(self, agent):
        """Run /compact on the agent's session (queued like a message)."""
        with self._edit(agent) as st:
            if busy(st) or not st.get("session_id"):
                return False
            st.pop("job_wait", None)   # the run re-checks the queue when it ends
            note(st, "Compact requested (context %s tokens)." % kilo(context_tokens(st["session_id"])))
            st["denials"] = []
            st["status"] = "working"
            st["working_on"], st["started"] = "Compact the conversation", None
        self._enqueue(agent, COMPACT)
        return True

    def comment(self, agent, text, prompt=None, selection=None, scheduled=None):
        """selection: {"text", "heading"} of index.html text the owner selected, quoted in the prompt,
        or {"text", "heading", "file", "lines"} of text in a file of the agent's folder (shown raw at the
        end of index.html, with its line numbers). False if file isn't one of those.
        scheduled: the repeat period when check_repeats() sends it (shown in the thread); it starts
        a fresh session, its prompt pointing at index.html instead of the thread."""
        if selection:
            md = selection.get("file")
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
            selection = dict({"text": selection["text"][:SEL_MAX], "heading": selection.get("heading", "")[:200],
                              "lines": lines}, **({"file": md} if md else {}))
            prompt = prompt or selection_prompt(selection, text)
        with self._edit(agent) as st:
            if busy(st):
                return False
            st.pop("job_wait", None)   # the run re-checks the queue when it ends
            st["auto_runs"] = 0
            if scheduled and st.get("session_id"):
                st["session_id"] = None
                note(st, NEW_CHAT_MARK)
            elif not st.get("session_id") and st["thread"] and (prompt is None or selection):
                prompt = fresh_prompt(st["thread"], prompt or text)   # New chat: catch up from index.html and the thread
            st["thread"].append(dict({"role": "user", "time": now(), "text": text},
                                     **({"selection": selection} if selection else {}),
                                     **({"scheduled": scheduled} if scheduled else {})))
            agent_dir = os.path.join(self.root, agent)
            named = [r for r in path_grants(text, self.root, read_scope(agent_dir, self.root))
                     if r not in st.get("grants", [])]
            if named:
                st["grants"] = sorted(set(st.get("grants", [])) | set(named))
                note(st, "Read access for this agent (named in your message): " + ", ".join(named))
            st["denials"] = []
            st["status"] = "working"   # waiting for a free slot counts as working
            st["working_on"], st["started"] = text, None
        prompt = prompt or text
        self._enqueue(agent, prompt)
        return True

    def grant(self, agent, rules, always):
        rules = [r for r in rules if r and not always_denied(r)]
        if not rules:
            return False
        with self._edit(agent) as st:
            if busy(st) or not st.get("session_id"):
                return False
            st.pop("job_wait", None)
            st["auto_runs"] = 0
            self._save_grants(st, rules, always)
            st["denials"] = []
            st["status"] = "working"   # waiting for a free slot counts as working
            st["working_on"], st["started"] = "Retry with granted: " + ", ".join(rules), None
        self._enqueue(agent, "The owner granted these permissions: %s. Retry what was blocked "
                            "and finish the task." % ", ".join(rules))
        return True

    @staticmethod
    def _save_grants(st, rules, always):
        """Keep rules for this agent (once) or for every agent (always); caller holds the lock.
        Folder reads stay with this agent even under "Always allow": letting agent A read B must
        not let every agent of every tree read B."""
        reads = [r for r in rules if is_read_rule(r)]
        others = [r for r in rules if not is_read_rule(r)]
        agent_rules, global_rules = (reads, others) if always else (rules, [])
        if global_rules:
            perms = load_json(PERMS_FILE, {"always": []})
            perms["always"] = sorted(set(perms["always"]) | set(global_rules))
            save_json(PERMS_FILE, perms)
            note(st, "Granted (always): " + ", ".join(global_rules))
        if agent_rules:
            st["grants"] = sorted(set(st.get("grants", [])) | set(agent_rules))
            note(st, "Granted (this agent): " + ", ".join(agent_rules))

    # --- permission prompts (ask mode) ---------------------------------------------------
    def _ask(self, agent, live, rid, req):
        """A permission prompt from the run: put it in the agent's thread for the owner. Answered
        at once when the owner chose Always allow for the same action earlier in this run, or
        when the run has used up its ASK_WAIT_S of waiting."""
        d = request_denial(req)
        rules = denial_rules(d)
        with self._edit(agent) as st:
            choice = ("allow" if rules and all(r in live.granted for r in rules)
                      else "timeout" if live.waiting() >= ASK_WAIT_S else None)
            st["thread"].append({"role": "ask", "time": now(), "id": rid, "text": describe_denial(d),
                                 "detail": json.dumps(d["tool_input"], indent=1)[:4000],
                                 "rules": rules, "answer": choice})
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
                self._save_grants(st, rules, True)
                # prompts already waiting for what was just granted (parallel tool calls) go too
                for other, oreq in list(live.pending.items()):
                    orules = denial_rules(request_denial(oreq))
                    if orules and all(r in live.granted for r in orules):
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
        else:
            r = {"behavior": "deny", "message": ASK_DENIED[choice]}
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
        check(): after a successful result, a follow-up message to send in the same session, or
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
            elif kind == "result":
                if out:     # the follow-up's result
                    out = dict(m, result=out.get("result"), followup=m.get("result") or "",
                               permission_denials=out.get("permission_denials", []) + m.get("permission_denials", []),
                               total_cost_usd=self._cost(out.get("total_cost_usd"), m.get("total_cost_usd")))
                    break
                out = m
                msg = check() if check and not m.get("is_error") else None
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
        if self.queue and self.hold_until <= time.time():
            until, reason = claude_usage.pause_until()     # network, so outside the lock (cached 60 s)
        else:
            until, reason = 0, ""
        with self.lock:
            if until > self.hold_until:
                self.hold_until, self.hold_reason = until, reason
            wait = self.hold_until - time.time()
            data = self._load()
            for item in list(self.queue):
                if self.running >= MAX_RUNNING:
                    break
                model = self._model(data, item[0])
                if wait > 0 and model not in NON_CLAUDE:
                    continue    # local and GenAI Studio agents don't use the Claude limits: they start anyway
                if model in GENAI_MODELS:
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
                self._queue_on_hold()
                if self.timer:
                    self.timer.cancel()
                self.timer = threading.Timer(wait, self._start_queued)
                self.timer.daemon = True
                self.timer.start()

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
        self._start_queued()

    def _queue_on_hold(self):
        """Mark every queued message as waiting for the usage limit; caller holds the lock.
        (A GenAI Studio one still queued waits for the GenAI agent running, not for the limit.)"""
        with self._changes() as data:
            for agent, prompt in self.queue:
                if self._model(data, agent) in NON_CLAUDE:
                    continue
                st = self._agent(data, agent)
                if st["status"] != "queued":
                    note(st, "%s. Queued: this message will be sent automatically at %s."
                             % (self.hold_reason or "Claude usage limit", clock(self.hold_until)))
                if st["status"] != "queued" or st.get("queued_until") != self.hold_until:
                    st["status"], st["queued_until"], st["pending"] = "queued", self.hold_until, prompt
                    st["queued_reason"], st["started"] = self.hold_reason, None

    def _command(self, agent_dir, model, grants, session):
        """The claude command line for a run in agent_dir: its permissions, folders, MCP servers
        and instructions."""
        allow = DEFAULT_ALLOW + self.config["allow"] + ["Edit(/%s/**)" % agent_dir] + \
            load_json(PERMS_FILE, {"always": []})["always"] + grants
        scope = read_scope(agent_dir, self.root)
        read_dirs = [scope] + self.config["read_dirs"]
        dirs = read_dirs + extra_dirs(allow, agent_dir, read_dirs)
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
               "--append-system-prompt", SYSTEM_PROMPT.format(root=self.root,
                   index_file=os.path.join(agent_dir, "index.html"), agent_dir=agent_dir, scope=scope,
                   git=GIT_PROMPT.format(agent_dir=agent_dir) if in_git(agent_dir) else "",
                   approval=APPROVAL[mode], always_denied=", ".join(ALWAYS_DENY), agent_rule_path=AGENT_RULE_MD,
                   agent_rm=os.path.join(dirai_config.SCRIPTS_DIR, "agent_rm.sh"),
                   card_py=os.path.join(dirai_config.LIB_DIR, "dirai_card.py"))
                   + "\n\n" + load_text(AGENT_RULE_MD),
               "--allowedTools"] + allow + ["--disallowedTools"] + ALWAYS_DENY
        if model in GENAI_MODELS:
            cmd += ["--effort", "medium"]
        if session:
            cmd += ["--resume", session]
        return cmd

    def _run(self, agent, prompt):
        """One message to the agent, from its slot in the queue to its reply in the thread."""
        try:
            session, grants, model = self._begin(agent)
            before = context_tokens(session)
            path = transcript(session)
            offset = os.path.getsize(path) if path and os.path.exists(path) else 0
            agent_dir = os.path.join(self.root, agent)
            index, snap = os.path.join(agent_dir, "index.html"), self.before_run_path(agent) + ".run"
            os.makedirs(os.path.dirname(snap), exist_ok=True)
            try:
                shutil.copyfile(index, snap)
            except OSError:
                pass
            entry, card_note, denials, session = self._attempt(agent, prompt, model, grants, session, agent_dir, snap)
            until = limit_reset(entry["text"]) if entry["role"] == "claude" and model not in NON_CLAUDE else None
            if prompt == COMPACT and entry["role"] == "claude" and not until:
                after = context_tokens(session)
                entry = system_entry("Conversation compacted: %s -> %s tokens." % (
                    kilo(before), kilo(after)) if after != before else "Compact finished: " + entry["text"])
            if not until:   # the run changed index.html: highlight against the copy from before it
                try:
                    with open(snap, "rb") as a, open(index, "rb") as b:
                        if a.read() != b.read():
                            os.replace(snap, self.before_run_path(agent))
                except OSError:
                    pass
            if os.path.exists(snap):
                os.remove(snap)
            if until:
                self._retry_after_limit(agent, prompt, entry, session, until)
                return
            ids = [] if entry["text"] == "Cancelled by the owner." else self._jobs_to_wait_for(agent_dir, session, offset)
            self._finish(agent, entry, card_note, denials, session, ids)
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

    def _begin(self, agent):
        """Mark the agent working as its run starts: (session, agent grants, model)."""
        with self._edit(agent) as st:
            st["status"] = "working"
            st["started"] = time.time()
            for k in ("queued_until", "pending", "queued_reason"):
                st.pop(k, None)
            return st.get("session_id"), list(st.get("grants", [])), st.get("model") or DEFAULT_MODEL

    def _attempt(self, agent, prompt, model, grants, session, agent_dir, snap):
        """Run claude on prompt until it replies, is cancelled, times out or fails to start:
        (thread entry, summary-card note or None, permission denials, session)."""
        index = os.path.join(agent_dir, "index.html")
        cmd = self._command(agent_dir, model, grants, session)
        card_note = None
        try:
            env = dict(os.environ, DIRAI_AGENT_DIR=agent_dir, **model_env(model))
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
            out = self._drive(agent, live, None if prompt == COMPACT else lambda: self._card_fix(index, snap))
            with self.lock:
                self.procs.pop(agent, None)
                if agent in self.cancelled:
                    raise RunCancelled()
            if live.timed_out:
                raise subprocess.TimeoutExpired(cmd, RUN_TIMEOUT_S)
            reply = out.get("result") or live.err[-2000:] or "(no reply)"
            entry = {"role": "claude", "time": now(), "text": reply, "model": model}
            if "followup" in out:
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

    def _retry_after_limit(self, agent, prompt, entry, session, until):
        """Claude refused for the usage limit: keep the message and send it again after the reset,
        in the same session, ahead of the rest of the queue."""
        retry = prompt if prompt == COMPACT or prompt.startswith(LIMIT_RETRY) else LIMIT_RETRY + prompt
        with self.lock:
            if until > self.hold_until:
                self.hold_until, self.hold_reason = until, "Claude usage limit hit (%s)" % entry["text"]
            self.queue.insert(0, (agent, retry))
            with self._changes(agent) as st:
                st["session_id"] = session

    def _finish(self, agent, entry, card_note, denials, session, ids):
        """Put the run's reply in the thread, and wait for the SLURM jobs ids if there are any."""
        with self._edit(agent) as st:
            st["thread"].append(entry)
            if card_note:
                st["thread"].append(card_note)
            st["denials"] = denials
            st["session_id"] = session
            st["status"] = "unread"
            if ids and st.get("auto_runs", 0) >= MAX_AUTO:
                note(st, "SLURM jobs %s are still queued, but the agent has already been "
                         "messaged automatically %d times in a row; not watching them. Comment "
                         "to continue." % (", ".join(ids), MAX_AUTO))
            elif ids:
                self._start_job_wait(st, ids)

    # --- waiting on SLURM jobs ------------------------------------------------------------
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

    def _jobs_to_wait_for(self, agent_dir, session, offset):
        """Jobs still queued that this run submitted, plus the owner's jobs in the agent's folder."""
        live = slurm.live_ids()
        if live is None:
            return []
        ids = [i for i in submitted_jobs(session, offset) if i in live]
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
