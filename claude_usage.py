"""Claude plan usage (the numbers Claude Code's /usage shows), for review.py and the list page.

Reads https://api.anthropic.com/api/oauth/usage with Claude Code's own login token from
~/.claude/.credentials.json. Asking costs no tokens. The token is only read, never refreshed
here: Claude Code refreshes it whenever it runs. If the token has expired or the request fails,
usage is unknown and nothing is held back.

This is the endpoint Claude Code itself uses; it is not a documented API and may change.
"""
import calendar
import json
import os
import threading
import time
import urllib.request

CREDENTIALS = os.path.join(os.environ.get("CLAUDE_CONFIG_DIR", os.path.expanduser("~/.claude")),
                           ".credentials.json")
URL = "https://api.anthropic.com/api/oauth/usage"
CACHE_S = 60                # ask at most once a minute, across all DirAI servers (shared file)
BACKOFF_S = 300             # after a refused request (e.g. 429), wait this long before asking again
SHARED = os.path.join(os.path.expanduser(os.environ.get("DIRAI_CONFIG_DIR", "~/.config/dirai")), "usage.json")
SESSION_STOP = 95           # no new runs at or above this % of the 5-hour session limit
WEEKLY_STOP = 98            # ... or this % of the weekly limit
RESUME_MARGIN_S = 120       # start again this long after the limit resets

_lock = threading.Lock()
_cache = {"checked": 0, "usage": None}


def _epoch(iso):
    """'2026-10-14T08:09:59.98+00:00' -> epoch seconds (Python 3.6 has no fromisoformat)."""
    if not iso:
        return None
    base, sign, off = iso[:19], 0, iso[19:]
    for ch in "+-":
        k = off.rfind(ch)
        if k >= 0:
            sign, off = (1 if ch == "+" else -1), off[k + 1:]
            break
    t = calendar.timegm(time.strptime(base, "%Y-%m-%dT%H:%M:%S"))
    if sign:
        hh, _, mm = off.partition(":")
        t -= sign * (int(hh) * 3600 + int(mm or 0) * 60)
    return t


def _fetch():
    with open(CREDENTIALS) as f:
        token = json.load(f)["claudeAiOauth"]["accessToken"]
    req = urllib.request.Request(URL, headers={"Authorization": "Bearer " + token,
                                               "anthropic-beta": "oauth-2025-04-20"})
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read().decode())
    out = {}
    for key, name in (("five_hour", "session"), ("seven_day", "weekly")):
        w = d.get(key) or {}
        if w.get("utilization") is not None:
            out[name] = {"percent": float(w["utilization"]), "resets": _epoch(w.get("resets_at"))}
    return out


def _read_shared():
    try:
        with open(SHARED) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_shared(u):
    try:
        os.makedirs(os.path.dirname(SHARED), exist_ok=True)
        with open(SHARED + ".%d.tmp" % os.getpid(), "w") as f:
            json.dump(u, f)
        os.replace(SHARED + ".%d.tmp" % os.getpid(), SHARED)
    except OSError:
        pass


def usage():
    """{"session": {"percent", "resets"}, "weekly": {...}, "checked": epoch, "error": str|None}.
    Every DirAI server on this account shares one reading (SHARED), so they don't each poll the
    endpoint (it answers 429 to bursts). A failed request keeps the last good numbers, marked
    "stale", and isn't retried for BACKOFF_S."""
    with _lock:
        now = time.time()
        u = _read_shared() or _cache["usage"]
        if u and now - u.get("checked", 0) < (BACKOFF_S if u.get("error") else CACHE_S):
            _cache.update(checked=u["checked"], usage=u)
            return u
        try:
            new = dict(_fetch(), error=None)
        except Exception as e:      # offline, expired token, 429, changed format
            err = "%s: %s" % (type(e).__name__, e)
            if u and u.get("session"):          # keep the last good numbers
                new = dict(u, error=err, stale=True)
            else:
                new = {"error": err}
        new["checked"] = now
        new["stop"] = {"session": SESSION_STOP, "weekly": WEEKLY_STOP}
        _cache.update(checked=now, usage=new)
        _write_shared(new)
        return new


def hold():
    """(until, reason) if new runs should wait for a limit to reset, else (0, "")."""
    u = usage()
    until, reason = 0, ""
    for name, stop, label in (("session", SESSION_STOP, "5-hour session"), ("weekly", WEEKLY_STOP, "weekly")):
        w = u.get(name)
        if w and w["percent"] >= stop and w.get("resets"):
            t = w["resets"] + RESUME_MARGIN_S
            if t > until:
                until, reason = t, "Claude usage at %.0f%% of the %s limit (stop at %d%%)" % (
                    w["percent"], label, stop)
    return until, reason


if __name__ == "__main__":
    print(json.dumps(usage(), indent=1))
    print(hold())
