"""The words review.py sends to a page's assistant: its instructions (SYSTEM_PROMPT, GIT_PROMPT),
the starter page of a New agent, and the prompts built around the owner's messages (a fresh
session's catch-up, the page text they selected, a retry after the usage limit).
"""
import html
import re

SYSTEM_PROMPT = """You are handling a review comment the owner left on one of their HTML report pages,
served from their tree {root}. The page is {page_file}; its
folder ({page_dir}) is your working directory and the place for your changes. Do what the comment
asks (fix the page, rerun scripts, regenerate plots, submit SLURM jobs for long runs), then end
with a short reply for the comment thread: what you found, what you ran, and anything still open.
Don't describe your edits to the page in the reply (no "Page changes" section): the owner sees them
on the page itself, where the server highlights every added or changed part.
Bash permissions are matched per command, and a built-in safety check refuses anything it can't
verify, whatever is granted: command substitution $(...) or backticks, for/while loops (also
"... | while read"), heredocs, and paths with "..". So keep each Bash call to one plain command or
a short && chain of plain commands with literal absolute paths. For anything more (counting,
checking several files, loops), write a small python3 or bash script file in this folder and run
it with "python3 <file>" or "bash <file>". Always write fully
resolved absolute paths: never "..", which a built-in safety check refuses no matter what is granted.
You can read {scope} (this page's own area) and the folders granted to you; other folders of the
tree are off limits until the owner names them in a comment or allows a blocked read, so if the
work needs one, say which and why in your reply.
Follow the page conventions below (from {pages_md_path}); in particular, keep the page's summary
card current (its Open field lists what is unfinished), and give every figure its script path. To learn
what another page found, run "python3 {card_py} <its folder>" instead of reading its index.html.
{git}To delete files or folders, run "{page_rm} <path>...": it works only inside this page folder and
deletes immediately, no trash (plain rm -r / rm -rf stay blocked).
Rules: don't delete anything outside this folder; long or heavy work goes to
SLURM (sbatch), not this process. Don't wait for or poll SLURM jobs (no squeue loops, no sleep):
submit them, say what you submitted, and end your reply. The server watches the jobs you submit and
jobs running in this folder, and messages you here when they have all finished. If the work runs
jobs in other folders (e.g. a job that submits a test sweep in another checkout), list those
folders in this folder's job_dirs.txt (one absolute path per line), so the server keeps waiting
for them and shows them in the page's status bar. {approval} Exception: these are blocked permanently and can
never be granted, so don't ask; give the owner the exact command to run themselves instead: {always_denied}."""


APPROVAL = {
    "allowlist": "Nobody can approve actions while you run: if a permission is denied, do the rest and "
                 "say in your reply exactly what you needed and why; the owner can grant it and resume you.",
    "ask": "An action that isn't already allowed is shown to the owner in the page chat and waits for "
           "their answer, which may take a while; that is normal. If the owner denies an action, don't "
           "ask for it again in this run: do the rest, finish, and say in your reply what is still needed.",
}


# Only for pages inside a git repo (a tree need not be one)
GIT_PROMPT = """Git: you may git add / commit / push (this replaces any earlier "never commit" instruction), but
only when the owner's message asks for it (that request is their approval). Run git from your
working directory (this page folder, inside the repo) with no "cd ... &&" before it and no "git -C":
a built-in check refuses git after cd, and -C is blocked.
Stage and commit only this page's folder: "git add -- {page_dir}", then
'git commit -m "<summary>" -m "<details>" -m "Co-Authored-By: Claude <noreply@anthropic.com>" -- {page_dir}'
(never "git add -A" or "git add ." at the repo root: other agents share this checkout), then
"git push origin HEAD".
If the push is rejected (the remote moved on), stop and tell the owner; don't pull, rebase or
force. Quote the commit hash and message in your reply.
"""


STARTER_PAGE = """<!doctype html>
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
    <dt>Result</dt>    <dd>none yet: the AI assistant is working on this task</dd>
    <dt>Open</dt>      <dd>the whole task</dd>
    <dt>Updated</dt>   <dd>{date}</dd>
  </dl>
</details>
<!-- /dirai:card -->
<p><i>Created {date} by New agent; the AI assistant is working on this task and will replace this page.</i></p>
<h2>Task</h2>
<p style="white-space:pre-wrap">{task}</p>
</body>
</html>
"""


NEW_CHAT_MARK = "New chat: the next message starts a fresh session."


# sent once, in the same session, when a run changed the page and left its summary card incomplete
CARD_FIX = ("Before you finish: this page's summary card (the <!-- dirai:card --> block, see the page "
            "conventions) needs fixing: %s. Fix only the card, then reply in one line.")


def fresh_prompt(thread, text, keep=6, limit=1500):
    """First message of a new session on a page that already has a thread: point it at the
    page's state and quote the last few thread entries."""
    recent = [m for m in thread if m.get("text") != NEW_CHAT_MARK][-keep:]
    quoted = "\n\n".join("[%s, %s]\n%s" % (m["role"], m["time"], m["text"][:limit] +
                                             ("..." if len(m["text"]) > limit else ""))
                          for m in recent)
    return ("This is a fresh session on a page that already has history. Before acting, read this "
            "folder's index.html (its summary card first); the last messages of the earlier conversation follow "
            "for context.\n\n--- earlier messages ---\n%s\n--- end ---\n\nNew message:\n%s" % (quoted, text))


SKIP_RE = re.compile(r"(?is)<(script|style)\b.*?</\1\s*>|<!--.*?-->|<[^>]*>|&#?\w+;|\s+")


SEL_MAX = 4000      # characters of selected page text sent with a message


SEL_KEY = 30        # characters (whitespace removed) used to find the selection's start/end in the source


def visible_chars(source):
    """The page's text with tags, scripts and whitespace removed, plus each character's source line."""
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
    """(first, last) source lines of the selected page text in path, or None if it can't be found
    (text built by scripts, or split by markup the browser shows differently)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            page, lines = visible_chars(f.read())
    except OSError:
        return None
    sel = re.sub(r"\s", "", text)
    head, tail = sel[:SEL_KEY], sel[-SEL_KEY:]
    i = page.find(head) if head else -1
    if i < 0:
        return None
    j = page.find(tail, i)
    if j < 0 or j - i > 2 * len(sel) + 200:   # end not found near the start: give the start only
        return lines[i], lines[i]
    return lines[i], lines[j + len(tail) - 1]


def selection_prompt(sel, text):
    """The owner's message with the page text they selected quoted in front of it."""
    where = ["index.html"]
    if sel.get("heading"):
        where.append('near the heading "%s"' % sel["heading"])
    if sel.get("lines"):
        a, b = sel["lines"]
        where.append("source line%s %s; read just the lines around %s unless you need more"
                     % ("" if a == b else "s", a if a == b else "%s-%s" % (a, b), "it" if a == b else "them"))
    quoted = "\n".join("> " + l for l in sel["text"].splitlines())
    return ("The owner selected this text on the page (%s):\n%s\n\nTheir message about it:\n%s"
            % (", ".join(where), quoted, text))


LIMIT_RETRY = ("(Your previous attempt at the message below was cut off by the Claude usage "
               "limit. Check what is already done before continuing.)\n\n")
