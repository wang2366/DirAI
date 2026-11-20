"""codex_engine.py and the engine switch in agents.Agents: the machine's engine (Claude Code or Codex),
Codex runs with tests/fake_codex.py, its usage from the session log, holds per engine, and the
context handed over when the owner switches."""
import json
import os
import time
import unittest

from tests import util

import agents
import codex_engine


def login():
    """A Codex sign-in in the test CODEX_HOME."""
    util.write(os.path.join(codex_engine.CODEX_HOME, "auth.json"), "{}")


def forget():
    for f in (codex_engine.ENGINE_FILE, codex_engine.USAGE_FILE, codex_engine.PAUSE_FILE,
              os.path.join(codex_engine.CODEX_HOME, "auth.json")):
        if os.path.exists(f):
            os.remove(f)


class Engine(unittest.TestCase):
    def setUp(self):
        forget()

    tearDown = setUp

    def test_default_is_claude_and_switch_needs_a_login(self):
        self.assertEqual(codex_engine.engine(), "claude")
        self.assertIn("signed in", codex_engine.set_engine("codex"))
        login()
        self.assertIn("allowlist", codex_engine.set_engine("codex", "ask"))
        self.assertEqual(codex_engine.engine(), "claude")
        self.assertIsNone(codex_engine.set_engine("codex"))
        self.assertEqual(codex_engine.engine(), "codex")
        self.assertIsNone(codex_engine.set_engine("claude"))
        self.assertEqual(codex_engine.engine(), "claude")
        self.assertIn("unknown", codex_engine.set_engine("gemini"))

    def test_machine_without_claude(self):
        real = codex_engine.CLAUDE_CMD
        codex_engine.CLAUDE_CMD = os.path.join(util.TMP, "no-such-claude")
        try:
            self.assertEqual(codex_engine.engine(), "claude")     # Codex not signed in: nothing to default to
            login()
            self.assertEqual(codex_engine.engine(), "codex")      # no Claude, Codex signed in: Codex
            self.assertIn("Claude Code isn't installed", codex_engine.set_engine("claude"))
            self.assertEqual(codex_engine.engine(), "codex")
            self.assertIsNone(codex_engine.set_engine("codex"))
        finally:
            codex_engine.CLAUDE_CMD = real
        self.assertIsNone(codex_engine.set_engine("claude"))     # Claude back: the switch works again
        self.assertEqual(codex_engine.engine(), "claude")

    def test_read_events(self):
        lines = [json.dumps(m) for m in (
            {"type": "thread.started", "thread_id": "t1"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "first"}},
            {"type": "item.completed", "item": {"type": "command_execution", "aggregated_output": "Submitted batch job 9"}},
            {"type": "error", "message": "Reconnecting... 1/5"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "12"}},
            {"type": "turn.completed", "usage": {"input_tokens": 3}})] + ["not json"]
        out = codex_engine.read_events(lines)
        self.assertEqual((out["session_id"], out["result"], out["usage"], out["error"], out["is_error"]),
                         ("t1", "12", {"input_tokens": 3}, None, False))
        self.assertEqual(out["commands"], ["Submitted batch job 9"])
        failed = codex_engine.read_events([json.dumps({"type": "turn.failed", "error": {"message": "405"}})])
        self.assertEqual((failed["error"], failed["is_error"]), ("405", True))

    def test_command(self):
        d = os.path.join(util.TMP, "cmd-agent")
        os.makedirs(d, exist_ok=True)
        cmd = codex_engine.command(d, "hi", "t9", [d, util.TMP, "/no/such"], "gpt-x")
        self.assertEqual(cmd[1:3], ["exec", "--json"])
        self.assertIn("workspace-write", cmd)
        self.assertEqual(cmd.count("--add-dir"), 1)          # not the agent's own, not a missing one
        self.assertEqual(cmd[-4:], ["gpt-x", "resume", "t9", "hi"])

    def test_usage_windows_named_by_length_and_pause(self):
        util.write(os.path.join(codex_engine.CODEX_HOME, "sessions", "2026", "11", "10", "rollout-x-s1.jsonl"),
                   json.dumps({"payload": {"model": "gpt-6-luna"}}) + "\n" + json.dumps({"payload": {
                       "info": None, "rate_limits": {"primary": {"used_percent": 95.0, "window_minutes": 43200,
                                                                 "resets_at": int(time.time()) + 999},
                                                     "secondary": None, "plan_type": "free"}}}) + "\n")
        u = codex_engine.record_usage("s1")
        self.assertEqual([(w["name"], w["label"]) for w in u["windows"]], [("w43200", "30-day")])
        self.assertEqual((u["plan"], u["model"]), ("free", "gpt-6-luna"))
        self.assertEqual(codex_engine.pause_until(), (0, ""))           # 95 % < 100 %
        self.assertTrue(codex_engine.set_pause_level("w43200", 90))
        self.assertFalse(codex_engine.set_pause_level("session", 90))
        until, why = codex_engine.pause_until()
        self.assertGreater(until, time.time())
        self.assertIn("30-day", why)
        self.assertEqual(codex_engine.usage()["stop"], {"w43200": 90})

    def test_handoff_quotes_only_the_other_engines_turns(self):
        t = [{"role": "user", "text": "a", "time": "1"}, {"role": "claude", "text": "A", "time": "2"},
             {"role": "user", "text": "b", "time": "3"}, {"role": "claude", "text": "B", "time": "4", "engine": "codex"},
             {"role": "system", "text": "note", "time": "5"}, {"role": "user", "text": "new", "time": "6"}]
        back = codex_engine.handoff_prompt(t, "new", "claude")
        self.assertTrue(back.startswith("While you were away, this agent ran on Codex."))
        self.assertIn("[Codex, 4]\nB", back)
        self.assertNotIn("\nA\n", back)
        self.assertTrue(back.endswith("new"))
        self.assertEqual(codex_engine.handoff_prompt(t[:3], "x", "claude"), "x")     # nothing missed


class AgentsOnCodex(unittest.TestCase):
    def setUp(self):
        forget()
        login()
        self.root = util.new_tree("codex-" + self.id().rsplit(".", 1)[1])
        self.dir = os.path.join(self.root, "p")
        util.write(os.path.join(self.dir, "index.html"), "<html><body>p</body></html>")
        self.rv = agents.Agents(self.root)

    def tearDown(self):
        if self.rv.timer:
            self.rv.timer.cancel()
        forget()

    def data(self):
        with open(os.path.join(self.root, "www", "agents.json")) as f:
            return json.load(f)["p"]

    def wait(self, status="unread", timeout=20):
        end = time.time() + timeout
        while time.time() < end:
            st = self.data()
            if st["status"] == status and not self.rv.running:
                return st
            time.sleep(0.1)
        self.fail("never %s: %s" % (status, self.data()["status"]))

    def argv(self, name):
        with open(os.path.join(self.dir, name)) as f:
            return json.load(f)

    def test_runs_on_codex_then_back_on_claude(self):
        self.assertIsNone(self.rv.set_engine("codex"))
        self.assertTrue(self.rv.comment("p", "do it"))
        st = self.wait()
        reply = st["thread"][-1]
        self.assertEqual((reply["text"], reply["engine"], reply["model"]), ("codex did it", "codex", "codex:gpt-test"))
        self.assertTrue(st["codex_session"].startswith("th-"))
        self.assertIsNone(st.get("session_id"))
        first = self.argv("codex_argv.json")
        self.assertNotIn("resume", first)
        self.assertTrue(first[-1].startswith("Instructions for this agent"))    # DirAI's instructions, once
        self.assertTrue(first[-1].endswith("do it"))
        self.assertEqual(self.rv.state("p")["engine"], "codex")
        u = codex_engine.usage()
        self.assertEqual([w["label"] for w in u["windows"]], ["5-hour", "Weekly"])
        self.assertEqual(u["plan"], "plus")
        # the next message resumes the Codex session, without the instructions again
        self.rv.comment("p", "more")
        self.wait()
        again = self.argv("codex_argv.json")
        self.assertEqual(again[again.index("resume") + 1], st["codex_session"])
        self.assertEqual(again[-1], "more")
        # Compact is Claude Code's; on Codex it isn't offered
        self.assertFalse(self.rv.compact("p"))
        # back to Claude: a fresh Claude session gets the thread quoted (comment()), Codex's replies included
        self.assertIsNone(self.rv.set_engine("claude"))
        self.rv.comment("p", "on claude")
        st = self.wait()
        self.assertEqual([e for e in st["thread"] if e["role"] == "claude"][-1]["engine"], "claude")
        self.assertEqual(st["session_id"], "sess1")              # fake_claude's
        self.assertEqual(st["codex_session"], again[again.index("resume") + 1])   # kept for a switch back

    def test_claude_hold_does_not_hold_codex_and_codex_limit_holds_only_codex(self):
        self.rv.hold_until, self.rv.hold_reason = time.time() + 3600, "Claude usage at 100%"
        self.rv.comment("p", "held")
        self.assertEqual(self.data()["status"], "queued")
        # the owner switches: the held message goes to Codex now
        self.assertIsNone(self.rv.set_engine("codex"))
        st = self.wait()
        self.assertEqual(st["thread"][-1]["text"], "codex did it")
        # Codex refuses for its limit: the message waits for Codex's reset, in the same session
        self.rv.comment("p", "LIMIT please")
        st = self.wait("queued")
        self.assertTrue(st["queued_reason"].startswith("Codex usage limit hit"))
        self.assertGreater(self.rv.codex_hold_until, time.time())
        self.assertGreater(self.rv.hold_until, time.time())     # Claude's own hold is untouched


if __name__ == "__main__":
    unittest.main()
