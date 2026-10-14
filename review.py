"""Page reviews for html_server.py: a comment thread per index.html page, each saved
comment handed to a background `claude -p` session working in that page's folder.

Status per page: working (Claude is running) -> unread (new reply) -> read -> closed.
A new comment reopens a page. When a run hits the Claude usage limit, the page is "queued":
its message is kept (in reviews.json, so it survives a restart) and sent again, in the same
session, shortly after the limit resets; no run starts before then. Runs are also held back
(same "queued" status) while plan usage is at or above claude_usage.SESSION_STOP % of the
5-hour session limit or WEEKLY_STOP % of the weekly limit, until that limit resets. State for one served root lives in <root>/www/reviews.json.

Only the owner can use any of this: requests must come from 127.0.0.1 (the SSH tunnel
lands on this node's loopback) and carry the secret key cookie (see login_key()).
Everyone else gets 404 for /_review/* and sees pages without the panel.
"""
import datetime
import glob
import json
import os
import re
import secrets
import subprocess
import threading
import time

import claude_usage
import dirai_config

KEY_FILE = dirai_config.KEY_FILE
WWW_DIR = dirai_config.TOOL_DIR
PERMS_FILE = dirai_config.PERMS_FILE
PAGES_MD = os.path.join(WWW_DIR, "PAGES.md")   # page conventions, appended to every run's instructions
CLAUDE_CMD = os.environ.get("REVIEW_CLAUDE_CMD", os.path.expanduser("~/.local/bin/claude"))
# Background runs use --restricted: user/project/local settings files are ignored (so rules
# granted to interactive sessions never leak in) and file tools stay inside the tree plus the
# tree's dirai.json "read_dirs", which Claude may read; edits still need an allow rule (only the
# page folder has one).
TOOLS = "Bash,Read,Edit,Write,Glob,Grep,Skill,TodoWrite,NotebookEdit"
MAX_RUNNING = 2
# "You've hit your session limit · resets 10:20pm (America/Indiana/Indianapolis)"
LIMIT_RE = re.compile(r"(?i)\b(hit|reached) your\b.*\blimit\b|\busage limit\b")
RESET_RE = re.compile(r"(?i)resets?\s+(?:at\s+)?(?:([A-Z][a-z]{2})\s+(\d{1,2}),?\s+(?:at\s+)?)?"
                      r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)")
# A resumed session resends its whole context with every request; warn (panel, list badge) when
# it is this big and offer Compact, which runs Claude Code's /compact on the session.
CONTEXT_WARN = 150000
CONTEXT_HIGH = 300000
COMPACT = "/compact"
TRANSCRIPTS = os.path.join(os.environ.get("CLAUDE_CONFIG_DIR", os.path.expanduser("~/.claude")), "projects")
LIMIT_MARGIN_S = 120        # send this long after the stated reset time
LIMIT_FALLBACK_S = 1800     # retry after this when the reset time can't be read
RUN_TIMEOUT_S = 4 * 3600

DEFAULT_ALLOW = [
    "Read", "Glob", "Grep", "Skill", "TodoWrite",
    "Bash(python3:*)", "Bash(bash:*)", "Bash(sh:*)",
    "Bash(sbatch:*)", "Bash(squeue:*)", "Bash(scancel:*)", "Bash(sacct:*)", "Bash(scontrol show:*)",
    "Bash(ls:*)", "Bash(cat:*)", "Bash(head:*)", "Bash(tail:*)", "Bash(grep:*)", "Bash(find:*)",
    "Bash(wc:*)", "Bash(diff:*)", "Bash(awk:*)", "Bash(sed -n:*)", "Bash(sort:*)", "Bash(du:*)",
    "Bash(mkdir:*)", "Bash(cp:*)", "Bash(mv:*)", "Bash(ln -s:*)", "Bash(cmp:*)", "Bash(date:*)",
    "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)",
    "Bash(git add:*)", "Bash(git commit:*)", "Bash(git push:*)", "Bash(git fetch:*)",
    "Bash(git ls-files:*)", "Bash(git rev-parse:*)", "Bash(git remote -v)", "Bash(git branch --show-current)",
    # deleting: only via page_rm.sh, which refuses anything outside the page folder
    "Bash(%s/page_rm.sh:*)" % os.path.dirname(os.path.abspath(__file__)),
    # shell plumbing Claude chains into its commands (every part of a && chain must match)
    "Bash(cd:*)", "Bash(echo:*)", "Bash(printf:*)", "Bash(set:*)", "Bash(export:*)", "Bash(test:*)",
    "Bash([:*)", "Bash(true)", "Bash(false)", "Bash(sleep:*)", "Bash(for:*)", "Bash(while:*)",
    "Bash(if:*)", "Bash(type:*)", "Bash(which:*)", "Bash(tr:*)", "Bash(cut:*)", "Bash(uniq:*)",
    "Bash(tee:*)", "Bash(xargs:*)", "Bash(basename:*)", "Bash(dirname:*)", "Bash(realpath:*)",
    "Bash(readlink:*)", "Bash(stat:*)", "Bash(touch:*)", "Bash(paste:*)", "Bash(column:*)",
    "Bash(sed:*)", "Bash(module:*)", "Bash(source:*)", "Bash(.:*)", "Bash(seq:*)", "Bash(env:*)",
]   # plus the tree's dirai.json "allow" rules
ALWAYS_DENY = [
    "Bash(git push --force:*)", "Bash(git push -f:*)", "Bash(git push --force-with-lease:*)",
    "Bash(git reset:*)", "Bash(git checkout:*)", "Bash(git restore:*)", "Bash(git stash:*)",
    "Bash(git rebase:*)", "Bash(git clean:*)", "Bash(git commit --amend:*)",
    "Bash(git -C:*)",   # would slip past the rules above (git -C x push --force)
    "Bash(rm -rf:*)", "Bash(rm -r:*)", "Bash(sudo:*)",
]

SYSTEM_PROMPT = """You are handling a review comment the owner left on one of their HTML report pages,
served from their tree {root}. The page is {page_file}; its
folder ({page_dir}) is your working directory and the place for your changes. Do what the comment
asks (fix the page, rerun scripts, regenerate plots, submit SLURM jobs for long runs), then end
with a short reply for the comment thread: what you changed, what you ran, and anything still open.
Bash permissions are matched per command, and a built-in safety check refuses anything it can't
verify, whatever is granted: command substitution $(...) or backticks, for/while loops (also
"... | while read"), heredocs, and paths with "..". So keep each Bash call to one plain command or
a short && chain of plain commands with literal absolute paths. For anything more (counting,
checking several files, loops), write a small python3 or bash script file in this folder and run
it with "python3 <file>" or "bash <file>". Always write fully
resolved absolute paths: never "..", which a built-in safety check refuses no matter what is granted.
Follow the page conventions below (from {pages_md_path}); in particular, keep this folder's todo.md
current and give every figure its script path.
Git: you may git add / commit / push (this replaces any earlier "never commit" instruction), but
only when the owner's message asks for it (that request is their approval). Run git from your
working directory (this page folder, inside the repo) with no "cd ... &&" before it and no "git -C":
a built-in check refuses git after cd, and -C is blocked.
Stage and commit only this page's folder: "git add -- {page_dir}", then
'git commit -m "<summary>" -m "<details>" -m "Co-Authored-By: Claude <noreply@anthropic.com>" -- {page_dir}'
(never "git add -A" or "git add ." at the repo root: other agents share this checkout), then
"git push origin HEAD".
If the push is rejected (the remote moved on), stop and tell the owner; don't pull, rebase or
force. Quote the commit hash and message in your reply.
To delete files or folders, run "{page_rm} <path>...": it works only inside this page folder and
deletes immediately, no trash (plain rm -r / rm -rf stay blocked).
Rules: don't delete anything outside this folder; long or heavy work goes to
SLURM (sbatch), not this process. Nobody can approve actions while you run: if a permission is
denied, do the rest and say in your reply exactly what you needed and why; the owner can grant it
and resume you. Exception: these are blocked permanently and can never be granted, so don't ask;
give the owner the exact command to run themselves instead: {always_denied}."""


STARTER_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>body {{ font-family: system-ui, sans-serif; max-width: 56rem; margin: 2rem auto; padding: 0 16px; }}</style>
</head>
<body>
<h1>{title}</h1>
<p><i>Created {date} by New agent; the AI assistant is working on this task and will replace this page.</i></p>
<h2>Task</h2>
<p style="white-space:pre-wrap">{task}</p>
</body>
</html>
"""


NEW_CHAT_MARK = "New chat: the next message starts a fresh session."


def fresh_prompt(thread, text, keep=6, limit=1500):
    """First message of a new session on a page that already has a thread: point it at the
    page's state and quote the last few thread entries."""
    recent = [m for m in thread if m.get("text") != NEW_CHAT_MARK][-keep:]
    quoted = "\n\n".join("[%s, %s]\n%s" % (m["role"], m["time"], m["text"][:limit] +
                                             ("..." if len(m["text"]) > limit else ""))
                          for m in recent)
    return ("This is a fresh session on a page that already has history. Before acting, read this "
            "folder's index.html and todo.md; the last messages of the earlier conversation follow "
            "for context.\n\n--- earlier messages ---\n%s\n--- end ---\n\nNew message:\n%s" % (quoted, text))


def limit_reset(reply):
    """Epoch time the usage limit resets, if reply is Claude's usage-limit message, else None.
    The stated clock time is taken as server-local time, at its next occurrence."""
    if not reply or len(reply) > 300 or not LIMIT_RE.search(reply):
        return None
    m = RESET_RE.search(reply)
    if not m:
        return time.time() + LIMIT_FALLBACK_S
    mon, day, hour, minute, ampm = m.groups()
    hour = int(hour) % 12 + (12 if ampm.lower() == "pm" else 0)
    nowdt = datetime.datetime.now()
    at = nowdt.replace(hour=hour, minute=int(minute or 0), second=0, microsecond=0)
    if mon:
        try:
            at = at.replace(month=datetime.datetime.strptime(mon, "%b").month, day=int(day))
        except ValueError:
            return time.time() + LIMIT_FALLBACK_S
        if at < nowdt - datetime.timedelta(days=180):
            at = at.replace(year=at.year + 1)
    elif at <= nowdt:
        at += datetime.timedelta(days=1)
    return time.mktime(at.timetuple()) + LIMIT_MARGIN_S


_ctx_cache = {}


def context_tokens(session_id):
    """Tokens in the session's context: the last request's input (uncached + cache write +
    cache read), or the size recorded by a later compaction. None if unknown."""
    if not session_id:
        return None
    paths = glob.glob(os.path.join(TRANSCRIPTS, "*", session_id + ".jsonl"))
    if not paths:
        return None
    try:
        mtime = os.path.getmtime(paths[0])
        if _ctx_cache.get(paths[0], (None,))[0] == mtime:
            return _ctx_cache[paths[0]][1]
        ctx = None
        with open(paths[0], encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"usage"' not in line and "compact_boundary" not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("subtype") == "compact_boundary":
                    ctx = (d.get("compactMetadata") or {}).get("postTokens", ctx)
                m = d.get("message")
                u = m.get("usage") if d.get("type") == "assistant" and isinstance(m, dict) else None
                if isinstance(u, dict):
                    n = sum(u.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens",
                                                    "cache_read_input_tokens"))
                    if n:       # synthetic replies (e.g. the usage-limit message) carry 0
                        ctx = n
    except OSError:
        return None
    _ctx_cache[paths[0]] = (mtime, ctx)
    return ctx


def kilo(n):
    return "?" if n is None else "%dK" % round(n / 1000.0)


def clock(t):
    return time.strftime("%H:%M" if t - time.time() < 20 * 3600 else "%b %d %H:%M", time.localtime(t))


def html_escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def split_command(cmd):
    """Pieces of a chained shell command (split on &&, ||, ;, | outside quotes): Claude Code
    checks permissions per piece, so a grant has to name each piece."""
    pieces, cur, quote, i = [], "", None, 0
    while i < len(cmd):
        c = cmd[i]
        if quote:
            if c == quote:
                quote = None
            elif c == "\\" and quote == '"' and i + 1 < len(cmd):
                cur += c
                i += 1
                c = cmd[i]
        elif c in "'\"":
            quote = c
        elif cmd.startswith(("&&", "||"), i):
            pieces.append(cur)
            cur, i = "", i + 2
            continue
        elif c in ";|\n":
            pieces.append(cur)
            cur, i = "", i + 1
            continue
        cur += c
        i += 1
    pieces.append(cur)
    return [p.strip() for p in pieces if p.strip()]


def denial_rules(d):
    """Allow rules that grant exactly the denied action (one per piece of a chained command)."""
    if d.get("tool_name") == "Bash":
        return ["Bash(%s)" % p for p in split_command((d.get("tool_input") or {}).get("command", ""))]
    return [denial_rule(d)]


def denial_rule(d):
    """Turn a permission_denials entry into an allow rule granting exactly that action."""
    tool, inp = d.get("tool_name", ""), d.get("tool_input", {}) or {}
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        path = inp.get("file_path") or inp.get("notebook_path") or ""
        return "Edit(/%s)" % path if path.startswith("/") else "Edit(%s)" % path
    if tool == "Bash":
        return "Bash(%s)" % inp.get("command", "")
    if tool in ("Read", "Grep", "Glob"):
        # blocked by the working-folder limit: grant read access to the folder
        path = inp.get("file_path") or inp.get("path") or ""
        if path.startswith("/"):
            folder = path if os.path.isdir(path) else os.path.dirname(path)
            return "Read(/%s/**)" % folder
    if tool in ("WebFetch",) and inp.get("url"):
        from urllib.parse import urlparse
        return "WebFetch(domain:%s)" % urlparse(inp["url"]).netloc
    return tool


def always_denied(rule):
    """True if ALWAYS_DENY blocks this rule no matter what is granted (deny beats allow)."""
    if rule in ALWAYS_DENY:
        return True
    if rule.startswith("Bash(") and rule.endswith(")"):
        cmd = rule[5:-1].strip()
        for d in ALWAYS_DENY:
            if d.startswith("Bash(") and d.endswith(":*)"):
                prefix = d[5:-3]
                if cmd == prefix or cmd.startswith(prefix + " "):
                    return True
    return False


def extra_dirs(allow, page_dir, read_dirs):
    """Working directories a run needs beyond read_dirs: restricted mode only lets tools touch
    working directories, so granted edits, and granted commands naming absolute paths, bring
    their folders along."""
    extra = {os.path.dirname(r[len("Edit(/"):-1]) for r in allow if r.startswith("Edit(//")}
    extra |= {r[len("Read(/"):-1].rstrip("*").rstrip("/") for r in allow if r.startswith("Read(//")}
    for r in allow:
        if r.startswith("Bash(") and not r.endswith(":*)"):
            for tok in re.findall(r"""(?<![\w.])/[^\s'"|;&<>()]+""", r[5:-1]):
                extra.add(tok if os.path.isdir(tok) else os.path.dirname(tok))
    return sorted(d for d in extra if d and d != "/" and os.path.isdir(d)
                  and not any(d == r or d.startswith(r + "/") for r in read_dirs + [page_dir]))


def describe_denial(d):
    tool, inp = d.get("tool_name", ""), d.get("tool_input", {}) or {}
    detail = inp.get("command") or inp.get("file_path") or inp.get("url") or json.dumps(inp)[:200]
    return "%s: %s" % (tool, detail)


LIMIT_RETRY = ("(Your previous attempt at the message below was cut off by the Claude usage "
               "limit. Check what is already done before continuing.)\n\n")


class Reviews:
    def __init__(self, root):
        self.root = root
        self.config = dirai_config.tree_config(root)
        self.read_dirs = [root] + self.config["read_dirs"]
        self.path = os.path.join(root, "www", "reviews.json")
        self.lock = threading.Lock()
        self.running = 0
        self.queue = []
        self.hold_until = 0     # no run starts before this (usage limit)
        self.hold_reason = ""
        self.timer = None
        with self.lock:
            data = load_json(self.path, {})
            for page, st in data.items():           # runs don't survive a restart
                if st.get("status") == "queued" and st.get("pending"):   # queued ones do
                    self.queue.append((page, st["pending"]))
                    if (st.get("queued_until") or 0) > self.hold_until:
                        self.hold_until, self.hold_reason = st["queued_until"], st.get("queued_reason", "")
                elif st.get("status") == "working":
                    st["status"] = "unread"
                    st["thread"].append({"role": "system", "time": now(),
                                         "text": "The server restarted while this was running; "
                                                 "the run was lost. Comment again to retry."})
            self._save(data)
        if self.queue:
            self._pump()

    # --- state ------------------------------------------------------------------------
    def _load(self):
        return load_json(self.path, {})

    def _save(self, data):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        save_json(self.path, data)

    def _page(self, data, page):
        return data.setdefault(page, {"status": "read", "thread": [], "session_id": None,
                                      "denials": [], "grants": []})

    def all_status(self):
        with self.lock:
            data = self._load()
        return {p: {"status": s["status"], "updated": (s["thread"][-1]["time"] if s["thread"] else ""),
                    "context": context_tokens(s.get("session_id"))}
                for p, s in data.items()}

    def state(self, page):
        with self.lock:
            st = self._load().get(page) or {"status": "none", "thread": [], "denials": [], "grants": []}
            st = dict(st)
            st["always"] = load_json(PERMS_FILE, {"always": []})["always"]
            granted = set(st["always"]) | set(st.get("grants", []))
            # "granted": the rule is already allowed yet was refused anyway (built-in safety check,
            # e.g. ".." in a path), so another grant can't help
            st["context"] = context_tokens(st.get("session_id"))
            st["context_warn"], st["context_high"] = CONTEXT_WARN, CONTEXT_HIGH
            st["denials"] = [{"text": describe_denial(d), "rules": denial_rules(d),
                              "blocked": any(always_denied(r) for r in denial_rules(d)),
                              "granted": all(r in granted for r in denial_rules(d))}
                             for d in st.get("denials", [])]
            return st

    def working(self, page):
        """(what, started, until) if Claude is working on page or it is queued, else None.
        started is None while waiting; until is when a usage-limit wait ends (or None)."""
        with self.lock:
            st = self._load().get(page)
            if not st or st.get("status") not in ("working", "queued"):
                return None
            until = st.get("queued_until") if st["status"] == "queued" else None
            return st.get("working_on") or "", st.get("started"), until, st.get("queued_reason") or ""

    def set_status(self, page, status):
        with self.lock:
            data = self._load()
            st = self._page(data, page)
            if st["status"] in ("working", "queued"):
                return False
            st["status"] = status
            self._save(data)
            return True

    # --- running Claude ---------------------------------------------------------------
    def new_page(self, page, task):
        """Create ROOT/page/ with a starter index.html if it has none, then start an agent there
        on task. False if that page's agent is already working."""
        full = os.path.join(self.root, page)
        os.makedirs(full, exist_ok=True)
        index = os.path.join(full, "index.html")
        created = not os.path.exists(index)
        if created:
            title = html_escape(os.path.basename(page) or page)
            with open(index, "w", encoding="utf-8") as f:
                f.write(STARTER_PAGE.format(title=title, task=html_escape(task), date=now()[:10]))
        prompt = task
        if created:
            prompt = ("This folder and its index.html were just created for this task (the page is a "
                      "placeholder). Do the task, and turn index.html into the page that reports it.\n\n"
                      "Task: " + task)
        return self.comment(page, task, prompt)

    def new_chat(self, page):
        """Next message starts a fresh Claude session (the thread stays, with a divider)."""
        with self.lock:
            data = self._load()
            st = self._page(data, page)
            if st["status"] in ("working", "queued") or not st.get("session_id"):
                return False
            st["session_id"], st["denials"] = None, []
            st["thread"].append({"role": "system", "time": now(), "text": NEW_CHAT_MARK})
            self._save(data)
            return True

    def compact(self, page):
        """Run /compact on the page's session (queued like a message)."""
        with self.lock:
            data = self._load()
            st = self._page(data, page)
            if st["status"] in ("working", "queued") or not st.get("session_id"):
                return False
            st["thread"].append({"role": "system", "time": now(), "text":
                                 "Compact requested (context %s tokens)." % kilo(context_tokens(st["session_id"]))})
            st["denials"] = []
            st["status"] = "working"
            st["working_on"], st["started"] = "Compact the conversation", None
            self._save(data)
        self._enqueue(page, COMPACT)
        return True

    def comment(self, page, text, prompt=None, on_file=None):
        with self.lock:
            data = self._load()
            st = self._page(data, page)
            if st["status"] in ("working", "queued"):
                return False
            if not st.get("session_id") and st["thread"] and prompt is None:
                prompt = fresh_prompt(st["thread"], text)   # New chat: catch up from the page and thread
            st["thread"].append({"role": "user", "time": now(), "text": text})
            st["denials"] = []
            st["status"] = "working"   # waiting for a free slot counts as working
            st["working_on"], st["started"] = text, None
            self._save(data)
        prompt = prompt or text
        if on_file:     # sent from a plan_*.html page in this folder rather than index.html
            prompt = ("(This message was sent from %s in this folder; that file is the page it is "
                      "about, not index.html.)\n\n%s" % (on_file, prompt))
        self._enqueue(page, prompt)
        return True

    def grant(self, page, rules, always):
        rules = [r for r in rules if r and not always_denied(r)]
        if not rules:
            return False
        with self.lock:
            data = self._load()
            st = self._page(data, page)
            if st["status"] in ("working", "queued") or not st.get("session_id"):
                return False
            if always:
                perms = load_json(PERMS_FILE, {"always": []})
                perms["always"] = sorted(set(perms["always"]) | set(rules))
                save_json(PERMS_FILE, perms)
            else:
                st["grants"] = sorted(set(st.get("grants", [])) | set(rules))
            st["thread"].append({"role": "system", "time": now(),
                                 "text": "Granted (%s): %s" % ("always" if always else "this page", ", ".join(rules))})
            st["denials"] = []
            st["status"] = "working"   # waiting for a free slot counts as working
            st["working_on"], st["started"] = "Retry with granted: " + ", ".join(rules), None
            self._save(data)
        self._enqueue(page, "The owner granted these permissions: %s. Retry what was blocked "
                            "and finish the review." % ", ".join(rules))
        return True

    def _enqueue(self, page, prompt):
        with self.lock:
            self.queue.append((page, prompt))
        self._pump()

    def _pump(self):
        if self.queue and self.hold_until <= time.time():
            until, reason = claude_usage.hold()     # network, so outside the lock (cached 60 s)
        else:
            until, reason = 0, ""
        with self.lock:
            if until > self.hold_until:
                self.hold_until, self.hold_reason = until, reason
            wait = self.hold_until - time.time()
            if wait > 0:
                self._hold_queue()
                if self.timer:
                    self.timer.cancel()
                self.timer = threading.Timer(wait, self._pump)
                self.timer.daemon = True
                self.timer.start()
                return
            while self.queue and self.running < MAX_RUNNING:
                page, prompt = self.queue.pop(0)
                self.running += 1
                threading.Thread(target=self._run, args=(page, prompt), daemon=True).start()

    def _hold_queue(self):
        """Mark every queued message as waiting for the usage limit; caller holds the lock."""
        data = self._load()
        for page, prompt in self.queue:
            st = self._page(data, page)
            if st["status"] != "queued":
                st["thread"].append({"role": "system", "time": now(), "text":
                                     "%s. Queued: this message will be sent automatically at %s."
                                     % (self.hold_reason or "Claude usage limit", clock(self.hold_until))})
            if st["status"] != "queued" or st.get("queued_until") != self.hold_until:
                st["status"], st["queued_until"], st["pending"] = "queued", self.hold_until, prompt
                st["queued_reason"], st["started"] = self.hold_reason, None
        self._save(data)

    def _run(self, page, prompt):
        try:
            with self.lock:
                data = self._load()
                st = self._page(data, page)
                st["status"] = "working"
                st["started"] = time.time()
                for k in ("queued_until", "pending", "queued_reason"):
                    st.pop(k, None)
                session, grants = st.get("session_id"), list(st.get("grants", []))
                self._save(data)
            before = context_tokens(session)
            page_dir = os.path.join(self.root, page)
            allow = DEFAULT_ALLOW + self.config["allow"] + ["Edit(/%s/**)" % page_dir] + \
                load_json(PERMS_FILE, {"always": []})["always"] + grants
            dirs = self.read_dirs + extra_dirs(allow, page_dir, self.read_dirs)
            cmd = [CLAUDE_CMD, "-p", prompt, "--output-format", "json", "--permission-mode", "dontAsk",
                   "--restricted", "--strict-mcp-config", "--tools", TOOLS, "--add-dir"] + dirs + [
                   "--append-system-prompt", SYSTEM_PROMPT.format(root=self.root,
                       page_file=os.path.join(page_dir, "index.html"), page_dir=page_dir,
                       always_denied=", ".join(ALWAYS_DENY), pages_md_path=PAGES_MD,
                       page_rm=os.path.join(WWW_DIR, "page_rm.sh"))
                       + "\n\n" + load_text(PAGES_MD),
                   "--allowedTools"] + allow + ["--disallowedTools"] + ALWAYS_DENY
            if session:
                cmd += ["--resume", session]
            try:
                p = subprocess.run(cmd, cwd=page_dir, env=dict(os.environ, REVIEW_PAGE_DIR=page_dir),
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, timeout=RUN_TIMEOUT_S)
                out = json.loads(p.stdout.decode("utf-8", "replace") or "{}")
                reply = out.get("result") or p.stderr.decode("utf-8", "replace")[-2000:] or "(no reply)"
                entry = {"role": "claude", "time": now(), "text": reply}
                if out.get("total_cost_usd") is not None:
                    entry["cost"] = round(out["total_cost_usd"], 3)
                denials = out.get("permission_denials", [])
                session = out.get("session_id") or session
            except subprocess.TimeoutExpired:
                entry, denials = {"role": "system", "time": now(), "text": "Run timed out after %d h." % (RUN_TIMEOUT_S // 3600)}, []
            except (ValueError, OSError) as e:
                entry, denials = {"role": "system", "time": now(), "text": "Run failed: %s" % e}, []
            until = limit_reset(entry["text"]) if entry["role"] == "claude" else None
            if prompt == COMPACT and entry["role"] == "claude" and not until:
                after = context_tokens(session)
                entry = {"role": "system", "time": now(), "text": "Conversation compacted: %s -> %s tokens." % (
                    kilo(before), kilo(after)) if after != before else "Compact finished: " + entry["text"]}
            if until:
                # keep the message and send it again after the reset, in the same session
                retry = prompt if prompt == COMPACT or prompt.startswith(LIMIT_RETRY) else LIMIT_RETRY + prompt
                with self.lock:
                    if until > self.hold_until:
                        self.hold_until, self.hold_reason = until, "Claude usage limit hit (%s)" % entry["text"]
                    self.queue.insert(0, (page, retry))
                    data = self._load()
                    st = self._page(data, page)
                    st["session_id"] = session
                    self._save(data)
                return
            with self.lock:
                data = self._load()
                st = self._page(data, page)
                st["thread"].append(entry)
                st["denials"] = denials
                st["session_id"] = session
                st["status"] = "unread"
                self._save(data)
        finally:
            with self.lock:
                self.running -= 1
            self._pump()
