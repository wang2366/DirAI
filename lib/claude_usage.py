"""Claude plan usage (the numbers Claude Code's /usage shows), for agents.py and the agent list.

Reads https://api.anthropic.com/api/oauth/usage with Claude Code's own login token from
~/.claude/.credentials.json (Linux), or on macOS, where Claude Code keeps it in the login
Keychain, from the "Claude Code-credentials" item. Asking costs no tokens. The token is only read, never refreshed
here: Claude Code refreshes it whenever it runs. If the token has expired or the request fails,
usage is unknown and nothing is held back.

This is the endpoint Claude Code itself uses; it is not a documented API and may change.
"""
import calendar
import json
import math
import os
import subprocess
import sys
import threading
import time
import urllib.request

import dirai_config

CREDENTIALS = os.path.join(dirai_config.CLAUDE_DIR, ".credentials.json")
KEYCHAIN_ITEM = "Claude Code-credentials"   # macOS: same JSON as the Linux file
URL = "https://api.anthropic.com/api/oauth/usage"
CACHE_S = 60                # ask at most once a minute, across all DirAI servers (shared file)
BACKOFF_S = 300             # after a refused request (e.g. 429), wait this long before asking again
SHARED = os.path.join(dirai_config.CONFIG_DIR, "usage.json")
PAUSE_FILE = os.path.join(dirai_config.CONFIG_DIR, "usage_stop.json")
HISTORY = os.path.join(dirai_config.CONFIG_DIR, "usage_history.jsonl")   # one sample per line, for the charts
HISTORY_KEEP_S = 8 * 86400      # a week plus a day
HISTORY_GAP_S = 600             # a sample is kept when a value changed, or after this long without one
# no new runs at or above this % of the 5-hour session limit / of the weekly limit, unless the
# owner set other levels (the sliders on the agent list, saved in PAUSE_FILE for all their trees). With
# weekly auto on (the default) the weekly level follows the day instead: n/7 on day n of the week.
DEFAULT_PAUSE = {"session": 100, "weekly": 100}
RESUME_MARGIN_S = 120
DAY_S, WEEK_S = 86400, 7 * 86400       # start again this long after the limit resets

_lock = threading.Lock()
_cache = {"usage": None}


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


def _credentials():
    """Claude Code's stored login: the credentials file, else (macOS) the Keychain item."""
    if os.path.exists(CREDENTIALS) or sys.platform != "darwin":
        with open(CREDENTIALS) as f:
            return json.load(f)
    p = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_ITEM,
                        "-a", os.environ.get("USER", ""), "-w"],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=10)
    if p.returncode != 0:
        raise OSError("no %r Keychain item (log in to Claude Code first): %s" % (KEYCHAIN_ITEM, p.stderr.strip()))
    return json.loads(p.stdout)


def _fetch():
    login = _credentials()["claudeAiOauth"]
    expires = (login.get("expiresAt") or 0) / 1000
    if expires and expires < time.time():     # asking with it only gets refusals (and 429s)
        raise OSError("Claude Code's login token here expired %d min ago; it is renewed whenever Claude Code "
                      "runs on this machine (any agent run, or `claude` once)" % ((time.time() - expires) // 60))
    token = login["accessToken"]
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


def settings():
    """The owner's levels: {"session": %, "weekly": %, "weekly_auto": bool} (DEFAULT_STOP and
    weekly_auto on, unless set on the agent list)."""
    out = dict(DEFAULT_PAUSE, weekly_auto=True)
    try:
        saved = dirai_config.load_json(PAUSE_FILE, {})
        out.update((k, int(v)) for k, v in saved.items() if k in DEFAULT_PAUSE and 1 <= int(v) <= 100)
        if isinstance(saved.get("weekly_auto"), bool):
            out["weekly_auto"] = saved["weekly_auto"]
    except (ValueError, TypeError, AttributeError):
        pass
    return out


def pause_levels():
    """{"session": %, "weekly": %}: the levels set by hand."""
    return {k: v for k, v in settings().items() if k in DEFAULT_PAUSE}


def _save(**changes):
    with _lock:
        cur = settings()
        cur.update(changes)
        dirai_config.save_json(PAUSE_FILE, cur)


def set_pause_level(name, percent):
    """Save one stop level (1-100); setting the weekly one by hand turns weekly auto off. False if
    name or percent is invalid."""
    try:
        percent = int(percent)
    except (TypeError, ValueError):
        return False
    if name not in DEFAULT_PAUSE or not 1 <= percent <= 100:
        return False
    _save(**dict({name: percent}, **({"weekly_auto": False} if name == "weekly" else {})))
    return True


def set_weekly_auto(on):
    _save(weekly_auto=bool(on))
    return True


def weekly_pace(resets, now=None):
    """Weekly auto level: on day n of the 7-day window that ends at resets, n/7 of the limit.
    Returns (percent, n, when day n ends)."""
    now = time.time() if now is None else now
    start = resets - WEEK_S
    n = min(7, max(1, int(math.ceil((now - start) / DAY_S))))
    return 100.0 * n / 7, n, min(start + n * DAY_S, resets)


def levels(u):
    """The levels in force for reading u: {"session": %, "weekly": %}, plus "weekly_auto" (None, or
    {"day": n, "until": epoch} while the weekly level follows the day of the week)."""
    st = settings()
    out = {"session": st["session"], "weekly": st["weekly"], "weekly_auto": None}
    w = u.get("weekly") or {}
    if st["weekly_auto"] and w.get("resets"):
        pct, n, until = weekly_pace(w["resets"])
        out["weekly"], out["weekly_auto"] = round(pct, 1), {"day": n, "until": until}
    elif st["weekly_auto"]:
        out["weekly_auto"] = {"day": None, "until": None}   # on, but no reset time to pace by
    return out


def _record(u, now):
    """Append a sample {t, s, w, sr, wr} (session %, weekly %, their reset times) to HISTORY when a
    value changed or HISTORY_GAP_S passed; drop samples older than HISTORY_KEEP_S."""
    s, w = u.get("session") or {}, u.get("weekly") or {}
    row = {"t": int(now), "s": s.get("percent"), "w": w.get("percent"), "sr": s.get("resets"), "wr": w.get("resets")}
    rows = history()
    last = rows[-1] if rows else None
    if last and last["s"] == row["s"] and last["w"] == row["w"] and now - last["t"] < HISTORY_GAP_S:
        return
    rows = [r for r in rows if now - r["t"] < HISTORY_KEEP_S]
    rows.append(row)
    os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
    tmp = HISTORY + ".tmp"
    with open(tmp, "w") as f:
        f.write("".join(json.dumps(r) + "\n" for r in rows))
    os.replace(tmp, HISTORY)


def history():
    """The saved samples, oldest first: [{"t", "s", "w", "sr", "wr"}, ...] (empty if none)."""
    rows = []
    try:
        with open(HISTORY) as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    return rows


def usage():
    """{"session": {"percent", "resets"}, "weekly": {...}, "checked": epoch, "error": str|None}.
    Every DirAI server on this account shares one reading (SHARED), so they don't each poll the
    endpoint (it answers 429 to bursts). A failed request keeps the last good numbers, marked
    "stale", and isn't retried for BACKOFF_S."""
    with _lock:
        now = time.time()
        u = dirai_config.load_json(SHARED, None) or _cache["usage"]
        if u and now - u.get("checked", 0) < (BACKOFF_S if u.get("error") else CACHE_S):
            _cache["usage"] = u
            return dict(u, stop=levels(u))
        try:
            new = dict(_fetch(), error=None)
        except Exception as e:      # offline, expired token, 429, changed format
            err = "%s: %s" % (type(e).__name__, e)
            if u and u.get("session"):          # keep the last good numbers
                new = dict(u, error=err, stale=True)
            else:
                new = {"error": err}
        new["checked"] = now
        _cache["usage"] = new
        try:
            dirai_config.save_json(SHARED, new)
            if not new.get("error"):
                _record(new, now)
        except OSError:
            pass
        return dict(new, stop=levels(new))


def pause_until():
    """(until, reason) if new runs should wait for a limit to reset, else (0, "")."""
    u = usage()
    until, reason = 0, ""
    auto = u["stop"].get("weekly_auto") or {}
    for name, label in (("session", "5-hour session"), ("weekly", "weekly")):
        w, stop = u.get(name), u["stop"][name]
        if w and w["percent"] >= stop and w.get("resets"):
            paced = name == "weekly" and auto.get("until")
            # paced: wait for the next day of the week (its level is a seventh higher), not the reset
            t = (auto["until"] if paced else w["resets"]) + RESUME_MARGIN_S
            if t > until:
                until, reason = t, "Claude usage at %.0f%% of the %s limit (pause at %.0f%%%s)" % (
                    w["percent"], label, stop, ", auto: day %d of 7" % auto["day"] if paced else "")
    return until, reason


if __name__ == "__main__":
    print(json.dumps(usage(), indent=1))
    print(pause_until())
