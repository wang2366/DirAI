"""The words agents.py sends to an agent: its instructions (SYSTEM_PROMPT, GIT_PROMPT), the
starter index.html of a New agent, and the prompts built around the owner's messages (a fresh
session's catch-up, the index.html text they selected, a retry after the usage limit).
"""
import html
import os
import re

import dirai_config

SYSTEM_PROMPT = """You are one of the owner's agents, served from their tree {root}. You are the agent
of the folder {agent_dir}: it is your working directory and the place for your changes, and its
{index_file} is your report, which the owner reads in the browser. You are handling a message the
owner sent you. Do what it asks (fix index.html, rerun scripts, regenerate plots, submit SLURM jobs
for long runs), then end with a short reply for the chat thread: at most 3 lines (about 50 words)
saying what you did or found, linking to where index.html has the details, and what is still open
(job ids). The details (numbers, file lists, reasoning, how you checked) go in index.html: the
section they belong to, and the card's Result and Open. Only what needs the owner's answer may make
the reply longer: a question, a blocked permission with the exact command to run, a rejected push.
Don't describe your edits to index.html in the reply (no "Changes to index.html"
section): the owner sees them in index.html itself, where the server highlights every added or
changed part. Instead, point to the part of index.html you mean with a link [text](#id): the chat
turns it into a link that scrolls the page there. The id is an element's id attribute, or for a
heading without one, its text in lower case with any leading section number dropped and every run of
other characters made "-" ("3. Fit results" is #fit-results). Two more targets: #changes (the parts
this run changed; each click goes to the next) and #file:<name>:<line> (a line of a file in this
folder, as listed at the end of index.html).
Bash permissions are matched per command, and a built-in safety check refuses anything it can't
verify, whatever is granted: command substitution $(...) or backticks, for/while loops (also
"... | while read"), heredocs, and paths with "..". So keep each Bash call to one plain command or
a short && chain of plain commands with literal absolute paths. For anything more (counting,
checking several files, loops), write a small python3 or bash script file in this folder and run
it with "python3 <file>" or "bash <file>"; never pass a script inline (python3 - <<EOF), which asks
every time and can't be granted. Scratch files (patches, one-off scripts) go in {agent_dir}/tmp/,
never /tmp: tmp/ isn't shown on your page, and /tmp isn't yours to write. Always write fully
resolved absolute paths: never "..", which a built-in safety check refuses no matter what is granted.
You can read {scope} (your own area) and the folders granted to you; other folders of the
tree are off limits until the owner names them in a message or allows a blocked read, so if the
work needs one, say which and why in your reply.
Follow the agent conventions below (from {agent_rule_path}); in particular, keep the summary card in
your index.html current (its Open field lists what is unfinished), and give every figure its script
path. To learn what another agent found, run "python3 {card_py} <its folder>" instead of reading its
index.html. If you need another agent of this tree to do something its page doesn't already answer,
draft a request: {note_cmd} ask <its folder> "<what you need>" (see its --help). The owner reads it and
sends it; its answer comes back to you as a message. Don't wait for it in this run.
{git}To delete files or folders, run "{agent_rm} <path>...": it works only inside your folder and
deletes immediately, no trash (plain rm -r / rm -rf stay blocked).
Rules: don't delete anything outside this folder; long or heavy work goes to
SLURM (sbatch), not this process. Don't wait for or poll SLURM jobs (no squeue loops, no sleep):
submit them, say what you submitted, and end your reply. The server watches the jobs you submit and
jobs running in this folder, and messages you here when they have all finished. If the work runs
jobs in other folders (e.g. a job that submits a test sweep in another checkout), list those
folders in this folder's job_dirs.txt (one absolute path per line), so the server keeps waiting
for them and shows them in the status bar of your index.html. {approval} Exception: these are blocked permanently and can
never be granted, so don't ask; give the owner the exact command to run themselves instead: {always_denied}."""


APPROVAL = {
    "allowlist": "Nobody can approve actions while you run: if a permission is denied, do the rest and "
                 "say in your reply exactly what you needed and why; the owner can grant it and resume you.",
    "ask": "An action that isn't already allowed is shown to the owner in your chat and waits for "
           "their answer, which may take a while; that is normal. If the owner denies an action, don't "
           "ask for it again in this run: do the rest, finish, and say in your reply what is still needed.",
}


# Only for agents inside a git repo (a tree need not be one)
GIT_PROMPT = """Git: you may git add / commit / push (this replaces any earlier "never commit" instruction), but
only when the owner's message asks for it (that request is their approval). Run git from your
working directory (your folder, inside the repo) with no "cd ... &&" before it and no "git -C":
a built-in check refuses git after cd, and -C is blocked.
Stage and commit only your folder: "git add -- {agent_dir}", then
'git commit -m "<summary>" -m "<details>" -m "Co-Authored-By: Claude <noreply@anthropic.com>" -- {agent_dir}'
(never "git add -A" or "git add ." at the repo root: other agents share this checkout), then
"git push origin HEAD".
If the push is rejected (the remote moved on), stop and tell the owner; don't pull, rebase or
force. Quote the commit hash and message in your reply.
"""


STARTER_INDEX = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
</head>
<body>
<h1>{title}</h1>
<!-- dirai:card -->
<details id="dirai-card" open>
  <summary>Summary</summary>
  <dl>
    <dt>Objective</dt> <dd>{task}</dd>
    <dt>Inputs</dt>    <dd>not yet known</dd>
    <dt>Outputs</dt>   <dd>not yet known</dd>
    <dt>Result</dt>    <dd>none yet: the agent is working on this task</dd>
    <dt>Open</dt>      <dd>the whole task</dd>
    <dt>Updated</dt>   <dd>{date}</dd>
  </dl>
</details>
<!-- /dirai:card -->
<p><i>Created {date} by New agent; the agent is working on this task and will replace this placeholder.</i></p>
<h2>Task</h2>
<p style="white-space:pre-wrap">{task}</p>
</body>
</html>
"""


NEW_CHAT_MARK = "New chat: the next message starts a fresh session."


# sent once, in the same session, when a run changed index.html and left its summary card incomplete
CARD_FIX = ("Before you finish: the summary card in your index.html (the <!-- dirai:card --> block, see "
            "the agent conventions) needs fixing: %s. Fix only the card, then reply in one line.")


def fresh_prompt(thread, text, keep=6, limit=1500):
    """First message of a new session of an agent that already has a thread: point it at its
    index.html and quote the last few thread entries."""
    recent = [m for m in thread if m.get("text") != NEW_CHAT_MARK][-keep:]
    quoted = "\n\n".join("[%s, %s]\n%s" % (m["role"], m["time"], m["text"][:limit] +
                                             ("..." if len(m["text"]) > limit else ""))
                          for m in recent)
    return ("This is a fresh session of an agent that already has history. Before acting, read this "
            "folder's index.html (its summary card first); the last messages of the earlier conversation follow "
            "for context.\n\n--- earlier messages ---\n%s\n--- end ---\n\nNew message:\n%s" % (quoted, text))


SKIP_RE = re.compile(r"(?is)<(script|style)\b.*?</\1\s*>|<!--.*?-->|<[^>]*>|&#?\w+;|\s+")


SEL_MAX = 4000      # characters of selected index.html text sent with a message


SEL_KEY = 30        # characters (whitespace removed) used to find the selection's start/end in the source


def visible_chars(source):
    """The text of an index.html with tags, scripts and whitespace removed, plus each character's source line."""
    chars, lines, line, pos = [], [], 1, 0
    for m in SKIP_RE.finditer(source):
        for c in source[pos:m.start()]:
            chars.append(c); lines.append(line)
        tok = m.group(0)
        if tok.startswith("&"):
            for c in re.sub(r"\s", "", html.unescape(tok)):
                chars.append(c); lines.append(line)
        line += tok.count("\n")
        pos = m.end()
    for c in source[pos:]:
        chars.append(c); lines.append(line)
    return "".join(chars), lines


def selection_lines(path, text):
    """(first, last) source lines of the selected text in path, or None if it can't be found
    (text built by scripts, or split by markup the browser shows differently)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            visible, lines = visible_chars(f.read())
    except OSError:
        return None
    sel = re.sub(r"\s", "", text)
    head, tail = sel[:SEL_KEY], sel[-SEL_KEY:]
    i = visible.find(head) if head else -1
    if i < 0:
        return None
    j = visible.find(tail, i)
    if j < 0 or j - i > 2 * len(sel) + 200:   # end not found near the start: give the start only
        return lines[i], lines[i]
    return lines[i], lines[j + len(tail) - 1]


def selection_prompt(sel, text):
    """The owner's message with the index.html text they selected quoted in front of it."""
    where = []
    if sel.get("heading"):
        where.append('near the heading "%s"' % sel["heading"])
    if sel.get("lines"):
        a, b = sel["lines"]
        where.append("source line%s %s; read just the lines around %s unless you need more"
                     % ("" if a == b else "s", a if a == b else "%s-%s" % (a, b), "it" if a == b else "them"))
    quoted = "\n".join("> " + l for l in sel["text"].splitlines())
    name = sel.get("file") or "index.html"   # another file: shown raw at the end of index.html
    if sel.get("svg"):   # a diagram index.html shows (svg_inline.py): fixed by its plotting script
        name += ", a diagram in index.html (change the script that draws it, named in its caption)"
    return ("The owner selected this text in %s%s:\n%s\n\nTheir message about it:\n%s"
            % (name, " (%s)" % ", ".join(where) if where else "", quoted, text))


NOTE_CMD = "python3 " + os.path.join(dirai_config.SCRIPTS_DIR, "dirai_note.py")


def _exchange(thread):
    """A note's earlier exchange (notes.py "thread"), quoted for the agent."""
    return "\n".join("  [%s, %s] %s" % ("you" if e.get("who") == "agent" else "owner", e.get("time", ""),
                                        e.get("text", "").replace("\n", "\n  ")) for e in thread)


def notes_prompt(sels, text):
    """The owner's sticky notes (notes.py) as one message: sels is [(n, selection as _selection() gives
    it, the note, its exchange so far)], each quoted the way selection_prompt() quotes a selection;
    text: their message, or "". The agent answers each on the note with dirai_note.py (E1b).
    A request from another agent (proposal 77) comes as (n, None, its entry, []) (notes.receive)."""
    parts, askers = [], []
    for n, sel, note, thread in sels:
        if sel is None:
            askers.append(note["from"])
            parts.append(request_part(n, note))
            continue
        part = "Note %d. %s" % (n, selection_prompt(sel, note or "(no note: just this selection; look at it and fix "
                                                                 "what is wrong or unclear there)"))
        if thread:
            part += ("\n\nThe exchange on this note so far (the owner's last word is what they want now):\n%s"
                     % _exchange(thread))
        parts.append(part)
    nums = ", ".join(str(s[0]) for s in sels)
    # keep "sticky note(s) on your page (note(s) ...)": notes.PROMPT_RE finds the run's notes by it (R3)
    who = ("Agent%s %s asked you, and the owner sent" % ("s" if len(set(askers)) > 1 else "", ", ".join(sorted(set(askers))))
           if askers and len(askers) == len(sels) else "The owner left")
    return ("%s %d sticky note%s on your page (note%s %s). Handle each one.\n\n%s\n\n%s"
            "Answer each note on the note itself, right after you handle it, with:\n"
            "  %s <n> done \"<what you did, and where>\" --at \"#<id of the place on the page>\"\n"
            "  %s <n> open \"<why it is not done, or your question>\"\n"
            "(--at is optional: an element id, or #file:<name>:<line>.) The owner reads these answers on the "
            "notes, so put the per-note details there, not in your reply. Your reply then only says what is "
            "beyond the notes, if anything. The notes are kept in .notes.json in your folder by the server: "
            "don't edit or delete that file; use the command."
            % (who, len(sels), "" if len(sels) == 1 else "s", "" if len(sels) == 1 else "s", nums,
               "\n\n".join(parts), "Their message with the notes:\n%s\n\n" % text if text else "",
               NOTE_CMD, NOTE_CMD)) + (REQUEST_RULES if askers else "")


# what an agent is told with a request from another agent (proposal 77; R13: no leak between askers)
REQUEST_RULES = ("\n\nA request's answer goes to the agent that asked, as you write it: put results on your page "
                 "and link to them (#id) rather than pasting them. Work in your own folder only. Never quote one "
                 "agent's request, or your answer to it, to another agent. If two requests clash, answer both "
                 "open and say what clashes.")


def request_part(n, x):
    """One request from another agent (notes.receive's entry x), quoted in the message."""
    part = "Note %d. A request from agent %s, sent by the owner:\n%s" % (n, x["from"], x["note"])
    if x.get("about") or x.get("text"):
        part += "\n\nIt is about %s on %s's page%s" % (
            x.get("about") or "this text", x["from"], ":\n> " + x["text"].replace("\n", "\n> ") if x.get("text") else ".")
    if x.get("prev"):
        part += ("\n\nThe previous request from %s, and your answer:\n> %s\nYou: %s"
                 % (x["from"], x["prev"]["note"].replace("\n", "\n> "), x["prev"]["answer"]))
    return part


# the answers to an agent's requests, given to it when they are in (agents._deliver)
ANSWERS_PROMPT = ("%s (requests sent by the owner). They are also on your page, on the notes in the Requests "
                  "bar. Go on with your work using them; to follow up or ask again, draft a new request with "
                  "dirai_note.py ask.\n\n%s")


# sent once, in the same session, when a run left some of its sticky notes unanswered (E2a)
NOTES_FIX = ("Before you finish: note%s %s %s no answer yet. Answer each with %s <n> done|open \"<answer>\" "
             "[--at \"#id\"], then reply in one line.")


# several messages the owner queued while a run was going (agents.py, st["inbox"]), sent together when it ended
QUEUED_PROMPT = ("The owner sent these %d messages while you were working on the previous one. Handle them "
                 "together, in order:\n\n%s")


LIMIT_RETRY = ("(Your previous attempt at the message below was cut off by the Claude usage "
               "limit. Check what is already done before continuing.)\n\n")
