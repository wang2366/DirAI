#!/usr/bin/env python3
"""Stand-in for `codex exec --json` in the tests: prints the JSONL events DirAI reads and writes a
session log with rate limits under $CODEX_HOME, as Codex 0.167 does. Writes its argv to
codex_argv.json in the agent's folder. A prompt containing LIMIT fails on the usage limit."""
import json
import os
import sys
import time

args = sys.argv[1:]
with open("codex_argv.json", "w") as f:
    json.dump(args, f)
prompt = args[-1]
session = args[args.index("resume") + 1] if "resume" in args else "th-%d" % (time.time() * 1000)
limit = "LIMIT" in prompt


def say(m):
    print(json.dumps(m), flush=True)


home = os.environ["CODEX_HOME"]
day = os.path.join(home, "sessions", "2026", "11", "10")
os.makedirs(day, exist_ok=True)
rl = {"limit_id": "codex", "primary": {"used_percent": 100.0 if limit else 12.0, "window_minutes": 300,
                                       "resets_at": int(time.time()) + 3600},
      "secondary": {"used_percent": 40.0, "window_minutes": 10080, "resets_at": int(time.time()) + 86400},
      "credits": {"has_credits": False}, "plan_type": "plus"}
with open(os.path.join(day, "rollout-2026-11-10T00-00-00-%s.jsonl" % session), "a") as f:
    f.write(json.dumps({"type": "turn_context", "payload": {"model": "gpt-test"}}) + "\n")
    f.write(json.dumps({"type": "event_msg", "payload": {"type": "token_count", "rate_limits": rl}}) + "\n")

say({"type": "thread.started", "thread_id": session})
say({"type": "turn.started"})
if limit:
    say({"type": "error", "message": "Reconnecting... 1/5"})
    say({"type": "turn.failed", "error": {"message": "You've hit your usage limit. Try again later."}})
    sys.exit(1)
say({"type": "item.completed", "item": {"id": "i1", "type": "command_execution", "command": "sbatch x",
                                        "aggregated_output": "Submitted batch job 4242\n", "exit_code": 0}})
say({"type": "item.completed", "item": {"id": "i2", "type": "agent_message", "text": "codex did it"}})
say({"type": "turn.completed", "usage": {"input_tokens": 10, "cached_input_tokens": 5, "output_tokens": 2}})
