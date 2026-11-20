#!/usr/bin/env python3
"""The top server's own DirAI: show whether its git checkout is behind its upstream, and pull it
(design: improvement/pull-button/index.html).

Only for a git checkout with an upstream branch and no remotes.BUILD_FILE: a copy in
~/.local/share/dirai, made by the machine above with Update, carries that file and never pulls.
Only `git pull --ff-only`, never merge, rebase, stash or reset. A pull that can't fast-forward, that
would touch a file with uncommitted changes, or that comes while a commit is in progress (an agent
committing) is refused, with the reason and the commands for the owner to run.

One exception: an upstream whose history was rewritten and that
says so in REWRITE_MAP ("old new" commit ids per line; each rewrite appends its map). When HEAD's
history holds an old commit the upstream no longer has, Pull moves the checkout onto the new
history: `git reset --keep @{u}` if none of HEAD's commits are the owner's own (it refuses to
overwrite uncommitted changes), else `git rebase --onto @{u} <old>` to keep the owner's commits
on top (only with no uncommitted changes; a conflict is aborted). Without a map, a checkout that
shares no history with its upstream is refused with the commands to move it by hand. After a pull the
server restarts once no agent run is going (a restart stops runs; queued messages and SLURM waits
survive it).

  self_update.py status     what the Machines box shows, as JSON
  self_update.py pull       the checks and the pull (DirAI pull), then waits to restart the tree's server
"""
import json
import os
import subprocess
import sys
import threading
import time

import dirai_config

BUILD_FILE = "BUILD"        # remotes.BUILD_FILE: present in a copy, never in a checkout
FETCH_S = 1800              # background git fetch at most this often (and when Machines is opened)
FETCH_TIMEOUT_S = 30
PULL_TIMEOUT_S = 60
IDLE_CHECK_S = 5
INCOMING_MAX = 20
REWRITE_MAP = "lib/history_rewrite.map"     # in the upstream: old -> new commit ids of history rewrites
# git must never wait for a password or a host-key answer: no terminal behind the server
GIT_ENV = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_SSH_COMMAND="ssh -o BatchMode=yes")

_state = {"fetched": 0, "fetch_error": "", "fetching": False, "pulled": "", "note": ""}
_lock = threading.Lock()


def git(tool, *args, timeout=15):
    """(exit code, stdout, stderr) of git in tool; code -1 if it couldn't run or timed out."""
    try:
        r = subprocess.run(["git", "-C", tool] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=timeout, env=GIT_ENV)
        # rstrip only: git status --porcelain starts lines with a space (" M path")
        return r.returncode, r.stdout.rstrip(), r.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, "", str(e)


def upstream(tool=dirai_config.TOOL_DIR):
    """The upstream branch (e.g. origin/main) if tool is a pullable checkout, else None."""
    if os.path.exists(os.path.join(tool, BUILD_FILE)):
        return None
    code, top, _ = git(tool, "rev-parse", "--show-toplevel")
    if code or os.path.realpath(top) != os.path.realpath(tool):
        return None
    code, up, _ = git(tool, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    return up if not code and up else None


def fetch(tool=dirai_config.TOOL_DIR):
    """git fetch the upstream's remote, in the background unless wait; at most one at a time."""
    with _lock:
        if _state["fetching"]:
            return
        _state["fetching"] = True

    def go():
        try:
            up = upstream(tool)
            code, _, err = git(tool, "fetch", "--quiet", up.split("/", 1)[0], timeout=FETCH_TIMEOUT_S) if up else (0, "", "")
            with _lock:
                _state["fetched"], _state["fetch_error"] = time.time(), (err.splitlines() or ["git fetch failed"])[-1] if code else ""
        finally:
            with _lock:
                _state["fetching"] = False
    threading.Thread(target=go, daemon=True).start()


def rewritten(tool=dirai_config.TOOL_DIR):
    """If the upstream's history was rewritten under HEAD (REWRITE_MAP in @{u} maps a commit of
    HEAD's history, one @{u} no longer has, to a commit @{u} has): (old, new, own), own = the commits
    on top of old (the owner's); else None."""
    code, text, _ = git(tool, "show", "@{u}:" + REWRITE_MAP)
    if code:
        return None
    mapping = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and all(len(p) == 40 for p in parts) and parts[0] != parts[1]:
            mapping[parts[0]] = parts[1]
    code, revs, _ = git(tool, "rev-list", "HEAD", timeout=30)
    old = next((r for r in revs.splitlines() if r in mapping), None) if not code else None
    if not old or not git(tool, "merge-base", "--is-ancestor", old, "@{u}")[0]:
        return None
    new = mapping[old]
    if git(tool, "merge-base", "--is-ancestor", new, "@{u}")[0]:
        return None
    _, own, _ = git(tool, "rev-list", "--count", old + "..HEAD")
    return old, new, int(own or 0)


def status(tool=dirai_config.TOOL_DIR, refresh=False):
    """What this server's Machines box shows: {"pull": False} for a copy or a checkout without an
    upstream; else branch, upstream, commit, ahead/behind, the incoming commits, the last fetch."""
    up = upstream(tool)
    if not up:
        return {"pull": False}
    if refresh or time.time() - _state["fetched"] > FETCH_S:
        fetch(tool)
    _, branch, _ = git(tool, "rev-parse", "--abbrev-ref", "HEAD")
    _, commit, _ = git(tool, "rev-parse", "--short", "HEAD")
    code, counts, _ = git(tool, "rev-list", "--left-right", "--count", "HEAD...@{u}")
    ahead, behind = (int(x) for x in counts.split()) if not code and len(counts.split()) == 2 else (0, 0)
    _, log, _ = git(tool, "log", "--oneline", "-n", str(INCOMING_MAX), "HEAD..@{u}")
    rw = rewritten(tool) if ahead and behind else None
    with _lock:
        s = dict(_state)
    return {"pull": True, "branch": branch, "upstream": up, "commit": commit, "ahead": ahead, "behind": behind,
            "rewritten": {"old": rw[0], "new": rw[1], "own": rw[2]} if rw else None,
            "incoming": log.splitlines() if behind else [], "fetched": s["fetched"], "fetching": s["fetching"],
            "fetch_error": s["fetch_error"], "pulled": s["pulled"], "note": s["note"]}


def checks(tool=dirai_config.TOOL_DIR):
    """None if a fast-forward pull can go now, else (why, commands for the owner)."""
    st = status(tool)
    if not st["pull"]:
        return "this DirAI isn't a git checkout with an upstream branch (a copy is updated from the machine above)", []
    if os.path.exists(os.path.join(tool, ".git", "index.lock")):
        return "a git command is running in the checkout (an agent committing?); try again in a minute", []
    if not st["behind"]:
        return "already up to date with %s" % st["upstream"], []
    here = ["cd %s" % tool]
    rw = st["rewritten"]
    if rw:
        _, dirty, _ = git(tool, "status", "--porcelain", "--untracked-files=no")
        if rw["own"] and dirty:
            return ("%s's history was rewritten; moving your %d commit%s onto it needs no uncommitted changes"
                    % (st["upstream"], rw["own"], "" if rw["own"] == 1 else "s"),
                    here + ["git status", "git stash", "# press Pull again, then: git stash pop"])
        return None
    if st["ahead"] and git(tool, "merge-base", "HEAD", "@{u}")[0]:
        return ("this checkout shares no history with %s (its history was rewritten?): not a fast-forward"
                % st["upstream"],
                here + ["git log --oneline -n %d   # your commits? none: then" % st["ahead"],
                        "git reset --keep @{u}   # refuses to overwrite uncommitted changes",
                        "# never pull --rebase or merge here: that brings the old history back"])
    if st["ahead"]:
        return ("this checkout has %d commit%s that %s doesn't, and %s has %d new: not a fast-forward"
                % (st["ahead"], "" if st["ahead"] == 1 else "s", st["upstream"], st["upstream"], st["behind"]),
                here + ["git log --oneline --graph HEAD...@{u}", "git pull --rebase   # or merge, as you prefer"])
    _, incoming, _ = git(tool, "diff", "--name-only", "HEAD", "@{u}")
    _, porcelain, _ = git(tool, "status", "--porcelain", "--untracked-files=all")
    changed = {line[3:].split(" -> ")[-1].strip('"') for line in porcelain.splitlines() if len(line) > 3}
    clash = sorted(changed & set(incoming.splitlines()))
    if clash:
        return ("the incoming commits change %d file%s that have uncommitted changes here: %s"
                % (len(clash), "" if len(clash) == 1 else "s", ", ".join(clash[:8]) + (" …" if len(clash) > 8 else "")),
                here + ["git status", "git diff -- " + " ".join(clash[:8]),
                        "# commit or move those changes, then press Pull again"])
    return None


def pull(tool=dirai_config.TOOL_DIR):
    """The checks, then git pull --ff-only. {"ok", "pulled": "old → new", "incoming"} or
    {"error", "commands"}."""
    why = checks(tool)
    if why:
        return {"error": "Not pulled: " + why[0], "commands": why[1]}
    st = status(tool)
    old = st["commit"]
    rw = st["rewritten"]
    if rw and rw["own"]:
        code, _, err = git(tool, "rebase", "--quiet", "--onto", "@{u}", rw["old"], timeout=PULL_TIMEOUT_S)
        if code:
            git(tool, "rebase", "--abort")
            return {"error": "%s's history was rewritten; moving your %d commit%s onto it conflicted (undone): %s"
                    % (st["upstream"], rw["own"], "" if rw["own"] == 1 else "s", (err.splitlines() or ["?"])[-1]),
                    "commands": ["cd %s" % tool, "git rebase --onto @{u} %s   # then resolve the conflicts" % rw["old"]]}
    elif rw:
        code, _, err = git(tool, "reset", "--quiet", "--keep", "@{u}")
        if code:
            return {"error": "%s's history was rewritten; not moved onto it: %s"
                    % (st["upstream"], (err.splitlines() or ["?"])[-1]),
                    "commands": ["cd %s" % tool, "git status", "# commit or move those changes, then press Pull again"]}
    else:
        code, _, err = git(tool, "pull", "--ff-only", "--quiet", timeout=PULL_TIMEOUT_S)
    if code:
        return {"error": "git pull --ff-only failed: " + ((err.splitlines() or ["?"])[-1]),
                "commands": ["cd %s" % tool, "git status", "git pull --ff-only"]}
    _, new, _ = git(tool, "rev-parse", "--short", "HEAD")
    with _lock:
        _state["pulled"], _state["fetched"], _state["fetch_error"] = "%s → %s" % (old, new), time.time(), ""
    return {"ok": True, "pulled": "%s → %s" % (old, new), "incoming": st["incoming"]}


def restart_when_idle(busy, restart):
    """After a pull: call restart() once busy() is false (no agent run going), checking every
    IDLE_CHECK_S; the note on the box says what it waits for. In a thread; one at a time."""
    with _lock:
        if _state.get("waiting"):
            return
        _state["waiting"] = True

    def go():
        try:
            while True:
                n = busy()
                if not n:
                    break
                with _lock:
                    _state["note"] = "restart waits: %d agent run%s going" % (n, "" if n == 1 else "s")
                time.sleep(IDLE_CHECK_S)
            with _lock:
                _state["note"] = "restarting…"
            out = restart() or {}
            if out.get("error"):
                with _lock:
                    _state["note"] = "pulled, but not restarted: %s" % out["error"]
        finally:
            with _lock:
                _state["waiting"] = False
    threading.Thread(target=go, daemon=True).start()


def tree_runs(root):
    """Agent runs going in the tree, from its agents.json (for DirAI pull, outside the server)."""
    data = dirai_config.load_json(os.path.join(root, "www", "agents.json"), {}) or {}
    return sum(1 for st in data.values() if st.get("status") == "working" and not st.get("job_wait"))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        print(json.dumps(status(), indent=1))
        return 0
    if cmd == "pull":
        out = pull()
        if out.get("error"):
            print(out["error"], file=sys.stderr)
            for c in out.get("commands", []):
                print("  " + c, file=sys.stderr)
            return 1
        print("Pulled DirAI %s:" % out["pulled"])
        for line in out["incoming"]:
            print("  " + line)
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
