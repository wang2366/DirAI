"""review.Reviews in process: the queue, usage holds, cancel, restarts, repeats, grants, pruning.
Runs are held back (hold_until in the future) so nothing starts unless a test wants it to."""
import datetime
import json
import os
import time
import unittest

from tests import util

import review


class ReviewsTest(unittest.TestCase):
    def setUp(self):
        self.root = util.new_tree("reviews-" + self.id().rsplit(".", 1)[1])
        util.write(os.path.join(self.root, "p", "index.html"), "<html><body>p</body></html>")
        self.rv = review.Reviews(self.root)
        self.rv.hold_until, self.rv.hold_reason = time.time() + 3600, "test hold"

    def tearDown(self):
        if self.rv.timer:
            self.rv.timer.cancel()

    def data(self):
        with open(os.path.join(self.root, "www", "reviews.json")) as f:
            return json.load(f)

    def texts(self, page="p"):
        return [m["text"] for m in self.data()[page]["thread"]]

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
        with open(os.path.join(self.root, "www", "reviews.json"), "w") as f:
            json.dump(data, f)
        rv2 = review.Reviews(self.root)
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
        self.assertTrue(st["pending"].startswith("The owner selected this text on the page"))

    def test_new_chat_and_fresh_prompt(self):
        self.assertFalse(self.rv.new_chat("p"))              # no session yet
        self.rv.comment("p", "first")
        self.rv.cancel("p")
        data = self.data()
        data["p"]["session_id"] = "s1"
        with open(os.path.join(self.root, "www", "reviews.json"), "w") as f:
            json.dump(data, f)
        self.assertTrue(self.rv.new_chat("p"))
        self.assertEqual(self.texts()[-1], review.NEW_CHAT_MARK)
        self.rv.comment("p", "second")
        self.assertTrue(self.data()["p"]["pending"].startswith("This is a fresh session on a page"))

    def test_repeat(self):
        self.assertFalse(self.rv.set_repeat("p", "fortnight", "x"))
        self.assertFalse(self.rv.set_repeat("p", "day", " "))
        self.assertFalse(self.rv.set_repeat("p", "off"))      # nothing to turn off
        self.assertTrue(self.rv.set_repeat("p", "hour", "check it"))
        self.assertTrue(self.texts()[-1].startswith("Repeats every hour, next at"))
        data = self.data()
        data["p"]["repeat"]["next"] = time.time() - 2.5 * 3600   # missed while the server was down
        with open(os.path.join(self.root, "www", "reviews.json"), "w") as f:
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
        with open(os.path.join(self.root, "www", "reviews.json"), "w") as f:
            json.dump(data, f)
        self.assertFalse(self.rv.grant("p", ["Bash(sudo x)"], True))  # always denied: nothing left
        self.assertTrue(self.rv.grant("p", ["Bash(make)", "Read(//data/**)"], True))
        st = self.data()["p"]
        self.assertEqual(st["grants"], ["Read(//data/**)"])           # folder reads stay with the page
        with open(review.PERMS_FILE) as f:
            self.assertIn("Bash(make)", json.load(f)["always"])
        self.assertEqual([m["text"] for m in st["thread"][-3:-1]],
                         ["Granted (always): Bash(make)", "Granted (this page): Read(//data/**)"])
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

    def test_prune_threads(self):
        old = (datetime.datetime.now() - datetime.timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S")
        thread = [{"role": "system", "time": old, "text": str(i)} for i in range(10)]
        thread.append({"role": "system", "time": review.now(), "text": "new"})
        with open(os.path.join(self.root, "www", "reviews.json"), "w") as f:
            json.dump({"p": {"status": "read", "thread": thread}}, f)
        self.rv.prune_threads()
        self.assertEqual(self.texts(), ["5", "6", "7", "8", "9", "new"])

    def test_permissions_mode(self):
        self.assertEqual(self.rv.permissions(), "allowlist")
        self.assertFalse(self.rv.set_permissions("yolo"))
        self.assertTrue(self.rv.set_permissions("ask"))
        self.assertEqual(self.rv.permissions(), "ask")

    def test_command(self):
        page_dir = os.path.join(self.root, "p")
        cmd = self.rv._command(page_dir, "haiku", ["Read(//data/**)"], "sess9")
        self.assertEqual(cmd[:3], [review.CLAUDE_CMD, "-p", "--model"])
        self.assertEqual(cmd[-2:], ["--resume", "sess9"])
        self.assertIn("Read(//data/**)", cmd)
        prompt = cmd[cmd.index("--append-system-prompt") + 1]
        self.assertIn("The page is %s/index.html" % page_dir, prompt)
        self.assertNotIn("{", prompt.split("\n\n")[0])      # every placeholder filled


if __name__ == "__main__":
    unittest.main()
