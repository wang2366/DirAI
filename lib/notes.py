"""Sticky notes on an agent's page (proposal 76, improvement/sticky-notes).

The owner selects text on the agent's page and leaves a note on it (panel.js); notes collect until
"Send N notes" puts them in one message (agent_prompts.notes_prompt). The agent answers each note on
the note itself, while it works: scripts/dirai_note.py <n> done|open "<answer>" [--at "#id"] (answer()).
A run that ends with notes unanswered gets one follow-up (agents.py, NOTES_FIX); finish_run() then
marks what is still unanswered "no answer" and reopens it. The owner can reply on a note (act "reply"):
that reopens it, and the next Send carries the exchange. Old-style reply lines ("<n>: done" /
"<n>: open, <why>") are still read as a fallback (parse_reply).

They live in the agent's own folder, <agent>/.notes.json: a dot-file, so the Files section doesn't show
it (agent_files.py skips dot-names), and the repo's .gitignore keeps it out of the agents' commits.
One note:
  {"id", "n", "text", "before", "after", "heading", ["file", "lines", "svg", "rendered"],
   "note", "state", ["answer", "at", "thread", "answered", "noanswer"], "created"}
state: "open" (not sent yet, the agent left it open, or the owner replied), "sent" (in a message, no
answer yet), "done". thread: [{"who": "agent"|"owner", "text", "time", ["state", "at"]}], the last
THREAD_MAX entries. answered: answered in the run it was sent in; noanswer: that run left it unanswered.
A done note stays (greyed), with its answers, until the owner deletes it or clears the done notes.
"""
import contextlib
import fcntl
import json
import os
import re
import secrets
import threading
import time

FILE = ".notes.json"
MAX_NOTES = 100
TEXT_MAX = 4000      # characters of quoted text kept (agent_prompts.SEL_MAX)
NOTE_MAX = 4000      # characters of the note itself
CTX_MAX = 40         # characters of page text kept before and after the quote (to tell copies apart)
STATES = ("open", "sent", "done")
THREAD_MAX = 10      # entries of a note's exchange kept
ANSWER_MAX = 2000    # characters of one answer or reply
_LOCK = threading.Lock()     # within the server; _locked() adds a file lock for dirai_note.py (another process)


@contextlib.contextmanager
def _locked(agent_dir):
    """Around every read-change-write of <agent>/.notes.json: the server's threads (_LOCK) and other
    processes (dirai_note.py) wait for each other, so no write is lost (R10, improvement/agent-notes).
    The flock is on a separate <agent>/.notes.json.lock, since _save() replaces .notes.json by another
    file. If the lock file can't be opened (folder not writable), only _LOCK."""
    with _LOCK:
        try:
            f = open(path(agent_dir) + ".lock", "a")
        except OSError:
            f = None
        if f is None:
            yield
            return
        with f:
            fcntl.flock(f, fcntl.LOCK_EX)     # released when f closes
            yield


def _now():
    return time.strftime("%Y-%m-%d %H:%M")


def _say(note, who, text, **extra):
    """Add an entry to the note's exchange (cut to THREAD_MAX)."""
    note["thread"] = (note.get("thread") or []) + [dict({"who": who, "text": text[:ANSWER_MAX], "time": _now()}, **extra)]
    note["thread"] = note["thread"][-THREAD_MAX:]


def path(agent_dir):
    return os.path.join(agent_dir, FILE)


def load(agent_dir):
    try:
        with open(path(agent_dir), encoding="utf-8") as f:
            notes = json.load(f)
    except (OSError, ValueError):
        return []
    return [n for n in notes if isinstance(n, dict) and n.get("id")] if isinstance(notes, list) else []


def _save(agent_dir, notes):
    """Atomically (temp file, then rename), so a run reading it never sees half a file. No notes: no file."""
    p = path(agent_dir)
    if not notes:
        try:
            os.remove(p)
        except OSError:
            pass
        return
    tmp = "%s.tmp%d" % (p, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(notes, f, indent=1)
    os.replace(tmp, p)


def _clean(raw):
    """The fields of a note the panel sent, cut to size; None without quoted text."""
    s = lambda k, n: str(raw.get(k) or "")[:n]
    text = s("text", TEXT_MAX).strip()
    if not text:
        return None
    out = {"text": text, "before": s("before", CTX_MAX), "after": s("after", CTX_MAX),
           "heading": s("heading", 200), "note": s("note", NOTE_MAX).strip()}
    if raw.get("file"):     # in a file of the Files section, or in an inline diagram (svg)
        out["file"] = s("file", 500)
        lines = raw.get("lines")
        if isinstance(lines, list) and len(lines) == 2 and all(isinstance(x, int) for x in lines):
            out["lines"] = lines
        out["svg"], out["rendered"] = bool(raw.get("svg")), bool(raw.get("rendered"))
    return out


def act(agent_dir, body):
    """POST /_review/notes: op add / edit / delete / state / reply / clear. Returns (notes, error or None)."""
    op = body.get("op")
    with _locked(agent_dir):
        notes = load(agent_dir)
        if op == "add":
            if len(notes) >= MAX_NOTES:
                return notes, "At most %d notes per page." % MAX_NOTES
            note = _clean(body.get("note") or {})
            if note is None:
                return notes, "Select some text first."
            note.update(id=secrets.token_hex(4), n=max([x.get("n", 0) for x in notes] + [0]) + 1,
                        state="open", created=time.strftime("%Y-%m-%d %H:%M"))
            notes.append(note)
        elif op == "clear":     # the owner removes the done notes (they stay, with answers, until then)
            notes = [x for x in notes if x.get("state") != "done" or x.get("to") or x.get("from")]   # requests fold by themselves
        else:
            hit = next((x for x in notes if x["id"] == str(body.get("id") or "")), None)
            if hit is None:
                return notes, "That note is gone (deleted, or closed by a run)."
            if op == "delete":
                notes.remove(hit)
            elif op == "edit":
                hit["note"] = str(body.get("note") or "")[:NOTE_MAX].strip()
            elif op == "state" and body.get("state") in STATES:   # the owner overrides the agent (D4a)
                hit["state"] = body["state"]
                hit.pop("noanswer", None)
            elif op == "reply":     # the owner answers the agent on the note: open again, for the next Send (E5a)
                text = str(body.get("text") or "").strip()
                if not text:
                    return notes, "Write a reply first."
                _say(hit, "owner", text)
                hit["state"] = "open"
                hit.pop("noanswer", None)
            else:
                return notes, "bad request"
        _save(agent_dir, notes)
        return notes, None


def take(agent_dir, ids):
    """The notes ids that can be sent (not done, and not a request of this agent to another: R4), by
    number, now marked "sent"; [] if none."""
    want = {str(i) for i in ids or []}
    with _locked(agent_dir):
        notes = load(agent_dir)
        out = [x for x in notes if x["id"] in want and x.get("state") != "done" and not x.get("to")]
        for x in out:
            x["state"] = "sent"
            for k in ("answered", "noanswer"):
                x.pop(k, None)
        if out:
            _save(agent_dir, notes)
    return sorted(out, key=lambda x: x.get("n", 0))


def unsend(agent_dir, ids):
    """Back to "open": the message that carried them wasn't sent after all."""
    want = set(ids)
    with _locked(agent_dir):
        notes = load(agent_dir)
        for x in notes:
            if x["id"] in want and x.get("state") == "sent":
                x["state"] = "open"
        _save(agent_dir, notes)


# "3: done", "**3:** open, which deck?", "- 3: done (moved to Results)", "Note 3 - open: ..."
REPLY_RE = re.compile(r"^[ \t>*_`-]*(?:note[ \t]*)?(\d{1,3})[*_`]*[ \t]*[:.)\-–][ \t]*[*_`]*[ \t]*(done|open)\b[*_`]*"
                      r"[ \t,:;.\-–]*(.*)$", re.I | re.M)


def parse_reply(text):
    """{n: (state, rest of the line)} from the agent's reply; the last line about a note wins."""
    return {int(m.group(1)): (m.group(2).lower(), m.group(3).strip()) for m in REPLY_RE.finditer(text or "")}


def _answer(x, state, text, at=""):
    x["state"], x["answer"], x["answered"] = state, text[:ANSWER_MAX], True
    x.pop("noanswer", None)
    if at:
        x["at"] = at[:300]
    else:
        x.pop("at", None)
    _say(x, "agent", text, state=state, **({"at": at[:300]} if at else {}))


def answer(agent_dir, n, state, text, at=""):
    """The agent's answer to note n (dirai_note.py): done or open, with what it did or asks, and where
    (at: "#id" or "#file:name:line"). Only a note sent to it; it may answer again in the same run.
    Returns (note, None) or (None, error)."""
    if state not in ("done", "open"):
        return None, "state must be done or open"
    text = (text or "").strip()
    if not text:
        return None, "give an answer: what you did and where, or your question"
    with _locked(agent_dir):
        notes = load(agent_dir)
        hit = next((x for x in notes if x.get("n") == n), None)
        if hit is None:
            return None, "there is no note %d (notes: %s)" % (n, ", ".join(str(x.get("n")) for x in notes) or "none")
        if hit.get("state") != "sent" and not hit.get("answered"):
            return None, "note %d wasn't sent to you (it is %s); answer only the notes in the message" % (n, hit.get("state"))
        _answer(hit, state, text, at)
        _save(agent_dir, notes)
        return hit, None


# "The owner left 3 sticky notes on your page (notes 1, 2, 5)" (agent_prompts.notes_prompt)
PROMPT_RE = re.compile(r"sticky notes? on your page \(notes? ([\d, ]+)\)")


def prompt_notes(prompt):
    """The numbers of the notes a run's prompt carries (several, for queued messages sent together)."""
    return sorted({int(n) for m in PROMPT_RE.finditer(prompt or "") for n in re.findall(r"\d+", m.group(1))})


def unanswered(agent_dir, nums, reply=""):
    """Of the notes nums (this run's), those still unanswered, after reading old-style reply lines."""
    if not nums:
        return []
    if reply:
        close_from_reply(agent_dir, reply, nums)
    return [x["n"] for x in load(agent_dir) if x.get("n") in nums and x.get("state") == "sent"]


def finish_run(agent_dir, nums, reply, replied):
    """When a run ends: read old-style reply lines and reopen this run's unanswered notes (marked
    "no answer" if the run replied; a cancelled or failed run just gives them back). Done notes stay,
    with their answers, until the owner deletes them (act "delete" / "clear"). Returns
    [{"id", "n", "state", ["noanswer"]}] of this run's notes, for the thread (E3a)."""
    if not nums:
        return []
    if replied and reply:
        close_from_reply(agent_dir, reply, nums)
    with _locked(agent_dir):
        notes = load(agent_dir)
        if not notes:
            return []
        out = []
        for x in notes:
            mine = x.get("n") in nums
            if mine and x.get("state") == "sent":
                x["state"] = "open"
                if replied:
                    x["noanswer"] = True
            if mine:
                x.pop("answered", None)
                out.append(dict({"id": x["id"], "n": x["n"], "state": x["state"]}, **({"noanswer": True} if x.get("noanswer") else {})))
        if out:
            _save(agent_dir, notes)
        return sorted(out, key=lambda r: r["n"])


def close_from_reply(agent_dir, reply, nums=None):
    """Mark each sent note (of nums, if given) that the reply names in an old-style "<n>: done|open"
    line. Returns how many it marked."""
    said = parse_reply(reply)
    if not said:
        return 0
    with _locked(agent_dir):
        notes = load(agent_dir)
        marked = 0
        for x in notes:
            got = said.get(x.get("n")) if x.get("state") == "sent" and (nums is None or x.get("n") in nums) else None
            if got:
                _answer(x, got[0], got[1] or got[0])
                marked += 1
        if marked:
            _save(agent_dir, notes)
        return marked


def strip_reply(reply, nums):
    """The reply without its old-style lines about the notes nums (they are on the notes now)."""
    if not nums:
        return reply
    out = [l for l in (reply or "").split("\n") if not ((lambda m: m and int(m.group(1)) in nums)(REPLY_RE.match(l)))]
    return "\n".join(out).strip()


# --- requests between agents (proposal 77, improvement/agent-notes) ----------------------------------
# Agent A asks agent B with dirai_note.py ask B "<request>": a draft entry in A's notes, {"to": B}. Only the
# owner sends it (agents.send_request): the server copies it into B's notes as {"from": A} (same "link")
# and messages B; B answers it like any note (answer()); when B's run ends the server copies the answer
# onto A's entry and gives it to A (agents._requests_answered). All of A's entries with B make the note
# "A ↔ B" (the panel's Requests bar); each entry has its own state:
#   A's entry ("to"): draft -> sent -> done | open (B asked back or didn't answer) | rejected (by the owner)
#   B's entry ("from"): open -> sent (in B's message) -> done | open, as any note
PAIR_KEEP = 5       # finished entries kept per pair (older ones fold away, R7)


def tree_root(agent_dir):
    """The tree an agent's folder is in: the nearest folder up with www/dirai.json; None if none."""
    d = os.path.abspath(agent_dir)
    while True:
        if os.path.isfile(os.path.join(d, "www", "dirai.json")):
            return d
        up = os.path.dirname(d)
        if up == d:
            return None
        d = up


def _fold(notes, key, other):
    """Keep PAIR_KEEP finished entries of the pair (key "to" or "from" == other), dropping the oldest."""
    done = [x for x in notes if x.get(key) == other and x.get("state") in ("done", "rejected")]
    drop = {x["id"] for x in done[:-PAIR_KEEP]} if len(done) > PAIR_KEEP else set()
    return [x for x in notes if x["id"] not in drop]


def _new(notes, fields):
    return dict(fields, id=secrets.token_hex(4), n=max([x.get("n", 0) for x in notes] + [0]) + 1,
                before="", after="", heading="", created=time.strftime("%Y-%m-%d %H:%M"))


def ask(agent_dir, tos, text, about="", quote=""):
    """The agent's drafts to the agents tos (dirai_note.py ask): one entry each, state "draft"; nothing is
    sent. A pair has one request in flight at a time (draft or sent). Returns (entries, error or None)."""
    text = (text or "").strip()[:NOTE_MAX]
    if not text:
        return [], "say what you ask for"
    with _locked(agent_dir):
        notes = load(agent_dir)
        busy = [t for t in tos if any(x.get("to") == t and x.get("state") in ("draft", "sent") for x in notes)]
        if busy:
            return [], ("a request to %s is still waiting (drafted or sent, not answered yet): wait for its "
                        "answer, or ask the owner to send or reject it" % ", ".join(busy))
        if len(notes) + len(tos) > MAX_NOTES:
            return [], "too many notes on this page (at most %d)" % MAX_NOTES
        out = []
        for t in tos:
            notes = _fold(notes, "to", t)
            x = _new(notes, {"to": t, "note": text, "text": (quote or "").strip()[:TEXT_MAX],
                             "about": (about or "").strip()[:300], "state": "draft", "link": secrets.token_hex(6)})
            notes.append(x)
            out.append(x)
        _save(agent_dir, notes)
        return out, None


def receive(agent_dir, frm, src):
    """The server copies A's entry src into B's notes (agent_dir), from frm, as an open note, with the
    pair's previous request and its answer, so a follow-up has its context (R7). Returns the new entry."""
    with _locked(agent_dir):
        notes = _fold(load(agent_dir), "from", frm)
        prev = [x for x in notes if x.get("from") == frm and x.get("answer")]
        x = _new(notes, {"from": frm, "note": src["note"], "text": src.get("text", ""),
                         "about": src.get("about", ""), "state": "open", "link": src["link"]})
        if prev:
            x["prev"] = {"note": prev[-1]["note"][:ANSWER_MAX], "answer": prev[-1]["answer"]}
        notes.append(x)
        _save(agent_dir, notes)
        return x


def update(agent_dir, match, **fields):
    """Set fields on the first note match(note) picks (a value None removes the field). The note, or None."""
    with _locked(agent_dir):
        notes = load(agent_dir)
        hit = next((x for x in notes if match(x)), None)
        if hit is not None:
            for k, v in fields.items():
                if v is None:
                    hit.pop(k, None)
                else:
                    hit[k] = v
            _save(agent_dir, notes)
        return hit


def remove(agent_dir, note_id):
    """Delete one note (a copy that couldn't be sent)."""
    with _locked(agent_dir):
        notes = load(agent_dir)
        left = [x for x in notes if x["id"] != note_id]
        if len(left) != len(notes):
            _save(agent_dir, left)
