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
import agent_permissions


def perms_rules(command):
    return agent_permissions.denial_rules({"tool_name": "Bash", "tool_input": {"command": command}})


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

    def test_no_git_runs_and_warns_once(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertFalse(agents.in_git(self.root))      # no FileNotFoundError
            self.rv._begin("p")
            self.rv._begin("p")
        self.assertEqual(self.texts().count(agents.GIT_MISSING), 1)

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

    def save(self, data):
        with open(os.path.join(self.root, "www", "agents.json"), "w") as f:
            json.dump(data, f)

    def run_ending_with(self, entry):
        """Run p's queued message to the end, its claude replaced by one that gives entry."""
        self.rv.queue = [i for i in self.rv.queue if i[0] != "p"]
        self.rv.running += 1      # as _start_queued would; _run gives the slot back
        with mock.patch.object(self.rv, "_attempt", return_value=(entry, None, [], "s1")), \
                mock.patch.object(self.rv, "_jobs_to_wait_for", return_value=[]):
            self.rv._run("p", "first")

    def test_crash_in_run_says_run_failed(self):
        self.rv.running += 1
        with mock.patch.object(self.rv, "_command", side_effect=FileNotFoundError("git")), \
                mock.patch("traceback.print_exc"):
            self.rv._run("p", "first")      # inside _attempt's try: its own "Run failed"
        self.assertTrue(self.texts()[-1].startswith("Run failed: git"))
        self.assertEqual(self.data()["p"]["status"], "unread")
        self.rv.running += 1
        with mock.patch.object(self.rv, "_attempt", side_effect=KeyError("boom")), \
                mock.patch("traceback.print_exc"):
            self.rv._run("p", "again")      # anywhere else: _run's catch-all
        self.assertEqual(self.texts()[-1], "Run failed: KeyError: 'boom' (details in www/serve_node.log).")
        self.assertEqual(self.data()["p"]["status"], "unread")
        self.assertEqual(self.rv.running, 0)

    def test_inbox_while_busy_goes_as_one_message(self):
        self.assertTrue(self.rv.comment("p", "first"))
        self.assertFalse(self.rv.comment("p", "not queued"))                  # schedules etc.: still refused
        self.assertEqual(self.rv.comment("p", "second", queue=True), "queued")
        self.assertEqual(self.rv.comment("p", "third", queue=True, selection={"text": "p", "heading": "H"}), "queued")
        st = self.data()["p"]
        self.assertEqual([m["text"] for m in st["inbox"]], ["second", "third"])
        self.assertEqual(self.rv.all_status()["p"]["inbox"], 2)
        self.run_ending_with({"role": "claude", "time": agents.now(), "text": "done"})
        st = self.data()["p"]
        self.assertNotIn("inbox", st)
        self.assertEqual(st["status"], "queued")                            # the held test queue
        self.assertEqual([m for m in st["thread"] if m["role"] == "user"][-1]["text"], "1) second\n\n2) third")
        self.assertTrue(st["pending"].startswith("The owner sent these 2 messages while you were working"))
        self.assertIn("2) The owner selected this text in index.html", st["pending"])

    def test_inbox_one_message_goes_as_it_is(self):
        self.rv.comment("p", "first")
        self.rv.comment("p", "second", queue=True)
        self.run_ending_with({"role": "claude", "time": agents.now(), "text": "done"})
        self.assertEqual(self.data()["p"]["pending"], "second")

    def test_inbox_held_after_cancel_until_send_now(self):
        self.rv.comment("p", "first")
        self.rv.comment("p", "second", queue=True)
        self.run_ending_with(agents.system_entry("Cancelled by the owner."))
        st = self.data()["p"]
        self.assertEqual((st["status"], [m["text"] for m in st["inbox"]]), ("unread", ["second"]))
        mid = st["inbox"][0]["id"]
        self.assertTrue(self.rv.change_inbox("p", mid, "second, edited"))
        self.assertTrue(self.rv.send_inbox("p"))
        st = self.data()["p"]
        self.assertNotIn("inbox", st)
        self.assertEqual(st["pending"], "second, edited")
        self.assertFalse(self.rv.send_inbox("p"))                          # nothing left
        self.assertFalse(self.rv.change_inbox("p", mid, "x"))              # already sent

    def test_inbox_remove_and_limit(self):
        self.rv.comment("p", "first")
        with mock.patch.object(agents, "INBOX_MAX", 2):
            self.assertEqual(self.rv.comment("p", "a", queue=True), "queued")
            self.assertEqual(self.rv.comment("p", "b", queue=True), "queued")
            self.assertFalse(self.rv.comment("p", "c", queue=True))
        for m in self.data()["p"]["inbox"]:
            self.assertTrue(self.rv.change_inbox("p", m["id"]))
        self.assertNotIn("inbox", self.data()["p"])
        self.assertFalse(self.rv.send_inbox("p"))

    def test_next_run(self):
        """Next runs come from the calendar, in local time: 15:00 stays 15:00 when daylight saving ends."""
        with mock.patch.dict(os.environ, {"TZ": "America/Indiana/Indianapolis"}):
            time.tzset()
            try:
                at = lambda s: time.mktime(time.strptime(s, "%Y-%m-%d %H:%M"))   # noqa: E731
                show = lambda t: time.strftime("%a %Y-%m-%d %H:%M %Z", time.localtime(t))   # noqa: E731
                sat = at("2026-10-24 10:00")
                fri = {"kind": "weekly", "days": [4], "time": "15:00"}
                n1 = agents.next_run(fri, sat)
                n2 = agents.next_run(fri, n1)
                self.assertEqual((show(n1), show(n2)), ("Fri 2026-10-30 15:00 EDT", "Fri 2026-11-06 15:00 EST"))
                self.assertEqual(n2 - n1, 7 * 86400 + 3600)
                daily = {"kind": "daily", "time": "08:00"}
                self.assertEqual(show(agents.next_run(daily, sat)), "Sun 2026-10-25 08:00 EDT")
                self.assertEqual(show(agents.next_run(daily, at("2026-10-24 07:00"))), "Sat 2026-10-24 08:00 EDT")
                self.assertEqual(show(agents.next_run(daily, at("2026-10-24 08:00"))), "Sun 2026-10-25 08:00 EDT")
                self.assertEqual(show(agents.next_run({"kind": "hourly", "time": "00:15"}, at("2026-10-24 10:20"))),
                                 "Sat 2026-10-24 11:15 EDT")
                self.assertEqual(show(agents.next_run({"kind": "weekly", "days": [0, 4], "time": "09:00"}, sat)),
                                 "Mon 2026-10-26 09:00 EDT")
                once = {"kind": "once", "date": "2026-10-27", "time": "09:00"}
                self.assertEqual(show(agents.next_run(once, sat)), "Tue 2026-10-27 09:00 EDT")
                self.assertIsNone(agents.next_run(once, at("2026-10-28 00:00")))
            finally:
                time.tzset()    # back to the zone the tests started in (mock restores TZ first)

    def test_schedule_fields(self):
        bad = [{"kind": "yearly", "time": "08:00"}, {"kind": "daily", "time": "25:00"},
               {"kind": "weekly", "time": "08:00", "days": []}, {"kind": "once", "date": "x", "time": "08:00"},
               {"kind": "once", "date": "2020-01-01", "time": "08:00"}]
        self.assertTrue(all(agents.clean_schedule(b)[1] for b in bad))
        self.assertEqual(agents.clean_schedule(bad[-1])[1], "That time has passed.")
        why, runs = agents.preview_schedule({"kind": "daily", "time": "08:00"})
        self.assertEqual((why, len(runs)), (None, 2))
        self.assertEqual([agents.schedule_label(s) for s in (
            {"kind": "daily", "time": "08:00"}, {"kind": "weekly", "days": [0, 4], "time": "15:00"},
            {"kind": "hourly", "time": "00:15"}, {"kind": "once"})],
            ["daily 08:00", "weekly Mon, Fri 15:00", "every hour at :15", "once"])

    def test_schedule(self):
        self.assertEqual(self.rv.set_schedule("p", {"kind": "daily", "time": "08:00"}), "Write the message to send.")
        self.assertIsNone(self.rv.set_schedule("p", {"kind": "daily", "time": "08:00", "text": "check queue"}))
        self.assertIsNone(self.rv.set_schedule("p", {"kind": "weekly", "days": [4], "time": "15:00", "text": "summary"}))
        self.assertTrue(self.texts()[-1].startswith("Scheduled (weekly Fri 15:00), next Fri"))
        sid = self.data()["p"]["schedules"][0]["id"]
        self.assertIsNone(self.rv.set_schedule("p", {"id": sid, "kind": "daily", "time": "09:30", "text": "check queue"}))
        self.assertEqual([s["time"] for s in self.data()["p"]["schedules"] if s["id"] == sid], ["09:30"])   # edited in place
        self.assertIsNotNone(self.rv.set_schedule("p", {"id": "gone", "kind": "daily", "time": "09:30", "text": "x"}))
        self.assertFalse(self.rv.change_schedule("p", sid, "explode"))
        self.assertTrue(self.rv.change_schedule("p", sid, "pause"))
        self.assertTrue(self.rv.all_status()["p"]["schedule"].endswith("15:00"))   # paused ones don't count
        st = self.rv.state("p")
        self.assertTrue(st["tz"] and all(s["when"] and s["label"] for s in st["schedules"]))
        # both missed for days while the server was down: the weekly one goes, once; the paused one doesn't
        data = self.data()
        for s in data["p"]["schedules"]:
            s["next"] = time.time() - 2.5 * 86400
        self.save(data)
        self.rv.check_schedules()
        st = self.data()["p"]
        self.assertEqual([m.get("scheduled") for m in st["thread"] if m["role"] == "user"], ["weekly Fri 15:00 · fresh chat"])
        self.assertTrue(st["pending"].startswith("(Scheduled run (weekly Fri 15:00 · fresh chat), set by the owner."))
        weekly = [s for s in st["schedules"] if s["kind"] == "weekly"][0]
        self.assertTrue(time.time() < weekly["next"] <= time.time() + 7 * 86400)
        self.rv.check_schedules()             # busy now: nothing more goes
        self.assertEqual(len([m for m in self.data()["p"]["thread"] if m["role"] == "user"]), 1)
        self.rv.cancel("p")
        self.assertTrue(self.rv.change_schedule("p", sid, "resume"))
        resumed = [s for s in self.data()["p"]["schedules"] if s["id"] == sid][0]
        self.assertTrue("paused" not in resumed and resumed["next"] > time.time())
        self.assertTrue(self.rv.change_schedule("p", sid, "delete"))
        self.assertFalse(self.rv.change_schedule("p", sid, "delete"))

    def test_schedule_once_continues_the_chat(self):
        t = time.localtime(time.time() + 3600)
        self.assertIsNone(self.rv.set_schedule("p", {"kind": "once", "date": time.strftime("%Y-%m-%d", t),
                                                     "time": time.strftime("%H:%M", t), "text": "rerun fit",
                                                     "session": "continue"}))
        data = self.data()
        data["p"]["schedules"][0]["next"] = time.time() - 60          # came due
        data["p"]["session_id"] = "s1"
        self.save(data)
        self.rv.check_schedules()
        st = self.data()["p"]
        self.assertEqual(st["schedules"], [])                         # a once removes itself
        self.assertEqual((st["session_id"], st["pending"]), ("s1", "rerun fit"))   # same session, like Send
        self.assertTrue([m for m in st["thread"] if m["role"] == "user"][-1]["scheduled"].startswith("set for "))

    def test_old_repeat_and_later_migrate(self):
        nxt = time.mktime(time.strptime("2026-10-27 10:47", "%Y-%m-%d %H:%M"))
        self.save({"p": {"status": "read", "thread": [], "session_id": None, "denials": [], "grants": [],
                         "repeat": {"every": "week", "text": "weekly", "next": nxt},
                         "later": [{"id": "ab12", "text": "held", "at": nxt + 60,
                                    "selection": {"text": "x", "heading": ""}}]}})
        rv2 = agents.Agents(self.root)
        try:
            st = self.data()["p"]
            self.assertFalse("repeat" in st or "later" in st)
            rep, held = st["schedules"]
            self.assertEqual((rep["kind"], rep["days"], rep["time"], rep["next"], rep["session"]),
                             ("weekly", [time.localtime(nxt).tm_wday], "10:47", nxt, "fresh"))
            self.assertEqual((held["id"], held["kind"], held["session"], held["selection"]["text"]),
                             ("ab12", "once", "continue", "x"))
        finally:
            if rv2.timer:
                rv2.timer.cancel()

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
        self.assertEqual(st["grants"], ["Bash(make)", "Read(//data/**)"])   # kept for this agent only
        self.assertEqual(self.rv.state("p")["grant_info"], [{"rule": "Bash(make)", "denied": False, "unusable": ""},
                                                            {"rule": "Read(//data/**)", "denied": False, "unusable": ""}])
        self.assertEqual(st["thread"][-2]["text"], "Granted (this agent): Bash(make), Read(//data/**)")
        self.assertTrue(st["pending"].startswith("The owner granted these permissions: Bash(make), Read(//data/**)."))
        self.assertNotIn("inline", st["pending"])

    def test_always_keeps_only_rules_that_can_recur(self):
        # F2: Always allow on a heredoc's pieces keeps none of the script lines; they go once
        data = {"p": dict(agents.Agents._blank(), session_id="s1")}
        with open(os.path.join(self.root, "www", "agents.json"), "w") as f:
            json.dump(data, f)
        rules = perms_rules("python3 - <<'EOF'\nimport os\nself.cards = {}\nEOF\nmake all")
        self.assertTrue(self.rv.grant("p", rules, True))
        st = self.data()["p"]
        self.assertEqual(st["grants"], ["Bash(make all:*)"])
        self.assertEqual(st["once"], sorted(r for r in rules if r != "Bash(make all:*)"))
        self.assertIn("write such a script to a file in your folder", st["pending"].lower())

    def test_remove_grant(self):
        # F4: the × in the Permissions list
        data = {"p": dict(agents.Agents._blank(), grants=["Bash(import os)", "Bash(make)", "Read(//data/**)"])}
        with open(os.path.join(self.root, "www", "agents.json"), "w") as f:
            json.dump(data, f)
        info = self.rv.state("p")["grant_info"]
        self.assertEqual([bool(g["unusable"]) for g in info], [True, False, False])
        self.assertEqual(self.rv.remove_grant("p", ["Bash(import os)"]), 1)
        self.assertEqual(self.data()["p"]["grants"], ["Bash(make)", "Read(//data/**)"])
        self.assertEqual(self.texts()[-1], "Permission removed: Bash(import os)")
        self.assertEqual(self.rv.remove_grant("p", ["Bash(nope)"]), 0)     # unknown: nothing changes
        self.assertEqual(self.data()["p"]["grants"], ["Bash(make)", "Read(//data/**)"])

    def test_colleague_modes(self):
        # F5: read -> own -> all -> read; own keeps the agents inside read-only
        top = os.path.join(self.root, "d")
        util.write(os.path.join(top, "index.html"), "<html><body>d</body></html>")
        util.write(os.path.join(top, "lib", "x.py"), "")
        util.write(os.path.join(top, "sub", "a", "index.html"), "<html></html>")
        util.write(os.path.join(top, "sub", "me", "index.html"), "<html></html>")
        util.write(os.path.join(self.root, "leaf", "index.html"), "<html></html>")
        data = {"d/sub/me": dict(agents.Agents._blank(), colleagues=["d", "leaf"]),
                "d": dict(agents.Agents._blank(), grants=["Bash(make)", "Edit(//x/y.py)"])}
        with open(os.path.join(self.root, "www", "agents.json"), "w") as f:
            json.dump(data, f)
        me = "d/sub/me"
        self.assertEqual([(c["mode"], c["next"]) for c in self.rv.state(me)["colleagues"]], [("read", "own"), ("read", "own")])
        self.assertEqual(self.rv._begin(me)[1], ["Bash(make)"])                     # read: no edits
        self.assertIsNone(self.rv.set_colleague_mode(me, "d", "own"))
        self.assertIsNone(self.rv.set_colleague_mode(me, "leaf", "own"))
        self.assertEqual([(c["mode"], c["next"]) for c in self.rv.state(me)["colleagues"]], [("own", "all"), ("own", "read")])
        session, grants, model, colls, modes, local = self.rv._begin(me)[:6]
        self.assertEqual((grants, modes, local), (["Bash(make)", "Edit(//x/y.py)"], {"d": "own", "leaf": "own"}, []))
        cmd = self.rv._command(os.path.join(self.root, me), "haiku", grants, None, colls, modes, local)
        allow = cmd[cmd.index("--allowedTools") + 1:cmd.index("--disallowedTools")]
        deny = cmd[cmd.index("--disallowedTools") + 1:]
        self.assertIn("Edit(/%s/**)" % top, allow)
        self.assertIn("Edit(/%s/sub/a/**)" % top, deny)                            # an agent inside: read-only
        self.assertNotIn("Edit(/%s/sub/me/**)" % top, deny)                         # never its own folder
        self.assertNotIn("Edit(/%s/**)" % os.path.join(self.root, "leaf"), deny)
        prompt = cmd[cmd.index("--append-system-prompt") + 1]
        self.assertIn("- %s: may edit its own files, not the folders of the agents inside it" % top, prompt)
        self.assertIsNone(self.rv.set_colleague_mode(me, "d", "all"))
        cmd = self.rv._command(os.path.join(self.root, me), "haiku", grants, None, colls, self.rv._begin(me)[4], [])
        self.assertEqual(cmd[cmd.index("--disallowedTools") + 1:], agents.ALWAYS_DENY)
        self.assertIn("isn't a colleague", self.rv.set_colleague_mode(me, "nope", "own"))
        self.assertIn("Unknown", self.rv.set_colleague_mode(me, "d", "write"))
        self.assertIsNone(self.rv.set_colleague_mode(me, "d", "read"))
        self.assertEqual(self.rv.colleague_modes(me), {"leaf": "own"})
        self.assertTrue(self.rv.remove_colleague(me, "leaf"))                      # removing drops its mode
        self.assertNotIn("coll_mode", self.data()[me])

    def test_ask_once_only(self):
        # F2/F3 in ask mode: a heredoc's lines aren't kept by Always, and Deny says to use a file
        sent = []

        class Live:
            granted, pending = set(), {}

            def waiting(self):
                return 0

            def hold(self, rid, req):
                self.pending[rid] = req

            def release(self, rid):
                return self.pending.pop(rid, None)

            def send(self, msg):
                sent.append(msg)
        live = Live()
        self.rv.live["p"] = live
        req = {"tool_name": "Bash", "input": {"command": "python3 - <<'EOF'\nimport os\nEOF"}}
        self.rv._ask("p", live, "r1", req)
        e = self.data()["p"]["thread"][-1]
        self.assertEqual((e["rules"], e["heredoc"]), ([], True))
        self.assertTrue(e["once_only"])
        self.assertTrue(self.rv.answer("p", "r1", "deny"))
        self.assertIn("Write such a script to a file", sent[-1]["response"]["response"]["message"])

    def test_denied_count_and_dismiss(self):
        blocked = {"tool_name": "Bash", "tool_input": {"command": "git push --force"}}
        data = {"p": dict(agents.Agents._blank(), status="unread", session_id="s1",
                          denials=[blocked, {"tool_name": "Edit", "tool_input": {"file_path": "/x/y.py"}}])}
        with open(os.path.join(self.root, "www", "agents.json"), "w") as f:
            json.dump(data, f)
        self.assertEqual(self.rv.all_status()["p"]["denied"], 2)   # blocked ones count too
        self.assertTrue(self.rv.dismiss_denials("p"))
        self.assertEqual(self.rv.all_status()["p"]["denied"], 0)
        self.assertFalse(self.rv.dismiss_denials("p"))   # nothing left to dismiss
        self.assertEqual(self.data()["p"]["grants"], [])   # nothing was granted

    def test_grant_once_and_colleagues(self):
        util.write(os.path.join(self.root, "q", "index.html"), "<html><body>q</body></html>")
        data = {"p": dict(agents.Agents._blank(), session_id="s1", colleagues=["q"]),
                "q": dict(agents.Agents._blank(), grants=["Bash(basecamp:*)", "Edit(//x/y.py)"],
                          colleagues=["r"]),
                "r": dict(agents.Agents._blank(), grants=["Bash(make)"])}
        with open(os.path.join(self.root, "www", "agents.json"), "w") as f:
            json.dump(data, f)
        self.assertTrue(self.rv.grant("p", ["Bash(ls -Z)"], False))
        st = self.data()["p"]
        self.assertEqual((st["grants"], st["once"]), ([], ["Bash(ls -Z)"]))
        # the next run gets q's grants but not its edits, nor r's (q's colleague); and the once-only rule, used up
        # its Permissions list shows only its own grants; r's list flags a rule ALWAYS_DENY blocks
        self.assertEqual(self.rv.state("p")["grant_info"], [])
        data = self.data()
        data["r"]["grants"].append("Bash(sudo ls)")
        with open(os.path.join(self.root, "www", "agents.json"), "w") as f:
            json.dump(data, f)
        self.assertEqual([g["denied"] for g in self.rv.state("r")["grant_info"]], [False, True])
        self.assertEqual(self.rv._begin("p")[1], ["Bash(basecamp:*)", "Bash(ls -Z)"])
        self.assertNotIn("once", self.data()["p"])
        self.assertEqual(self.rv._begin("p")[1], ["Bash(basecamp:*)"])

    def test_compact_needs_session(self):
        self.assertFalse(self.rv.compact("p"))

    def seed_session(self, **extra):
        data = self.data()
        data["p"] = dict({"status": "unread", "thread": [], "session_id": "s"}, **extra)
        with open(os.path.join(self.root, "www", "agents.json"), "w") as f:
            json.dump(data, f)

    def auto_compact(self, ctx, prompt="hi"):
        with mock.patch.object(agents, "context_tokens", return_value=ctx):
            return self.rv._auto_compact("p", prompt)

    def test_auto_compact_at_the_limit(self):
        self.seed_session()
        self.assertFalse(self.auto_compact(199000))                     # under the default 200K
        self.assertEqual(self.rv.queue, [])
        self.assertTrue(self.auto_compact(212000))
        self.assertEqual(self.rv.queue, [("p", agents.COMPACT_KEEP)])   # with the keep-instructions
        self.assertTrue(agents.is_compact(agents.COMPACT_KEEP))
        self.assertIn("Auto compact (212K >= 200K).", self.texts())
        self.assertTrue(self.data()["p"]["auto_compacting"])
        self.assertFalse(self.auto_compact(250000))                     # busy now

    def test_auto_compact_not_after_a_compact_nor_with_jobs_nor_off(self):
        self.seed_session()
        self.assertFalse(self.auto_compact(300000, agents.COMPACT_KEEP))
        self.seed_session(job_wait={"jobs": ["1"], "since": 0}, status="working")
        self.assertFalse(self.auto_compact(300000))
        self.seed_session(auto_compact=0)
        self.assertFalse(self.auto_compact(300000))
        self.assertEqual(self.rv.queue, [])

    def test_auto_compact_per_agent_and_tree_limit(self):
        self.seed_session()
        self.assertFalse(self.rv.set_auto_compact("p", 123))
        self.assertTrue(self.rv.set_auto_compact("p", 100000))
        self.assertEqual(self.rv.state("p")["auto_compact"], 100000)
        self.assertTrue(self.auto_compact(120000))
        self.seed_session(model="gemma4:26b-a4b")                      # capped at 70% of its 65536 window
        self.assertEqual(self.rv.state("p")["auto_compact"], 45875)
        self.rv.config["auto_compact"] = 0
        self.seed_session()
        self.assertEqual(self.rv.state("p")["auto_compact"], 0)

    def test_auto_compact_pauses_when_it_did_not_shrink(self):
        self.seed_session(auto_compacting=True)
        self.rv._auto_compact_done("p", 250000, 250000)
        st = self.data()["p"]
        self.assertTrue(st["auto_compact_paused"])
        self.assertNotIn("auto_compacting", st)
        self.assertFalse(self.auto_compact(260000))                     # paused
        self.assertFalse(self.auto_compact(150000))                     # under the limit: resumes
        self.assertNotIn("auto_compact_paused", self.data()["p"])
        self.seed_session(auto_compacting=True)
        self.rv._auto_compact_done("p", 250000, 30000)                  # it shrank
        self.assertNotIn("auto_compact_paused", self.data()["p"])

    def test_cancelled_auto_compact_does_not_pause(self):
        self.seed_session(auto_compacting=True)
        self.rv._auto_compact_done("p", 203000, 203000, ran=False)      # cancelled by the owner
        st = self.data()["p"]
        self.assertNotIn("auto_compact_paused", st)
        self.assertNotIn("auto_compacting", st)
        self.assertTrue(self.auto_compact(260000))                      # next run end: compacts again

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
        self.assertFalse(self.rv.change_schedule("ghost", "x", "delete"))
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

    def test_colleagues(self):
        util.write(os.path.join(self.root, "q", "index.html"), "<html><body>q</body></html>")
        self.assertIn("itself", self.rv.add_colleague("p", "http://127.0.0.1:1/p/index.html"))
        self.assertIsNone(self.rv.add_colleague("p", "http://127.0.0.1:1/q/index.html"))
        self.assertIn("already", self.rv.add_colleague("p", "q"))
        self.assertEqual(self.rv.colleagues("p"), ["q"])
        self.assertEqual(self.rv.state("p")["colleagues"], [{"path": "q", "url": "/q/index.html", "gone": False,
                                                              "mode": "read", "next": "own"}])
        self.assertTrue(self.texts()[-1].startswith("Colleague added (read-only, from the next run): "))
        self.assertTrue(self.rv.remove_colleague("p", "q"))
        self.assertFalse(self.rv.remove_colleague("p", "q"))
        self.assertEqual(self.rv.colleagues("p"), [])

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
        self.assertNotIn("Your colleagues", prompt)
        q = os.path.join(self.root, "q")
        util.write(os.path.join(q, "index.html"), "<html><body>q</body></html>")
        cmd = self.rv._command(agent_dir, "haiku", [], None, ["q", "gone"])
        self.assertIn("Read(/%s/**)" % q, cmd)                          # gone: no rule
        self.assertNotIn("Read(/%s/**)" % os.path.join(self.root, "gone"), cmd)
        self.assertIn(q, cmd[cmd.index("--add-dir"):cmd.index("--append-system-prompt")])
        self.assertIn("- %s: no summary card" % q, cmd[cmd.index("--append-system-prompt") + 1])
        # F6: a colleague's Read(//tmp/**) is still allowed but makes no working directory; the agent's own does
        cmd = self.rv._command(agent_dir, "haiku", ["Read(//tmp/**)"], None, ["q"], {}, [])
        self.assertIn("Read(//tmp/**)", cmd)
        self.assertNotIn("/tmp", cmd[cmd.index("--add-dir"):cmd.index("--append-system-prompt")])
        cmd = self.rv._command(agent_dir, "haiku", ["Read(//tmp/**)"], None, ["q"], {}, ["Read(//tmp/**)"])
        self.assertIn("/tmp", cmd[cmd.index("--add-dir"):cmd.index("--append-system-prompt")])
        self.assertIn("%s/tmp/,\nnever /tmp" % agent_dir, cmd[cmd.index("--append-system-prompt") + 1])


if __name__ == "__main__":
    unittest.main()
