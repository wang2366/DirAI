"""What an agent may do (agents.py): the allow and deny lists every run gets, the read grants a
message implies, the grants an agent shares with the agents that list it as a colleague, and turning
a refused action into the allow rule that grants exactly it (for the panel's Allow / Always allow).
"""
import hashlib
import json
import os
import re
import shlex
import shutil
from urllib.parse import urlparse

import dirai_config
from dirai_config import load_json, within

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
    # deleting: only via agent_rm.sh, which refuses anything outside the agent's folder
    "Bash(%s/agent_rm.sh:*)" % dirai_config.SCRIPTS_DIR,
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
    "Bash(git reset:*)", "Bash(git stash:*)",   # checkout/restore: grantable, exact command only
    "Bash(git rebase:*)", "Bash(git clean:*)", "Bash(git commit --amend:*)",
    "Bash(git -C:*)",   # would slip past the rules above (git -C x push --force)
    "Bash(rm -rf:*)", "Bash(rm -r:*)", "Bash(sudo:*)",
]


def mcp_config(agent_dir, root):
    """An --mcp-config file with the owner's MCP servers for a run in agent_dir, or None.
    --restricted ignores ~/.claude.json, so the servers Claude Code would load in that folder are
    passed explicitly: user scope, local scope of the folder or any folder above it, and the
    .mcp.json files there. Their tools are not pre-allowed: each needs a grant or the owner's answer.
    claude.ai connectors can't be passed this way."""
    cfg = load_json(os.path.expanduser("~/.claude.json"), {})
    servers = dict(cfg.get("mcpServers", {}))
    ups, d = [], agent_dir
    while d not in ups:
        ups.append(d)
        d = os.path.dirname(d)
    for d in reversed(ups):   # nearer folders override farther ones
        servers.update(load_json(os.path.join(d, ".mcp.json"), {}).get("mcpServers", {}))
        servers.update(cfg.get("projects", {}).get(d, {}).get("mcpServers", {}))
    if not servers:
        return None
    text = json.dumps({"mcpServers": servers}, sort_keys=True)
    path = os.path.join(dirai_config.data_dir(root), "mcp-%s.json" % hashlib.sha1(text.encode()).hexdigest()[:12])
    if not os.path.exists(path):   # may hold tokens (headers, env): owner-only
        fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(path + ".tmp", path)
    return path


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


def request_denial(req):
    """A can_use_tool permission prompt in the shape of a permission_denials entry."""
    return {"tool_name": req.get("tool_name", ""), "tool_input": req.get("input") or {}}


# A refused command is granted as "program subcommand:*" (basecamp attachments download 123 ... ->
# basecamp attachments:*), so the grant also covers the next call, and is worth sharing with
# colleagues. Commands whose second word isn't a subcommand (a flag, a path, a quoted string), and
# these programs, stay exact: a prefix of them would allow too much.
EXACT_ONLY = {"rm", "rmdir", "sudo", "su", "chmod", "chown", "kill", "pkill", "killall", "curl", "wget",
              "ssh", "scp", "rsync", "git", "dd", "mkfs", "truncate", "shred"}
SUBCMD_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
INTERPRETER_RE = re.compile(r"^(python[0-9.]*|bash|sh)$")
USER_BIN = os.path.expanduser("~/.local/bin") + "/"


def piece_rules(piece):
    """Allow rules for one refused command: its prefix rule ("prog sub:*"), for a program in
    ~/.local/bin also with the full path (Claude matches the text as written), else the exact command."""
    try:
        words = shlex.split(piece) if "\n" not in piece else []
    except ValueError:      # unbalanced quotes
        words = []
    # an interpreter (a venv's python): its script changes each time, so the grant is the interpreter,
    # no wider than the defaults' Bash(python3:*); an inline script stays exact, and unusable()
    if len(words) >= 2 and INTERPRETER_RE.match(os.path.basename(words[0])) and not is_heredoc(piece):
        return ["Bash(%s:*)" % words[0]]
    if len(words) < 2 or not SUBCMD_RE.match(words[1]):
        return ["Bash(%s)" % piece]
    prog = words[0]
    for pre in (USER_BIN, "~/.local/bin/", "$HOME/.local/bin/"):
        if prog.startswith(pre) and "/" not in prog[len(pre):]:
            prog = prog[len(pre):]
    if os.path.basename(prog) in EXACT_ONLY:
        return ["Bash(%s)" % piece]
    rules = ["Bash(%s %s:*)" % (prog, words[1])]
    if "/" not in prog and os.path.isfile(USER_BIN + prog):
        rules.append("Bash(%s%s %s:*)" % (USER_BIN, prog, words[1]))
    return rules


def denial_rules(d):
    """Allow rules that grant the denied action: for a command, those of each piece of the chain
    that the defaults don't already allow."""
    if d.get("tool_name") == "Bash":
        rules = []
        for p in split_command((d.get("tool_input") or {}).get("command", "")):
            if not any(rule_covers(r, "Bash", p) for r in DEFAULT_ALLOW):
                rules += [r for r in piece_rules(p) if r not in rules]
        return rules
    return [denial_rule(d)]


# A Bash rule that can never match a later command: a piece of an inline script (heredoc lines, HTML,
# docstrings) or a whole script body. "Always allow" doesn't keep them (Allow once still runs them),
# and the Permissions list marks the ones kept before.
ONCE_ONLY_MAX = 200     # characters: a longer command is a one-off
SHELL_WORDS = {"cd", "export", "set", "unset", "source", ".", "[", "[[", "test", "true", "false", "echo",
               "printf", "for", "while", "until", "if", "case", "type", "exec", "eval", "alias", "ulimit",
               "umask", "wait", "trap", "read", "time", "nohup", "command", "builtin", "pushd", "popd", "!"}
ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
SCRIPT_HINT = ("Write such a script to a file in your folder (one-off ones in its tmp/) and run it with "
               "\"python3 <file>\" or \"bash <file>\": an inline script (heredoc) asks every time, and can't be granted.")


def is_heredoc(command):
    return "<<" in command


def unusable(rule):
    """Why the allow rule can never match a later command, or "" if it may."""
    if not (rule.startswith("Bash(") and rule.endswith(")")):
        return ""
    cmd = rule[5:-1]
    cmd = cmd[:-2] if cmd.endswith(":*") else cmd
    if "\n" in cmd or is_heredoc(cmd):
        return "a whole inline script"
    if len(cmd) > ONCE_ONLY_MAX:
        return "over %d characters, a one-off" % ONCE_ONLY_MAX
    words = cmd.split()
    while words and ENV_RE.match(words[0]):
        words.pop(0)
    if not words:
        return "no command"
    first = words[0]
    if first in SHELL_WORDS or ("/" in first and first[0] not in "<\"'#") or shutil.which(first):
        return ""
    return "starts with %s, which isn't a program: a line of a script" % first[:20]


def keepable(rules):
    """The rules "Always allow" keeps: the ones a later command may match."""
    return [r for r in rules if not unusable(r)]


def rule_covers(rule, tool, text):
    """True if the allow rule covers a tool call: Bash(x:*) any command that is x or starts with
    "x "; any other rule only the exact action (a Bash piece's text, or the tool's own rule)."""
    if rule.startswith("Bash(") and rule.endswith(":*)"):
        prefix = rule[5:-3]
        return tool == "Bash" and (text == prefix or text.startswith(prefix + " "))
    return rule == ("Bash(%s)" % text if tool == "Bash" else text)


def covered(rules, d):
    """True if the rules already allow the denied action (every piece of a chained command)."""
    if d.get("tool_name") == "Bash":
        pieces = split_command((d.get("tool_input") or {}).get("command", ""))
        return bool(pieces) and all(any(rule_covers(r, "Bash", p) for r in rules) for p in pieces)
    want = denial_rule(d)
    return any(rule_covers(r, d.get("tool_name"), want) for r in rules)


def denial_rule(d):
    """Turn a non-Bash permission_denials entry into an allow rule granting exactly that action."""
    tool, inp = d.get("tool_name", ""), d.get("tool_input", {}) or {}
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        path = inp.get("file_path") or inp.get("notebook_path") or ""
        return "Edit(/%s)" % path if path.startswith("/") else "Edit(%s)" % path
    if tool in ("Read", "Grep", "Glob"):
        # blocked by the working-folder limit: grant read access to the folder
        path = inp.get("file_path") or inp.get("path") or ""
        if path.startswith("/"):
            folder = path if os.path.isdir(path) else os.path.dirname(path)
            return "Read(/%s/**)" % folder
    if tool == "WebFetch" and inp.get("url"):
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


# /abs/path, ~/path or tree/relative/path (a bare word never counts: it needs a slash)
PATH_TOKEN_RE = re.compile(r"""(?:~/|/)[\w.+-]+(?:/[\w.+-]*)*|[\w.+-]+(?:/[\w.+-]*)+""")


def path_grants(text, root, scope):
    """Read rules for the tree folders the owner names in a comment (the request is the approval):
    absolute, ~/ or tree-relative paths that exist inside the tree and outside the agent's scope.
    A named file grants its folder."""
    rules = []
    for tok in PATH_TOKEN_RE.findall(text):
        tok = tok.rstrip(".")
        path = os.path.expanduser(tok) if tok.startswith("~") else tok
        path = os.path.realpath(path if path.startswith("/") else os.path.join(root, path))
        if not os.path.exists(path):
            continue
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        if not within(folder, root):
            continue   # outside the tree: dirai.json "read_dirs", or Allow on a blocked read
        if within(folder, scope):
            continue   # already readable
        rule = "Read(/%s/**)" % folder
        if rule not in rules:
            rules.append(rule)
    return rules


def shared_grants(grants, mode="read"):
    """The part of a colleague's grants an agent gets too: for a read-only colleague all but edits,
    so its folder and files stay read-only; for a writable one ("own", "all") all of them (for "own",
    the run's --disallowedTools still keeps the agents inside it read-only)."""
    return list(grants) if mode in ("own", "all") else [r for r in grants if not r.startswith("Edit(")]


def extra_dirs(allow, agent_dir, read_dirs):
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
                  and not any(d == r or d.startswith(r + "/") for r in read_dirs + [agent_dir]))


def describe_denial(d):
    tool, inp = d.get("tool_name", ""), d.get("tool_input", {}) or {}
    detail = inp.get("command") or inp.get("file_path") or inp.get("url") or json.dumps(inp)[:200]
    return "%s: %s" % (tool, detail)
