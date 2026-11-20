#!/usr/bin/env python3
"""Answer one of the owner's sticky notes, on the note itself (lib/notes.py; proposal 76).

  python3 dirai_note.py <n> done|open "<answer>" [--at "#id"]

<n>: the note's number in the message. done: handled; say what you did and where. open: not done;
say why, or ask your question. --at: where on the page the change is (an element id "#results", or
"#file:<name>:<line>"), shown on the note as a link. Run it right after you handle each note.
The agent's folder is $DIRAI_AGENT_DIR (set by DirAI for every run), else the current directory.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import notes  # noqa: E402


def main(argv):
    at = ""
    if "--at" in argv:
        i = argv.index("--at")
        if i + 1 >= len(argv):
            return "--at needs a place, e.g. --at \"#results\""
        at, argv = argv[i + 1], argv[:i] + argv[i + 2:]
    if len(argv) < 3 or not argv[0].isdigit():
        return __doc__.strip()
    agent_dir = os.environ.get("DIRAI_AGENT_DIR") or os.getcwd()
    note, err = notes.answer(agent_dir, int(argv[0]), argv[1].lower(), " ".join(argv[2:]), at)
    if err:
        return "dirai_note.py: " + err
    print("note %d: %s (shown on the note%s)" % (note["n"], note["state"], ", linked to " + at if at else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
