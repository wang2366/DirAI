"""Sticky notes (notes.py): kept in the agent's .notes.json, sent as one message (agents.comment(notes=)),
answered on the note by the agent (scripts/dirai_note.py), a follow-up for unanswered ones, the owner's
replies on a note. The marks and pop-ups on the page: tests/notes.js."""
import json
import os
import subprocess
import sys
import time
import unittest
from unittest import mock

from tests import test_highlights, util

import agents
import notes


class NotesFileTest(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.join(util.new_tree("notes-" + self.id().rsplit(".", 1)[1]), "p")
        os.makedirs(self.dir, exist_ok=True)

    def add(self, text, note="", **kw):
        got, why = notes.act(self.dir, {"op": "add", "note": dict(text=text, note=note, **kw)})
        self.assertIsNone(why)
        return got[-1]

    def test_add_edit_delete_state(self):
        a = self.add("rates agree", "which decks?", before="xx", after="yy", heading="H")
        b = self.add("deck 4")
        self.assertEqual((a["n"], b["n"], a["state"]), (1, 2, "open"))
        self.assertEqual(notes.load(self.dir)[0]["before"], "xx")
        notes.act(self.dir, {"op": "edit", "id": b["id"], "note": "  why?  "})
        self.assertEqual(notes.load(self.dir)[1]["note"], "why?")
        notes.act(self.dir, {"op": "state", "id": b["id"], "state": "done"})
        self.assertEqual(notes.load(self.dir)[1]["state"], "done")
        notes.act(self.dir, {"op": "delete", "id": a["id"]})
        self.assertEqual([x["n"] for x in notes.load(self.dir)], [2])
        self.assertEqual(self.add("next")["n"], 3)                   # numbers aren't reused while notes remain
        _, why = notes.act(self.dir, {"op": "delete", "id": "nope"})
        self.assertTrue(why)
        _, why = notes.act(self.dir, {"op": "add", "note": {"text": "  "}})
        self.assertTrue(why)

    def test_file_is_hidden_and_goes_with_the_last_note(self):
        a = self.add("x")
        self.assertTrue(os.path.exists(os.path.join(self.dir, ".notes.json")))
        notes.act(self.dir, {"op": "delete", "id": a["id"]})
        self.assertFalse(os.path.exists(os.path.join(self.dir, ".notes.json")))
        self.assertEqual(notes.load(self.dir), [])

    def test_two_processes_lose_no_write(self):
        """The server and dirai_note.py are two processes writing one .notes.json: the flock in _locked()
        makes them wait for each other (without it, about 40 of these 90 adds were lost)."""
        import multiprocessing
        each = 45

        def writer(tag):
            for i in range(each):
                notes.act(self.dir, {"op": "add", "note": {"text": "%s %d" % (tag, i)}})
        ps = [multiprocessing.get_context("fork").Process(target=writer, args=(t,)) for t in "AB"]
        for p in ps:
            p.start()
        for p in ps:
            p.join()
        got = notes.load(self.dir)
        self.assertEqual(len(got), 2 * each)
        self.assertEqual(sorted(x["n"] for x in got), list(range(1, 2 * each + 1)))

    def test_parse_reply(self):
        reply = ("Fixed both.\n1: done\n**2:** open, which deck do you mean?\n- 3: done (moved to Results)\n"
                 "Note 4 - open: needs the job\nThe 5 decks: done\n")
        self.assertEqual(notes.parse_reply(reply), {1: ("done", ""), 2: ("open", "which deck do you mean?"),
                                                   3: ("done", "(moved to Results)"), 4: ("open", "needs the job")})

    def test_close_from_reply(self):    # old-style reply lines, still read as a fallback
        a, b, c = self.add("a"), self.add("b"), self.add("c")
        notes.take(self.dir, [a["id"], b["id"], c["id"]])
        self.assertEqual(notes.close_from_reply(self.dir, "1: done\n2: open, which one?"), 2)
        got = {x["n"]: x for x in notes.load(self.dir)}
        self.assertEqual([got[n]["state"] for n in (1, 2, 3)], ["done", "open", "sent"])
        self.assertEqual(got[2]["answer"], "which one?")
        self.assertEqual(got[2]["thread"][-1]["who"], "agent")
        notes.close_from_reply(self.dir, "2: done")                   # open (not sent) notes aren't marked
        self.assertEqual(notes.load(self.dir)[1]["state"], "open")
        self.assertEqual(notes.strip_reply("Fixed.\n1: done\n2: open, x\nThe 5 decks: done", [1, 2]),
                         "Fixed.\nThe 5 decks: done")

    def test_answer_command(self):      # scripts/dirai_note.py, as the agent runs it (E1b)
        a, b = self.add("a"), self.add("b")
        notes.take(self.dir, [a["id"]])
        cmd = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "dirai_note.py")
        env = dict(os.environ, DIRAI_AGENT_DIR=self.dir)
        run = lambda *args: subprocess.run(["python3", cmd] + list(args), env=env, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, universal_newlines=True)
        r = run("1", "done", "Renamed the decks in the table", "--at", "#results")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("note 1: done", r.stdout)
        got = notes.load(self.dir)[0]
        self.assertEqual((got["state"], got["answer"], got["at"]), ("done", "Renamed the decks in the table", "#results"))
        self.assertEqual(got["thread"][-1]["at"], "#results")
        self.assertEqual(run("1", "open", "on second thought: which table?").returncode, 0)   # again, same run
        self.assertEqual(notes.load(self.dir)[0]["state"], "open")
        r = run("2", "done", "x")                       # never sent
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("wasn't sent to you", r.stderr)
        self.assertNotEqual(run("9", "done", "x").returncode, 0)
        self.assertNotEqual(run("1", "maybe", "x").returncode, 0)

    def test_reply_reopens_and_finish_run(self):
        a, b, c = self.add("a"), self.add("b"), self.add("c")
        notes.take(self.dir, [a["id"], b["id"]])
        notes.answer(self.dir, 1, "done", "fixed")
        self.assertEqual(notes.unanswered(self.dir, [1, 2]), [2])
        out = notes.finish_run(self.dir, [1, 2], "reply", True)
        self.assertEqual(out, [{"id": a["id"], "n": 1, "state": "done"}, {"id": b["id"], "n": 2, "state": "open", "noanswer": True}])
        got = {x["n"]: x for x in notes.load(self.dir)}
        self.assertTrue(got[2]["noanswer"] and not got[1].get("answered"))
        _, why = notes.act(self.dir, {"op": "reply", "id": a["id"], "text": "  not quite: also the units  "})   # E4
        self.assertIsNone(why)
        got = {x["n"]: x for x in notes.load(self.dir)}
        self.assertEqual(got[1]["state"], "open")
        self.assertEqual([(e["who"], e["text"]) for e in got[1]["thread"]], [("agent", "fixed"), ("owner", "not quite: also the units")])
        self.assertTrue(notes.act(self.dir, {"op": "reply", "id": a["id"], "text": " "})[1])
        notes.act(self.dir, {"op": "state", "id": c["id"], "state": "done"})
        notes.take(self.dir, [b["id"]])
        notes.answer(self.dir, 2, "done", "kept")
        notes.finish_run(self.dir, [2], "", True)
        notes.finish_run(self.dir, [], "", True)        # a later run: done notes stay, with their answers
        self.assertEqual([(x["n"], x["state"]) for x in notes.load(self.dir)], [(1, "open"), (2, "done"), (3, "done")])
        self.assertEqual(notes.load(self.dir)[1]["answer"], "kept")
        notes.act(self.dir, {"op": "clear"})            # until the owner clears them
        self.assertEqual(sorted(x["n"] for x in notes.load(self.dir)), [1])
        b = self.add("b")
        notes.take(self.dir, [b["id"]])
        notes.finish_run(self.dir, [2], "", False)      # cancelled: given back, not "no answer"
        self.assertEqual((notes.load(self.dir)[1]["state"], notes.load(self.dir)[1].get("noanswer")), ("open", None))
        for _ in range(notes.THREAD_MAX + 3):
            notes.act(self.dir, {"op": "reply", "id": a["id"], "text": "more"})
        self.assertEqual(len(notes.load(self.dir)[0]["thread"]), notes.THREAD_MAX)

    def test_prompt_notes(self):
        self.assertEqual(notes.prompt_notes("1) The owner left 2 sticky notes on your page (notes 1, 5). x\n"
                                            "2) The owner left 1 sticky note on your page (note 3). y"), [1, 3, 5])
        self.assertEqual(notes.prompt_notes("no notes"), [])


class NotesSendTest(unittest.TestCase):
    def setUp(self):
        self.root = util.new_tree("notes-send-" + self.id().rsplit(".", 1)[1])
        self.dir = os.path.join(self.root, "p")
        util.write(os.path.join(self.dir, "index.html"),
                   "<html><body>\n<h2>Rates</h2>\n<p>rates agree</p>\n<p>except deck 4</p>\n</body></html>")
        self.rv = agents.Agents(self.root)
        self.rv.hold_until, self.rv.hold_reason = time.time() + 3600, "test hold"

    def tearDown(self):
        if self.rv.timer:
            self.rv.timer.cancel()

    def data(self):
        with open(os.path.join(self.root, "www", "agents.json")) as f:
            return json.load(f)["p"]

    def add(self, text, note=""):
        return notes.act(self.dir, {"op": "add", "note": {"text": text, "heading": "Rates", "note": note}})[0][-1]

    def test_send_notes_with_empty_text(self):
        a, b = self.add("rates agree", "name the decks"), self.add("except deck 4")
        self.assertTrue(self.rv.comment("p", "", notes=[a["id"], b["id"]]))
        st = self.data()
        p = st["pending"]
        self.assertTrue(p.startswith("The owner left 2 sticky notes on your page (notes 1, 2)."), p)
        self.assertIn("Note 1. The owner selected this text in index.html (near the heading \"Rates\", source line 3;", p)
        self.assertIn("Their message about it:\nname the decks", p)
        self.assertIn("Note 2.", p)
        self.assertIn("dirai_note.py <n> done \"<what you did, and where>\"", p)
        self.assertNotIn("The exchange on this note", p)
        self.assertNotIn("Their message with the notes", p)
        self.assertEqual(st["thread"][-2]["notes"], [{"n": 1, "text": "rates agree", "note": "name the decks"},
                                                     {"n": 2, "text": "except deck 4", "note": ""}])
        self.assertEqual(st["working_on"], "2 sticky notes")
        self.assertEqual({x["state"] for x in notes.load(self.dir)}, {"sent"})

    def test_left_out_note_stays_open_and_message_goes_too(self):
        a, b = self.add("rates agree"), self.add("except deck 4")
        self.assertTrue(self.rv.comment("p", "and check the units", notes=[b["id"]]))
        self.assertIn("Their message with the notes:\nand check the units", self.data()["pending"])
        self.assertEqual({x["n"]: x["state"] for x in notes.load(self.dir)}, {1: "open", 2: "sent"})

    def test_busy_queue_and_reply_closes(self):
        self.assertTrue(self.rv.comment("p", "first"))
        a = self.add("rates agree")
        self.assertFalse(self.rv.comment("p", "", notes=[a["id"]]))           # busy, not queued: back to open
        self.assertEqual(notes.load(self.dir)[0]["state"], "open")
        self.assertEqual(self.rv.comment("p", "", notes=[a["id"]], queue=True), "queued")
        self.assertEqual(notes.load(self.dir)[0]["state"], "sent")
        self.run_reply("Fixed.")
        st = self.data()                                                   # the queued notes went when it ended
        self.assertTrue(st["pending"].startswith("The owner left 1 sticky note on your page (note 1)."))
        self.assertEqual(notes.load(self.dir)[0]["state"], "sent")
        self.run_reply("Named them.\n1: done", st["pending"])
        self.assertEqual(notes.load(self.dir)[0]["state"], "done")        # an old-style line still closes it
        self.assertEqual(self.rv.state("p")["notes"][0]["state"], "done")
        last = self.data()["thread"][-1]
        self.assertEqual((last["text"], last["notes_result"]), ("Named them.", [{"id": a["id"], "n": 1, "state": "done"}]))

    def test_unanswered_note_reopened_and_follow_up(self):    # E2a
        a, b = self.add("rates agree"), self.add("except deck 4")
        self.assertTrue(self.rv.comment("p", "", notes=[a["id"], b["id"]]))
        prompt = self.data()["pending"]
        notes.answer(self.dir, 1, "done", "named the decks")
        asked = {}
        check = self.rv._followups(os.path.join(self.dir, "index.html"), "/nonexistent", self.dir, notes.prompt_notes(prompt), asked)
        with mock.patch.object(agents.dirai_card, "problems", return_value=[]):
            msg = check("Done.")
        self.assertIn("note 2 has no answer yet", msg)
        self.assertIn("dirai_note.py <n> done|open", msg)
        self.assertEqual(asked, {"notes": [2]})
        self.run_reply("Done.", prompt)
        got = {x["n"]: x for x in notes.load(self.dir)}
        self.assertEqual((got[1]["state"], got[2]["state"], got[2].get("noanswer")), ("done", "open", True))
        self.assertEqual(self.data()["thread"][-1]["notes_result"][1], {"id": b["id"], "n": 2, "state": "open", "noanswer": True})

    def test_exchange_goes_with_the_note(self):     # E4/E5a: a reply reopens the note; the next Send quotes it
        a = self.add("rates agree", "name the decks")
        notes.take(self.dir, [a["id"]])
        notes.answer(self.dir, 1, "done", "Named decks 1-3", "#rates")
        notes.act(self.dir, {"op": "reply", "id": a["id"], "text": "and deck 4?"})
        self.assertTrue(self.rv.comment("p", "", notes=[a["id"]]))
        p = self.data()["pending"]
        self.assertIn("The exchange on this note so far", p)
        self.assertIn("] Named decks 1-3", p)
        self.assertIn("[owner, ", p)
        self.assertIn("] and deck 4?", p)

    def run_reply(self, text, prompt="x"):
        self.rv.queue = [i for i in self.rv.queue if i[0] != "p"]
        self.rv.running += 1
        reply = {"role": "claude", "time": agents.now(), "text": text}
        with mock.patch.object(self.rv, "_attempt", return_value=(reply, None, [], "s1")), \
                mock.patch.object(self.rv, "_jobs_to_wait_for", return_value=[]):
            self.rv._run("p", prompt)

    def test_nothing_to_send(self):
        a = self.add("x")
        notes.act(self.dir, {"op": "state", "id": a["id"], "state": "done"})
        self.assertFalse(self.rv.comment("p", "", notes=[a["id"]]))       # done notes don't go


class RequestsTest(unittest.TestCase):
    """Requests between agents (proposal 77): a drafts with dirai_note.py ask, only the owner sends, b answers
    on its copy, the answer goes back to a by itself; Send all holds the answers until all are in."""
    def setUp(self):
        self.root = util.new_tree("requests-" + self.id().rsplit(".", 1)[1])
        util.write(os.path.join(self.root, "www", "dirai.json"), "{}")
        for a in "abcd":
            util.write(os.path.join(self.root, a, "index.html"), "<html><body><h2 id='yields'>Yields</h2></body></html>")
        self.rv = agents.Agents(self.root)
        self.rv.hold_until, self.rv.hold_reason = time.time() + 3600, "test hold"

    def tearDown(self):
        if self.rv.timer:
            self.rv.timer.cancel()

    def d(self, a):
        return os.path.join(self.root, a)

    def st(self, a):
        with open(os.path.join(self.root, "www", "agents.json")) as f:
            return json.load(f)[a]

    def ask(self, a, *args):
        script = os.path.join(util.TOOL, "scripts", "dirai_note.py")
        return subprocess.run([sys.executable, script, "ask"] + list(args), env=dict(os.environ, DIRAI_AGENT_DIR=self.d(a)),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)

    def run_reply(self, a, text, prompt="x"):
        self.rv.queue = [i for i in self.rv.queue if i[0] != a]
        self.rv.running += 1
        reply = {"role": "claude", "time": agents.now(), "text": text}
        with mock.patch.object(self.rv, "_attempt", return_value=(reply, None, [], "s1")), \
                mock.patch.object(self.rv, "_jobs_to_wait_for", return_value=[]):
            self.rv._run(a, prompt)

    def drafts(self, a):
        return [x for x in notes.load(self.d(a)) if x.get("to")]

    def last_msg(self, a):
        """The last message the agent was given (the test hold puts a line of its own after it)."""
        return [m for m in self.st(a)["thread"] if m["role"] == "user"][-1]

    def test_ask_send_answer_back(self):
        r = self.ask("a", "b", "rebin yields to 10 GeV", "--about", "#fit")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        x, = self.drafts("a")
        self.assertEqual((x["to"], x["state"], x["note"], x["about"], x["text"]), ("b", "draft", "rebin yields to 10 GeV", "#fit", ""))
        self.assertEqual(notes.load(self.d("b")), [])                         # nothing reaches b yet
        self.assertIn("still waiting", self.ask("a", "b", "and 5 GeV").stderr)    # one in flight per pair
        self.assertIn("isn't an agent", self.ask("a", "zz", "x").stderr)
        self.assertFalse(self.rv.comment("a", "", notes=[x["id"]]))           # R4: your Send notes skips it
        self.run_reply("a", "Drafted a request to b.")                        # the reply links to the draft
        self.assertEqual(self.st("a")["thread"][-1]["requests"], [{"id": x["id"], "n": 1, "to": "b"}])
        self.assertEqual(self.rv.all_status()["a"]["requests"], 1)
        self.assertEqual(self.rv.send_request("a", [x["id"]]), (1, []))      # your Send ▸ b
        self.assertEqual(self.rv.all_status()["a"]["requests"], 0)
        self.assertEqual(self.drafts("a")[0]["state"], "sent")
        self.assertIn(x["link"], self.st("a")["requests"])                    # R1: the record is the server's
        y, = notes.load(self.d("b"))
        self.assertEqual((y["from"], y["state"], y["link"]), ("a", "sent", x["link"]))
        p = self.st("b")["pending"]
        self.assertTrue(p.startswith("Agent a asked you, and the owner sent 1 sticky note on your page (note 1)."), p)
        self.assertIn("A request from agent a, sent by the owner:\nrebin yields to 10 GeV", p)
        self.assertIn("Never quote one agent's request", p)                   # R13
        self.assertEqual(notes.prompt_notes(p), [1])                          # R3
        self.assertEqual(self.last_msg("b")["from"], "a")
        notes.answer(self.d("b"), 1, "done", "rebinned", "#yields")           # b answers on its copy
        self.run_reply("b", "Done.", p)
        x = self.drafts("a")[0]                                               # R5: back on a's entry
        self.assertEqual((x["state"], x["answer"], x["at"], x["thread"][-1]["who"]), ("done", "rebinned", "#yields", "b"))
        self.assertTrue(x["delivered"])
        last = self.last_msg("a")                                             # and given to a
        self.assertEqual(last["from"], "b")
        self.assertIn("b answered", last["text"])
        self.assertIn("b's answer (done): rebinned (see #yields on its page, b/index.html)", last["text"])
        self.assertEqual(self.ask("a", "b", "now 5 GeV too").returncode, 0)  # a follow-up: next entry of the pair
        nxt = self.drafts("a")[-1]
        self.rv.send_request("a", [nxt["id"]])
        self.assertEqual(notes.load(self.d("b"))[-1]["prev"], {"note": "rebin yields to 10 GeV", "answer": "rebinned"})

    def test_only_the_owners_send_goes_back(self):     # R1: a copy nobody sent never reaches a
        self.assertEqual(self.ask("a", "b", "x").returncode, 0)
        x, = self.drafts("a")
        fake = notes.receive(self.d("b"), "a", x)
        self.rv.comment("b", "", notes=[fake["id"]])
        notes.answer(self.d("b"), fake["n"], "done", "forged")
        self.run_reply("b", "Done.", self.st("b")["pending"])
        self.assertEqual(self.drafts("a")[0]["state"], "draft")
        self.assertNotIn("answer", self.drafts("a")[0])

    def test_send_all_answers_together(self):
        self.assertEqual(self.ask("a", "b,c", "yields?").returncode, 0)
        ids = [x["id"] for x in self.drafts("a")]
        self.assertEqual(self.rv.send_request("a", ids, together=True), (2, []))
        self.assertEqual(len({x["group"] for x in self.drafts("a")}), 1)
        notes.answer(self.d("b"), 1, "done", "b's yields")
        self.run_reply("b", "Done.", self.st("b")["pending"])
        self.assertFalse([m for m in self.st("a")["thread"] if m.get("from")])  # 1 of 2 in: held
        notes.answer(self.d("c"), 1, "open", "which channel?")
        self.run_reply("c", "Asked.", self.st("c")["pending"])
        last = self.last_msg("a")                                              # both in: one message
        self.assertEqual(last["from"], "b, c")
        self.assertIn("b's answer (done): b's yields", last["text"])
        self.assertIn("c's answer (open): which channel?", last["text"])

    def test_deliver_now_and_reject(self):
        self.assertEqual(self.ask("a", "b,c", "yields?").returncode, 0)
        self.assertEqual(self.ask("a", "d", "plots?").returncode, 0)
        b, c, dd = self.drafts("a")
        self.assertTrue(self.rv.reject_request("a", dd["id"], "not needed"))
        self.assertEqual(self.drafts("a")[2]["state"], "rejected")
        self.assertIn("rejected your request 3 to d: not needed", self.st("a")["page_note"])     # R9
        self.rv.send_request("a", [b["id"], c["id"]], together=True)
        notes.answer(self.d("b"), 1, "done", "b's yields")
        self.run_reply("b", "Done.", self.st("b")["pending"])
        group = self.drafts("a")[0]["group"]
        self.assertTrue(self.rv.deliver_now("a", group))                    # what is in so far
        self.assertIn("b's yields", self.last_msg("a")["text"])
        self.assertNotIn("group", self.drafts("a")[1])                        # c's answer will come by itself

    def test_inbox_full_stays_draft(self):     # R8
        self.assertEqual(self.ask("a", "b", "x").returncode, 0)
        x, = self.drafts("a")
        with mock.patch.object(self.rv, "comment", return_value=False):
            sent, errors = self.rv.send_request("a", [x["id"]])
        self.assertEqual(sent, 0)
        self.assertIn("stays a draft", errors[0])
        self.assertEqual(self.drafts("a")[0]["state"], "draft")
        self.assertEqual(notes.load(self.d("b")), [])


class NotesBrowserTest(unittest.TestCase):
    def test_marks_pop_up_and_send(self):
        np = test_highlights.node_path()
        if np is None:
            self.skipTest("needs node and playwright")
        run = subprocess.run(["node", os.path.join(os.path.dirname(os.path.abspath(__file__)), "notes.js")],
                             env=dict(os.environ, NODE_PATH=np), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             universal_newlines=True, timeout=120)
        if "Executable doesn't exist" in run.stdout + run.stderr:
            self.skipTest("needs Playwright's chromium")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
