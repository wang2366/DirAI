"""agents.Agents in process: the queue, usage holds, cancel, restarts, repeats, grants, pruning.
Runs are held back (hold_until in the future) so nothing starts unless a test wants it to."""
import datetime
import json
import os
import http.server
import threading
import time
import unittest
from unittest import mock

from tests import util

import agents
import agent_prompts


class AgentsTest(unittest.TestCase):
    def setUp(self):
        self.root = util.new_tree("agents-" + self.id().rsplit(".", 1)[1])
        util.write(os.path.join(self.root, "p", "index.html"), "<html><body>p</body></html>")
        self.rv = agents.Agents(self.root)
        self.rv.hold_until, self.rv.hold_reason = time.time() + 3600, "test hold"

    def tearDown(self):
        if self.rv.timer:
            self.rv.timer.cancel()

    def data(self):
        """agents.json as saved ({} when nothing has been saved yet)."""
        try:
            with open(os.path.join(self.root, "www", "agents.json")) as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def texts(self, agent="p"):
        return [m["text"] for m in self.data()[agent]["thread"]]

    def test_comment_is_queued_while_held(self):
        self.assertTrue(self.rv.comment("p", "do it"))
        st = self.data()["p"]
        self.assertEqual((st["status"], st["pending"], st["queued_reason"]), ("queued", "do it", "test hold"))
        self.assertTrue(self.texts()[1].startswith("test hold. Queued: this message will be sent automatically at"))
        self.assertFalse(self.rv.comment("p", "again"))     # busy
        self.assertEqual(self.rv.working("p")[0], "do it")

    def test_cancel_queued(self):
        self.rv.comment("p", "do it")
        self.assertTrue(self.rv.cancel("p"))
        st = self.data()["p"]
        self.assertEqual(st["status"], "unread")
        self.assertNotIn("pending", st)
        self.assertEqual(self.texts()[-1], "Cancelled by the owner.")
        self.assertEqual(self.rv.queue, [])
        self.assertFalse(self.rv.cancel("p"))               # nothing left to cancel

    def test_restart_keeps_queue_and_drops_lost_runs(self):
        util.write(os.path.join(self.root, "q", "index.html"), "<html></html>")
        self.rv.comment("p", "do it")
        data = self.data()
        data["q"] = {"status": "working", "thread": [], "session_id": "s"}
        with open(os.path.join(self.root, "www", "agents.json"), "w") as f:
            json.dump(data, f)
        rv2 = agents.Agents(self.root)
        try:
            self.assertEqual(rv2.queue, [("p", "do it")])
            self.assertEqual(rv2.hold_reason, "test hold")
            self.assertEqual(self.data()["q"]["status"], "unread")
            self.assertTrue(self.texts("q")[-1].startswith("The server restarted while this was running"))
        finally:
            if rv2.timer:
                rv2.timer.cancel()

    def test_selection_and_named_paths(self):
        util.write(os.path.join(self.root, "other", "data.csv"), "")
        self.rv.comment("p", "compare with other/data.csv", selection={"text": "p", "heading": "H"})
        st = self.data()["p"]
        self.assertEqual(st["thread"][0]["selection"], {"text": "p", "heading": "H", "lines": [1, 1]})
        self.assertEqual(st["grants"], ["Read(/%s/other/**)" % self.root])
        self.assertTrue(st["pending"].startswith("The owner selected this text in index.html"))

    def test_file_selection_prompt(self):
        util.write(os.path.join(self.root, "p", "run.sh"), "echo one\necho two\n")
        self.assertTrue(self.rv.comment("p", "say three", selection={
            "text": "echo two", "heading": "", "file": "run.sh", "lines": [2, 2]}))
        self.assertEqual(self.data()["p"]["pending"],
                         "The owner selected this text in run.sh (source line 2; read just the lines around it "
                         "unless you need more):\n> echo two\n\nTheir message about it:\nsay three")
        self.rv.cancel("p")
        self.assertFalse(self.rv.comment("p", "x", selection={"text": "a", "file": "../x.sh", "lines": [1, 1]}))

    def test_new_chat_and_fresh_prompt(self):
        self.assertFalse(self.rv.new_chat("p"))              # no session yet
        self.rv.comment("p", "first")
        self.rv.cancel("p")
        data = self.data()
        data["p"]["session_id"] = "s1"
        with open(os.path.join(self.root, "www", "agents.json"), "w") as f:
            json.dump(data, f)
        self.assertTrue(self.rv.new_chat("p"))
        self.assertEqual(self.texts()[-1], agent_prompts.NEW_CHAT_MARK)
        self.rv.comment("p", "second")
        self.assertTrue(self.data()["p"]["pending"].startswith("This is a fresh session of an agent"))

    def test_repeat(self):
        self.assertFalse(self.rv.set_repeat("p", "fortnight", "x"))
        self.assertFalse(self.rv.set_repeat("p", "day", " "))
        self.assertFalse(self.rv.set_repeat("p", "off"))      # nothing to turn off
        self.assertTrue(self.rv.set_repeat("p", "hour", "check it"))
        self.assertTrue(self.texts()[-1].startswith("Repeats every hour, next at"))
        data = self.data()
        data["p"]["repeat"]["next"] = time.time() - 2.5 * 3600   # missed while the server was down
        with open(os.path.join(self.root, "www", "agents.json"), "w") as f:
            json.dump(data, f)
        self.rv.check_repeats()
        st = self.data()["p"]
        self.assertEqual(st["thread"][-2]["scheduled"], "hour")
        self.assertTrue(st["pending"].startswith("(Scheduled run: the owner set this message to be sent every hour."))
        self.assertTrue(time.time() < st["repeat"]["next"] <= time.time() + 3600)   # sent once, next in the future
        self.rv.cancel("p")
        self.assertTrue(self.rv.set_repeat("p", "off"))
        self.assertEqual(self.texts()[-1], "Repeat turned off.")

    def test_grant(self):
        self.rv.comment("p", "x")
        self.rv.cancel("p")
        self.assertFalse(self.rv.grant("p", ["Bash(make)"], False))   # no session
        data = self.data()
        data["p"]["session_id"] = "s1"
        with open(os.path.join(self.root, "www", "agents.json"), "w") as f:
            json.dump(data, f)
        self.assertFalse(self.rv.grant("p", ["Bash(sudo x)"], True))  # always denied: nothing left
        self.assertTrue(self.rv.grant("p", ["Bash(make)", "Read(//data/**)"], True))
        st = self.data()["p"]
        self.assertEqual(st["grants"], ["Read(//data/**)"])           # folder reads stay with the agent
        with open(agents.PERMS_FILE) as f:
            self.assertIn("Bash(make)", json.load(f)["always"])
        self.assertEqual([m["text"] for m in st["thread"][-3:-1]],
                         ["Granted (always): Bash(make)", "Granted (this agent): Read(//data/**)"])
        self.assertTrue(st["pending"].startswith("The owner granted these permissions: Bash(make), Read(//data/**)."))

    def test_compact_needs_session(self):
        self.assertFalse(self.rv.compact("p"))

    def test_set_status_and_model(self):
        self.assertTrue(self.rv.set_status("p", "closed"))
        self.assertFalse(self.rv.set_model("p", "gpt-5"))
        self.assertTrue(self.rv.set_model("p", "opus"))
        self.assertEqual(self.rv.state("p")["model"], "opus")
        self.rv.comment("p", "x")
        self.assertFalse(self.rv.set_status("p", "read"))   # queued

    def test_available_models(self):
        claude = ["sonnet", "opus", "fable", "haiku"]
        agents._available[1] = None
        self.assertEqual(agents.available_models(), claude)      # no key, no Ollama
        self.assertFalse(self.rv.set_model("p", "gemma4:26b-a4b"))

        class Ollama(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                data = json.dumps({"models": [{"name": "gpt-oss-20b-t64:latest"}, {"name": "other"}]}).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass
        ollama = http.server.HTTPServer(("127.0.0.1", 0), Ollama)
        threading.Thread(target=ollama.serve_forever, daemon=True).start()
        self.addCleanup(ollama.server_close)
        self.addCleanup(ollama.shutdown)
        util.write(agents.GENAI_KEY_FILE, "k\n")
        with mock.patch.object(agents, "OLLAMA_URL", "http://127.0.0.1:%d" % ollama.server_address[1]):
            self.assertEqual(agents.available_models(), claude)  # cached
            agents._available[1] = None
            self.assertEqual(agents.available_models(), claude + ["gpt-oss-20b-t64"] + list(agents.GENAI_MODELS))
            self.assertTrue(self.rv.set_model("p", "gemma4:26b-a4b"))
        os.remove(agents.GENAI_KEY_FILE)
        agents._available[1] = None
        self.assertEqual(self.rv.state("p")["models"], claude + ["gemma4:26b-a4b"])  # its own, though gone
        agents._available[1] = None

    @mock.patch.object(agents, "available_models", lambda: agents.MODELS)
    def test_one_genai_agent_at_a_time(self):
        started = []
        self.rv._run = lambda agent, prompt: started.append(agent)
        for a in ("q", "r"):
            util.write(os.path.join(self.root, a, "index.html"), "<html></html>")
        for a, model in (("p", "gpt-oss:120b"), ("q", "qwen3.8:27b"), ("r", "gpt-oss-20b-t64")):
            self.rv.set_model(a, model)
            self.rv.comment(a, "go")
        # held for the Claude limits, yet p and r start; q waits for p, not for the limit
        self.assertEqual((started, self.rv.queue, self.rv.genai_agent), (["p", "r"], [("q", "go")], "p"))
        self.assertEqual(self.data()["q"]["status"], "working")
        self.rv._genai_done("p")            # p's run ended
        self.rv._start_queued()
        self.assertEqual((started, self.rv.genai_agent), (["p", "r", "q"], "q"))
        self.rv._genai_done("q")

    @mock.patch.object(agents, "available_models", lambda: agents.MODELS)
    def test_genai_agent_waits_for_another_trees(self):
        started = []
        self.rv._run = lambda agent, prompt: started.append(agent)
        self.rv.set_model("p", "gemma4:26b-a4b")
        with mock.patch.object(agents.genai_relay, "claim", lambda: None):   # another server has it
            self.rv.comment("p", "go")
        self.assertEqual((started, self.rv.queue), ([], [("p", "go")]))
        self.assertTrue(self.rv.genai_timer.is_alive())
        self.rv.genai_timer.cancel()
        self.rv._start_queued()             # the recheck, once it's free
        self.assertEqual((started, self.rv.genai_agent), (["p"], "p"))
        self.rv._genai_done("p")

    def test_prune_threads(self):
        old = (datetime.datetime.now() - datetime.timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S")
        thread = [{"role": "system", "time": old, "text": str(i)} for i in range(10)]
        thread.append({"role": "system", "time": agents.now(), "text": "new"})
        with open(os.path.join(self.root, "www", "agents.json"), "w") as f:
            json.dump({"p": {"status": "read", "thread": thread}}, f)
        self.rv.prune_threads()
        self.assertEqual(self.texts(), ["5", "6", "7", "8", "9", "new"])

    def test_permissions_mode(self):
        self.assertEqual(self.rv.permissions(), "allowlist")
        self.assertFalse(self.rv.set_permissions("yolo"))
        self.assertTrue(self.rv.set_permissions("ask"))
        self.assertEqual(self.rv.permissions(), "ask")

    def test_refusal_writes_nothing(self):
        self.assertFalse(self.rv.new_chat("ghost"))
        self.assertFalse(self.rv.set_repeat("ghost", "off"))
        self.assertNotIn("ghost", self.data())

    def test_exception_discards_changes(self):
        with self.assertRaises(KeyError):
            with self.rv._edit("p") as st:
                st["status"] = "closed"
                raise KeyError("boom")
        self.assertNotEqual(self.data().get("p", {}).get("status"), "closed")

    def test_check_job_waits(self):
        self.rv.comment("p", "submit")
        self.rv.cancel("p")
        with self.rv._edit("p") as st:
            self.rv._start_job_wait(st, ["11", "12"])
        queue = [{"id": "12", "workdir": "/elsewhere"}]
        stubs = {"active_jobs": lambda: list(queue), "agent_jobs": lambda d, all_jobs=None, fresh=False: [],
                 "job_report": lambda ids: "report for " + ",".join(ids)}
        saved = {k: getattr(agents.slurm, k) for k in stubs}
        try:
            for k, f in stubs.items():
                setattr(agents.slurm, k, f)
            self.rv.check_job_waits()                      # 12 still queued: keep waiting
            st = self.data()["p"]
            self.assertEqual(st["job_wait"]["jobs"], ["11", "12"])
            self.assertTrue(st["working_on"].startswith("Waiting for 1 SLURM job (12)"))
            queue.clear()
            self.rv.check_job_waits()                      # all gone: message the agent
            st = self.data()["p"]
        finally:
            for k, f in saved.items():
                setattr(agents.slurm, k, f)
        self.assertNotIn("job_wait", st)
        self.assertEqual(st["auto_runs"], 1)
        self.assertIn("SLURM jobs finished:\nreport for 11,12", self.texts())
        self.assertIn("The SLURM jobs you were waiting on have left the queue:\nreport for 11,12", st["pending"])

    def test_retry_after_limit(self):
        self.rv.hold_until = 0
        until = time.time() + 600
        self.rv._retry_after_limit("p", "do it", {"text": "You've hit your limit"}, "s1", until)
        self.assertEqual(self.rv.queue, [("p", agent_prompts.LIMIT_RETRY + "do it")])
        self.assertEqual(self.rv.hold_until, until)
        self.assertEqual(self.rv.hold_reason, "Claude usage limit hit (You've hit your limit)")
        self.assertEqual(self.data()["p"]["session_id"], "s1")
        self.rv.queue.clear()
        self.rv._retry_after_limit("p", agent_prompts.LIMIT_RETRY + "x", {"text": "t"}, "s1", until - 60)
        self.assertEqual(self.rv.queue, [("p", agent_prompts.LIMIT_RETRY + "x")])   # not wrapped twice
        self.assertEqual(self.rv.hold_until, until)                                  # the later wait stays

    def test_finish_waits_for_jobs_up_to_max_auto(self):
        entry = {"role": "claude", "time": agents.now(), "text": "submitted"}
        self.rv._finish("p", entry, None, [], "s1", ["7"])
        st = self.data()["p"]
        self.assertEqual((st["status"], st["job_wait"]["jobs"]), ("working", ["7"]))
        with self.rv._edit("p") as st:
            st.pop("job_wait")
            st["auto_runs"] = agents.MAX_AUTO
        self.rv._finish("p", entry, None, [], "s1", ["8"])
        st = self.data()["p"]
        self.assertEqual(st["status"], "unread")
        self.assertNotIn("job_wait", st)
        self.assertTrue(self.texts()[-1].startswith("SLURM jobs 8 are still queued"))

    def test_migrates_old_state(self):
        """A tree served before 2026-10: reviews.json, page_prev/ and the "watch" key, renamed."""
        root = util.new_tree("agents-migrate")
        util.write(os.path.join(root, "www", "page_prev", "p.html"), "old")
        util.write(os.path.join(root, "www", "reviews.json"), json.dumps(
            {"p": {"status": "working", "thread": [], "watch": {"jobs": ["5"], "since": 1}}}))
        agents2 = agents.Agents(root)
        if agents2.timer:
            agents2.timer.cancel()
        www = os.path.join(root, "www")
        self.assertFalse(os.path.exists(os.path.join(www, "reviews.json")))
        self.assertTrue(os.path.isfile(os.path.join(www, "before_run", "p.html")))
        with open(os.path.join(www, "agents.json")) as f:
            st = json.load(f)["p"]
        self.assertEqual((st["status"], st["job_wait"]["jobs"]), ("working", ["5"]))   # still waiting
        self.assertNotIn("watch", st)
        self.assertEqual(agents2.state("p")["watching"], ["5"])

    def test_command(self):
        agent_dir = os.path.join(self.root, "p")
        cmd = self.rv._command(agent_dir, "haiku", ["Read(//data/**)"], "sess9")
        self.assertEqual(cmd[:3], [agents.CLAUDE_CMD, "-p", "--model"])
        self.assertEqual(cmd[-2:], ["--resume", "sess9"])
        self.assertIn("Read(//data/**)", cmd)
        prompt = cmd[cmd.index("--append-system-prompt") + 1]
        self.assertIn("You are the agent\nof the folder %s:" % agent_dir, prompt)
        self.assertIn("its\n%s/index.html is your report" % agent_dir, prompt)
        self.assertNotIn("{", prompt.split("\n\n")[0])      # every placeholder filled


if __name__ == "__main__":
    unittest.main()
