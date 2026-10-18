"""A `claude -p` run as agents.py drives it: LiveRun (its stream-json stdin and the permission
prompts waiting for the owner), stopping it with the commands it started, and reading what it
left behind (its transcript: context size, SLURM jobs it submitted; a usage-limit reply).
"""
import datetime
import glob
import json
import os
import re
import signal
import threading
import time

import dirai_config

TRANSCRIPTS = dirai_config.TRANSCRIPTS


# "You've hit your session limit · resets 10:20pm (America/Indiana/Indianapolis)"
LIMIT_RE = re.compile(r"(?i)\b(hit|reached) your\b.*\blimit\b|\busage limit\b")


RESET_RE = re.compile(r"(?i)resets?\s+(?:at\s+)?(?:([A-Z][a-z]{2})\s+(\d{1,2}),?\s+(?:at\s+)?)?"
                      r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)")


LIMIT_MARGIN_S = 120        # send this long after the stated reset time


LIMIT_FALLBACK_S = 1800     # retry after this when the reset time can't be read


SUBMITTED_RE = re.compile(r"Submitted batch job (\d+)")


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
    path = transcript(session_id)
    if not path:
        return None
    try:
        mtime = os.path.getmtime(path)
        if _ctx_cache.get(path, (None,))[0] == mtime:
            return _ctx_cache[path][1]
        ctx = None
        with open(path, encoding="utf-8", errors="replace") as f:
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
    _ctx_cache[path] = (mtime, ctx)
    return ctx


def transcript(session_id):
    """Path of the session's transcript, or None."""
    paths = glob.glob(os.path.join(TRANSCRIPTS, "*", session_id + ".jsonl")) if session_id else []
    return paths[0] if paths else None


def submitted_jobs(session_id, offset):
    """Job ids sbatch printed in the session's transcript after byte offset (this run's part)."""
    path = transcript(session_id)
    if not path:
        return []
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return []
    return list(dict.fromkeys(SUBMITTED_RE.findall(text)))


class RunCancelled(Exception):
    pass


def signal_group(p, sig):
    """Send sig to the run's process group (it may have exited already)."""
    try:
        os.killpg(p.pid, sig)
    except OSError:
        pass


def stop_process(p):
    """SIGTERM a claude run and the commands it started (its own process group), SIGKILL
    whatever is left after 10 s."""
    signal_group(p, signal.SIGTERM)
    t = threading.Timer(10, signal_group, args=(p, signal.SIGKILL))
    t.daemon = True
    t.start()


class LiveRun:
    """A running claude driven over stream-json: its stdin, and (ask mode) its permission prompts
    waiting for the owner. Agents.lock guards pending, granted and the waiting clock."""
    def __init__(self, proc):
        self.proc, self.lock = proc, threading.Lock()
        self.pending = {}       # request_id -> its can_use_tool request
        self.granted = set()    # rules the owner answered "Always allow" during this run
        self.waited, self.since = 0.0, None
        self.timed_out, self.err = False, ""

    def send(self, msg):
        with self.lock:
            try:
                self.proc.stdin.write(json.dumps(msg).encode() + b"\n")
                self.proc.stdin.flush()
            except (OSError, ValueError):
                pass    # the run has ended

    def close(self):
        with self.lock:
            try:
                self.proc.stdin.close()
            except OSError:
                pass

    def waiting(self):
        """Total time this run has spent waiting for the owner's answers."""
        return self.waited + (time.time() - self.since if self.since else 0)

    def hold(self, rid, req):
        self.pending[rid] = req
        self.since = self.since or time.time()

    def release(self, rid):
        req = self.pending.pop(rid, None)
        if req is not None and not self.pending and self.since:
            self.waited += time.time() - self.since
            self.since = None
        return req
