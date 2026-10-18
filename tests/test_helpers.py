"""The pure helpers: permission rules, selections, summary cards, config, usage-limit replies."""
import os
import time
import unittest

from tests import util

import dirai_card
import dirai_config
import claude_run
import slurm
import agent_files
import agents
import agent_permissions as perms
import agent_prompts as prompts


class PermissionRules(unittest.TestCase):
    def test_split_command(self):
        self.assertEqual(perms.split_command('ls -l && cd /x; echo "a && b" | grep x'),
                         ["ls -l", "cd /x", 'echo "a && b"', "grep x"])
        self.assertEqual(perms.split_command("a || b\nc"), ["a", "b", "c"])
        self.assertEqual(perms.split_command("echo 'x;y'"), ["echo 'x;y'"])

    def test_denial_rules(self):
        cases = [
            ("Bash", {"command": "ls && rm -rf /"}, ["Bash(ls)", "Bash(rm -rf /)"]),
            ("Edit", {"file_path": "/a/b.py"}, ["Edit(//a/b.py)"]),
            ("Write", {"file_path": "rel.py"}, ["Edit(rel.py)"]),
            ("Read", {"file_path": "/etc/passwd"}, ["Read(//etc/**)"]),
            ("Grep", {"path": "/tmp"}, ["Read(//tmp/**)"]),
            ("WebFetch", {"url": "https://ex.com/a"}, ["WebFetch(domain:ex.com)"]),
            ("Foo", {"q": 1}, ["Foo"]),
        ]
        for tool, inp, rules in cases:
            self.assertEqual(perms.denial_rules({"tool_name": tool, "tool_input": inp}), rules, tool)

    def test_describe_denial(self):
        self.assertEqual(perms.describe_denial({"tool_name": "Bash", "tool_input": {"command": "ls"}}), "Bash: ls")
        self.assertEqual(perms.describe_denial({"tool_name": "Grep", "tool_input": {"path": "/t"}}),
                         'Grep: {"path": "/t"}')

    def test_request_denial(self):
        self.assertEqual(perms.request_denial({"tool_name": "Bash", "input": None}),
                         {"tool_name": "Bash", "tool_input": {}})

    def test_always_denied(self):
        for rule, denied in [("Bash(git push --force origin)", True), ("Bash(git push)", False),
                             ("Bash(sudo)", True), ("Bash(rm -rf x)", True), ("Bash(rm -rfx)", False),
                             ("Read", False), ("Bash(git -C x push)", True)]:
            self.assertEqual(perms.always_denied(rule), denied, rule)


class Scope(unittest.TestCase):
    def setUp(self):
        self.root = util.new_tree("scope")
        os.makedirs(os.path.join(self.root, "a", "b"))
        os.makedirs(os.path.join(self.root, "a", ".git"))
        util.write(os.path.join(self.root, "c", "f.txt"), "")

    def test_read_scope(self):
        self.assertEqual(perms.read_scope(self.root + "/a/b", self.root), self.root + "/a")
        self.assertEqual(perms.read_scope(self.root + "/c", self.root), self.root + "/c")
        self.assertEqual(perms.read_scope(self.root, self.root), self.root)

    def test_path_grants(self):
        text = "see c/f.txt and %s/a/b and /etc and nope/x." % self.root
        self.assertEqual(perms.path_grants(text, self.root, self.root + "/a"),
                         ["Read(/%s/c/**)" % self.root])

    def test_extra_dirs(self):
        allow = ["Edit(//tmp/x.py)", "Read(//usr/**)", "Bash(cat /etc/hosts)", "Bash(ls:*)"]
        self.assertEqual(perms.extra_dirs(allow, self.root, [self.root]), ["/etc", "/tmp", "/usr"])


class Selection(unittest.TestCase):
    def test_visible_chars(self):
        text, lines = prompts.visible_chars("<p>Hi &amp; <b>there</b></p>\n<script>x</script>\n<i>yo</i>")
        self.assertEqual(text, "Hi&thereyo")
        self.assertEqual(lines, [1] * 8 + [3, 3])

    def test_selection_lines(self):
        root = util.new_tree("sel")
        agent = os.path.join(root, "index.html")
        util.write(agent, "<html><body>\n<h1>T</h1>\n<p>Some long selected\ntext here</p>\n<p>more</p></body></html>")
        self.assertEqual(prompts.selection_lines(agent, "Some long selected text here"), (3, 4))
        self.assertIsNone(prompts.selection_lines(agent, "not in index.html"))

    def test_selection_prompt(self):
        self.assertEqual(prompts.selection_prompt({"text": "a\nb", "heading": "H", "lines": (3, 4)}, "msg"),
                         'The owner selected this text in index.html (near the heading "H", '
                         "source lines 3-4; read just the lines around them unless you need more):\n"
                         "> a\n> b\n\nTheir message about it:\nmsg")

    def test_fresh_prompt(self):
        thread = [{"role": "user", "time": "t", "text": "x" * 2000},
                  {"role": "system", "time": "t", "text": prompts.NEW_CHAT_MARK}]
        p = prompts.fresh_prompt(thread, "new")
        self.assertIn("[user, t]\n" + "x" * 1500 + "...", p)
        self.assertNotIn(prompts.NEW_CHAT_MARK, p)
        self.assertTrue(p.endswith("New message:\nnew"))


class FolderFiles(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.join(util.new_tree("files"), "a")
        util.write(os.path.join(self.dir, "index.html"), "<html></html>")
        util.write(os.path.join(self.dir, "run.sh"), "#!/bin/bash\necho one\necho two\n")
        util.write(os.path.join(self.dir, "notes.md"), "# Notes\n")
        util.write(os.path.join(self.dir, ".env"), "TOKEN=secret")
        util.write(os.path.join(self.dir, "plot.png"), "png")
        with open(os.path.join(self.dir, "data.bin"), "wb") as f:
            f.write(b"\x00\x01binary")
        util.write(os.path.join(self.dir, "big.csv"), "x" * (agent_files.FILE_MAX + 1))
        util.write(os.path.join(self.dir, "sub", "deep.txt"), "x")
        util.write(os.path.join(self.dir, "child", "index.html"), "<html></html>")
        util.write(os.path.join(util.TMP, "outside.txt"), "secret")
        os.symlink(os.path.join(util.TMP, "outside.txt"), os.path.join(self.dir, "link.txt"))

    def test_folder_files(self):
        d = agent_files.folder_files(self.dir)
        self.assertEqual([f["name"] for f in d["files"]], ["notes.md", "run.sh"])
        self.assertEqual(d["files"][1]["text"], "#!/bin/bash\necho one\necho two\n")
        self.assertEqual({f["name"]: f["why"] for f in d["other"]},
                         {"big.csv": "over 1 MB", "data.bin": "binary", "link.txt": "not in this folder",
                          "plot.png": "image"})                       # no .env, no index.html
        self.assertEqual(d["dirs"], [{"name": "child", "agent": True}, {"name": "sub", "agent": False}])
        self.assertEqual(d["more"], 0)

    def test_file_path(self):
        self.assertTrue(agent_files.file_path(self.dir, "run.sh"))
        for bad in ("../x.txt", "sub/deep.txt", ".env", "index.html", "plot.png", "link.txt", "nope", "", None, 3):
            self.assertIsNone(agent_files.file_path(self.dir, bad), bad)

    def test_selected_lines(self):
        path = os.path.join(self.dir, "run.sh")
        self.assertEqual(agent_files.selected_lines(path, [2, 3]), (2, 3))
        self.assertEqual(agent_files.selected_lines(path, [3, 2]), (2, 3))
        self.assertEqual(agent_files.selected_lines(path, [0, 99]), (1, 4))   # kept within the file
        for bad in (None, "x", [1], ["a", "b"]):
            self.assertIsNone(agent_files.selected_lines(path, bad), bad)

    def test_rendered_lines(self):
        path = os.path.join(self.dir, "doc.md")
        util.write(path, "# Notes\n\nSome **bold** text here, and more of it.\n\n- one\n- two item\n")
        self.assertEqual(agent_files.rendered_lines(path, [3, 3], "Some bold text here"), (3, 3))
        self.assertEqual(agent_files.rendered_lines(path, [5, 6], "two item"), (6, 6))
        self.assertEqual(agent_files.rendered_lines(path, [5, 6], "not there"), (5, 6))   # the blocks
        self.assertEqual(agent_files.rendered_lines(path, [1, 99], "Notes"), (1, 1))      # within the file
        self.assertIsNone(agent_files.rendered_lines(path, None, "x"))

    def test_selection_prompt(self):
        self.assertTrue(prompts.selection_prompt({"text": "a", "file": "run.sh", "lines": (3, 3)}, "m").startswith(
            "The owner selected this text in run.sh (source line 3;"))


class Misc(unittest.TestCase):
    def test_limit_reset(self):
        self.assertIsNone(claude_run.limit_reset("hello"))
        t = claude_run.limit_reset("You've hit your session limit · resets 10:20pm (UTC)")
        self.assertTrue(time.time() < t < time.time() + 86400 + 300)
        self.assertAlmostEqual(claude_run.limit_reset("usage limit reached"),
                               time.time() + claude_run.LIMIT_FALLBACK_S, delta=5)

    def test_small_formatters(self):
        self.assertEqual((agents.kilo(None), agents.kilo(152345)), ("?", "152K"))
        self.assertEqual(slurm.seconds("1-02:03:04"), 93784)
        self.assertIsNone(slurm.seconds("UNLIMITED"))
        self.assertEqual(slurm.duration(93784), "1-02:03:04")
        self.assertEqual(slurm.base_id("12_[3-4]"), "12")

    def test_busy(self):
        self.assertTrue(agents.busy({"status": "working"}))
        self.assertTrue(agents.busy({"status": "queued", "job_wait": {}}))
        self.assertFalse(agents.busy({"status": "working", "job_wait": {"jobs": ["1"]}}))
        self.assertFalse(agents.busy({"status": "unread"}))


class Card(unittest.TestCase):
    def test_starter_index(self):
        agent = os.path.join(util.new_tree("card"), "index.html")
        util.write(agent, prompts.STARTER_INDEX.format(title="T", task="do it", date="2026-01-01"))
        self.assertEqual(dirai_card.problems(agent), [])
        self.assertEqual(dirai_card.problems(agent, "2026-02-02"),
                         ["Updated is 2026-01-01, but index.html changed today (2026-02-02)"])
        self.assertEqual(dirai_card.extract(agent)["objective"], "do it")

    def test_problems(self):
        agent = os.path.join(util.new_tree("card2"), "index.html")
        util.write(agent, "<html></html>")
        self.assertEqual(dirai_card.problems(agent), ["index.html has no summary card"])
        util.write(agent, '<!-- dirai:card --><dl><dt>Objective</dt><dd>x</dd><dt>Updated</dt><dd>soon</dd></dl>'
                         '<script type="application/json" id="dirai-results">{bad</script><!-- /dirai:card -->')
        got = dirai_card.problems(agent)
        self.assertIn("Inputs is missing", got)
        self.assertIn('Updated is "soon", not a YYYY-MM-DD date', got)
        self.assertTrue(any(p.startswith("the dirai-results JSON doesn't parse") for p in got))


class Config(unittest.TestCase):
    def test_tree_config_and_option(self):
        root = util.new_tree("cfg")
        self.assertEqual(dirai_config.tree_config(root),
                         {"port": None, "read_dirs": [], "allow": [], "slurm": [], "exclude": [],
                          "permissions": "allowlist"})
        dirai_config.set_tree_option(root, "port", 9999)
        dirai_config.set_tree_option(root, "read_dirs", ["~/x"])
        cfg = dirai_config.tree_config(root)
        self.assertEqual(cfg["port"], 9999)
        self.assertEqual(cfg["read_dirs"], [os.path.expanduser("~/x")])
        self.assertEqual(os.listdir(os.path.join(root, "www")), ["dirai.json"])   # no temp left

    def test_within(self):
        self.assertTrue(dirai_config.within("/a/b", "/a"))
        self.assertTrue(dirai_config.within("/a", "/a"))
        self.assertFalse(dirai_config.within("/ab", "/a"))

    def test_load_json_default(self):
        self.assertEqual(dirai_config.load_json("/nonexistent/x.json", {"d": 1}), {"d": 1})


if __name__ == "__main__":
    unittest.main()
