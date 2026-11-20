#!/usr/bin/env python3
"""Which Purdue GenAI Studio models can run a DirAI agent: try each with Claude Code.

Usage: scripts/genai_models_check.py [MODEL ...]     (default: every model GenAI Studio lists)

1. One request per model with a tool to call: does it call it (as a tool, not written out as text)?
2. For those that do, a real Claude Code run in a temp folder: read probe.txt, write out.txt with
   its text in uppercase, reply DONE. Passing means out.txt is right.
3. For those that pass, the context window (from the error a too-large max_tokens gets).

Requests go through genai_relay (the key from DIRAI_GENAI_KEY_FILE, at most 18 a minute), so this
takes a few minutes for every model. It prints a table and the GENAI_MODELS line for lib/agents.py.
"""
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import agents        # noqa: E402
import genai_relay   # noqa: E402

RUN_TIMEOUT_S = 420
TASK = "Read probe.txt, then create out.txt in this folder containing the same text in uppercase. Then reply DONE."
TOOL = [{"name": "read_file", "description": "Read a file and return its contents",
         "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}]


def call(relay, path, body=None):
    """(status, parsed JSON or the text) of a request through the relay."""
    conn = http.client.HTTPConnection("127.0.0.1", relay.httpd.server_address[1], timeout=300)
    conn.request("POST" if body else "GET", path, json.dumps(body) if body else None,
                 {"Authorization": "Bearer " + relay.token, "content-type": "application/json",
                  "anthropic-version": "2023-06-01"})
    r = conn.getresponse()
    text = r.read().decode("utf-8", "replace")
    try:
        return r.status, json.loads(text)
    except ValueError:
        return r.status, text


def calls_tool(relay, model):
    """(True, "") if the model answers with a tool call, else (False, why)."""
    status, d = call(relay, "/v1/messages", {
        "model": model, "max_tokens": 1024, "tools": TOOL, "output_config": {"effort": "medium"},
        "messages": [{"role": "user", "content": "Use the read_file tool to read probe.txt."}]})
    if status != 200 or not isinstance(d, dict):
        return False, "error %s: %s" % (status, str(d.get("detail", d) if isinstance(d, dict) else d)[:100])
    if any(c.get("type") == "tool_use" for c in d.get("content", [])):
        return True, ""
    return False, "no tool call"


def claude_task(relay, model, folder):
    """(True, "") if a Claude Code run on the model does TASK, else (False, why)."""
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    with open(os.path.join(folder, "probe.txt"), "w") as f:
        f.write("hello world 42\n")
    env = dict(os.environ, **dict(agents.LOCAL_ENV, ANTHROPIC_BASE_URL=relay.url, ANTHROPIC_AUTH_TOKEN=relay.token))
    try:
        p = subprocess.run([agents.CLAUDE_CMD, "-p", TASK, "--model", model, "--effort", "medium",
                            "--allowedTools", "Read", "Write", "Edit", "--output-format", "json"],
                           cwd=folder, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, universal_newlines=True, timeout=RUN_TIMEOUT_S)
        reply = (json.loads(p.stdout).get("result") or "").replace("\n", " ")
    except subprocess.TimeoutExpired:
        return False, "timed out after %d s" % RUN_TIMEOUT_S
    except ValueError:
        return False, "no result from claude"
    try:
        with open(os.path.join(folder, "out.txt")) as f:
            if f.read().strip() == "HELLO WORLD 42":
                return True, ""
    except OSError:
        pass
    return False, "task not done: " + reply[:300]


def context_window(relay, model):
    """The model's context window in tokens, or None if its error doesn't say."""
    status, d = call(relay, "/v1/messages", {"model": model, "max_tokens": 10 ** 7,
                                             "messages": [{"role": "user", "content": "hi"}]})
    m = re.search(r"max_model_len=(?:max_total_tokens=)?(\d+)|maximum context length is (\d+)", json.dumps(d))
    return int(m.group(1) or m.group(2)) if m else None


def main():
    key = agents.load_text(agents.GENAI_KEY_FILE).strip()
    if not key:
        sys.exit("No GenAI Studio key in %s" % agents.GENAI_KEY_FILE)
    relay = genai_relay.Relay(agents.GENAI_URL, lambda: key, rpm=18)
    models = sys.argv[1:] or [m["id"] for m in call(relay, "/models")[1]["data"]]
    work = tempfile.mkdtemp(prefix="genai-check-")
    print("%d models; work folder %s" % (len(models), work), flush=True)
    good = {}
    for model in models:
        t0 = time.time()
        ok, why = calls_tool(relay, model)
        if ok:
            ok, why = claude_task(relay, model, os.path.join(work, re.sub(r"[^\w.-]", "_", model)))
        if ok:
            good[model] = context_window(relay, model)
            why = "context %s" % (good[model] or "not reported")
        print("%-32s %-4s %4d s  %s" % (model, "ok" if ok else "no", time.time() - t0, why), flush=True)
    shutil.rmtree(work, ignore_errors=True)
    print("\nFor lib/agents.py (fill in a window not reported, e.g. from the model's card):")
    print("GENAI_MODELS = {%s}" % ", ".join('"%s": %s' % (m, w) for m, w in good.items()))


if __name__ == "__main__":
    main()
