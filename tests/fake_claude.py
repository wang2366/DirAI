#!/usr/bin/env python3
"""Stand-in for `claude -p` in the server tests: speaks just enough stream-json.

First message: breaks the page's summary card, asks for a permission and withdraws it, then
replies with one denial. Any later message (the card fix): repairs the card. Writes its argv to
argv.json in the page folder.
"""
import json
import sys

with open("argv.json", "w") as f:
    json.dump(sys.argv[1:], f)


def say(msg):
    print(json.dumps(msg), flush=True)


def edit(old, new, extra=""):
    with open("index.html") as f:
        s = f.read()
    with open("index.html", "w") as f:
        f.write(s.replace(old, new) + extra)


n = 0
for line in sys.stdin:
    if json.loads(line).get("type") != "user":
        continue
    n += 1
    if n == 1:
        edit("<dt>Updated</dt>", "<dt>Xpdated</dt>", "<!-- edited -->")
        say({"type": "control_request", "request_id": "r1", "request": {
            "subtype": "can_use_tool", "tool_name": "Bash", "input": {"command": "ls && rm -rf /x"}}})
        say({"type": "control_cancel_request", "request_id": "r1"})
        say({"type": "result", "result": "did it", "session_id": "sess1", "total_cost_usd": 0.5,
             "permission_denials": [{"tool_name": "Read", "tool_input": {"file_path": "/etc/hosts"}}]})
    else:
        edit("<dt>Xpdated</dt>", "<dt>Updated</dt>")
        say({"type": "result", "result": "fixed card", "session_id": "sess1", "total_cost_usd": 0.7})
