#!/usr/bin/env python3
"""Answer one of the owner's sticky notes, on the note itself (lib/notes.py; proposal 76).

  python3 dirai_note.py <n> done|open "<answer>" [--at "#id"]

<n>: the note's number in the message. done: handled; say what you did and where. open: not done;
say why, or ask your question. --at: where on the page the change is (an element id "#results", or
"#file:<name>:<line>"), shown on the note as a link. Run it right after you handle each note.

  python3 dirai_note.py ask <agent>[,<agent>...] "<request>" [--about "#id"] [--quote "<text>"]

Ask another agent of this tree to do something (proposal 77). <agent>: its folder, relative to the tree's
top (as in your colleagues' list). It only drafts the request, on the note "you <-> agent" on your page;
the owner reads it and sends it, edits it or rejects it. The answer comes back to you by itself, as a
message. Read the agent's page first (dirai_card.py): ask only what it doesn't already answer. One
request per agent waits at a time. --about: the place on your page it is about; --quote: text it is about.
The agent's folder is $DIRAI_AGENT_DIR (set by DirAI for every run), else the current directory.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import notes  # noqa: E402


def _opt(argv, name):
    """(value of --name or "", argv without it); value None if --name has nothing after it."""
    if name not in argv:
        return "", argv
    i = argv.index(name)
    if i + 1 >= len(argv):
        return None, argv
    return argv[i + 1], argv[:i] + argv[i + 2:]


def ask(agent_dir, argv):
    about, argv = _opt(argv, "--about")
    quote, argv = _opt(argv, "--quote")
    if about is None or quote is None or len(argv) < 2:
        return __doc__.strip()
    root = notes.tree_root(agent_dir)
    if root is None:
        return "dirai_note.py: this folder isn't in a DirAI tree"
    me = os.path.relpath(os.path.realpath(agent_dir), os.path.realpath(root))
    tos = []
    for t in argv[0].split(","):
        t = t.strip().strip("/")
        if t.startswith(root + "/"):
            t = t[len(root) + 1:]
        if not t or ".." in t.split("/") or os.path.isabs(t) or t == me:
            return "dirai_note.py: %r: give another agent's folder, relative to the tree's top" % t
        if not os.path.isfile(os.path.join(root, t, "index.html")):
            return "dirai_note.py: %s isn't an agent of this tree (no %s/index.html)" % (t, t)
        if t not in tos:
            tos.append(t)
    got, err = notes.ask(agent_dir, tos, " ".join(argv[1:]), about, quote)
    if err:
        return "dirai_note.py: " + err
    for x in got:
        print("request %d to %s: drafted; the owner sends it. Its answer comes back to you as a message."
              % (x["n"], x["to"]))
    return 0


def main(argv):
    agent_dir = os.environ.get("DIRAI_AGENT_DIR") or os.getcwd()
    if argv[:1] == ["ask"]:
        return ask(agent_dir, argv[1:])
    at = ""
    if "--at" in argv:
        i = argv.index("--at")
        if i + 1 >= len(argv):
            return "--at needs a place, e.g. --at \"#results\""
        at, argv = argv[i + 1], argv[:i] + argv[i + 2:]
    if len(argv) < 3 or not argv[0].isdigit():
        return __doc__.strip()
    note, err = notes.answer(agent_dir, int(argv[0]), argv[1].lower(), " ".join(argv[2:]), at)
    if err:
        return "dirai_note.py: " + err
    print("note %d: %s (shown on the note%s)" % (note["n"], note["state"], ", linked to " + at if at else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
