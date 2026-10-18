"""The pure helpers: permission rules, selections, summary cards, config, usage-limit replies."""
import os
import time
import unittest

from tests import util

import dirai_card
import dirai_config
import page_status
import review


class PermissionRules(unittest.TestCase):
    def test_split_command(self):
        self.assertEqual(review.split_command('ls -l && cd /x; echo "a && b" | grep x'),
                         ["ls -l", "cd /x", 'echo "a && b"', "grep x"])
        self.assertEqual(review.split_command("a || b\nc"), ["a", "b", "c"])
        self.assertEqual(review.split_command("echo 'x;y'"), ["echo 'x;y'"])

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
            self.assertEqual(review.denial_rules({"tool_name": tool, "tool_input": inp}), rules, tool)

    def test_describe_denial(self):
        self.assertEqual(review.describe_denial({"tool_name": "Bash", "tool_input": {"command": "ls"}}), "Bash: ls")
        self.assertEqual(review.describe_denial({"tool_name": "Grep", "tool_input": {"path": "/t"}}),
                         'Grep: {"path": "/t"}')

    def test_request_denial(self):
        self.assertEqual(review.request_denial({"tool_name": "Bash", "input": None}),
                         {"tool_name": "Bash", "tool_input": {}})

    def test_always_denied(self):
        for rule, denied in [("Bash(git push --force origin)", True), ("Bash(git push)", False),
                             ("Bash(sudo)", True), ("Bash(rm -rf x)", True), ("Bash(rm -rfx)", False),
                             ("Read", False), ("Bash(git -C x push)", True)]:
            self.assertEqual(review.always_denied(rule), denied, rule)


class Scope(unittest.TestCase):
    def setUp(self):
        self.root = util.new_tree("scope")
        os.makedirs(os.path.join(self.root, "a", "b"))
        os.makedirs(os.path.join(self.root, "a", ".git"))
        util.write(os.path.join(self.root, "c", "f.txt"), "")

    def test_read_scope(self):
        self.assertEqual(review.read_scope(self.root + "/a/b", self.root), self.root + "/a")
        self.assertEqual(review.read_scope(self.root + "/c", self.root), self.root + "/c")
        self.assertEqual(review.read_scope(self.root, self.root), self.root)

    def test_path_grants(self):
        text = "see c/f.txt and %s/a/b and /etc and nope/x." % self.root
        self.assertEqual(review.path_grants(text, self.root, self.root + "/a"),
                         ["Read(/%s/c/**)" % self.root])

    def test_extra_dirs(self):
        allow = ["Edit(//tmp/x.py)", "Read(//usr/**)", "Bash(cat /etc/hosts)", "Bash(ls:*)"]
        self.assertEqual(review.extra_dirs(allow, self.root, [self.root]), ["/etc", "/tmp", "/usr"])


class Selection(unittest.TestCase):
    def test_visible_chars(self):
        text, lines = review.visible_chars("<p>Hi &amp; <b>there</b></p>\n<script>x</script>\n<i>yo</i>")
        self.assertEqual(text, "Hi&thereyo")
        self.assertEqual(lines, [1] * 8 + [3, 3])

    def test_selection_lines(self):
        root = util.new_tree("sel")
        page = os.path.join(root, "index.html")
        util.write(page, "<html><body>\n<h1>T</h1>\n<p>Some long selected\ntext here</p>\n<p>more</p></body></html>")
        self.assertEqual(review.selection_lines(page, "Some long selected text here"), (3, 4))
        self.assertIsNone(review.selection_lines(page, "not on the page"))

    def test_selection_prompt(self):
        self.assertEqual(review.selection_prompt({"text": "a\nb", "heading": "H", "lines": (3, 4)}, "msg"),
                         'The owner selected this text on the page (index.html, near the heading "H", '
                         "source lines 3-4; read just the lines around them unless you need more):\n"
                         "> a\n> b\n\nTheir message about it:\nmsg")

    def test_fresh_prompt(self):
        thread = [{"role": "user", "time": "t", "text": "x" * 2000},
                  {"role": "system", "time": "t", "text": review.NEW_CHAT_MARK}]
        p = review.fresh_prompt(thread, "new")
        self.assertIn("[user, t]\n" + "x" * 1500 + "...", p)
        self.assertNotIn(review.NEW_CHAT_MARK, p)
        self.assertTrue(p.endswith("New message:\nnew"))


class Misc(unittest.TestCase):
    def test_limit_reset(self):
        self.assertIsNone(review.limit_reset("hello"))
        t = review.limit_reset("You've hit your session limit · resets 10:20pm (UTC)")
        self.assertTrue(time.time() < t < time.time() + 86400 + 300)
        self.assertAlmostEqual(review.limit_reset("usage limit reached"),
                               time.time() + review.LIMIT_FALLBACK_S, delta=5)

    def test_small_formatters(self):
        self.assertEqual((review.kilo(None), review.kilo(152345)), ("?", "152K"))
        self.assertEqual(page_status.seconds("1-02:03:04"), 93784)
        self.assertIsNone(page_status.seconds("UNLIMITED"))
        self.assertEqual(page_status.duration(93784), "1-02:03:04")
        self.assertEqual(page_status.base_id("12_[3-4]"), "12")

    def test_busy(self):
        self.assertTrue(review.busy({"status": "working"}))
        self.assertTrue(review.busy({"status": "queued", "watch": {}}))
        self.assertFalse(review.busy({"status": "working", "watch": {"jobs": ["1"]}}))
        self.assertFalse(review.busy({"status": "unread"}))


class Card(unittest.TestCase):
    def test_starter_page(self):
        page = os.path.join(util.new_tree("card"), "index.html")
        util.write(page, review.STARTER_PAGE.format(title="T", task="do it", date="2026-01-01"))
        self.assertEqual(dirai_card.problems(page), [])
        self.assertEqual(dirai_card.problems(page, "2026-02-02"),
                         ["Updated is 2026-01-01, but the page changed today (2026-02-02)"])
        self.assertEqual(dirai_card.extract(page)["objective"], "do it")

    def test_problems(self):
        page = os.path.join(util.new_tree("card2"), "index.html")
        util.write(page, "<html></html>")
        self.assertEqual(dirai_card.problems(page), ["the page has no summary card"])
        util.write(page, '<!-- dirai:card --><dl><dt>Objective</dt><dd>x</dd><dt>Updated</dt><dd>soon</dd></dl>'
                         '<script type="application/json" id="dirai-results">{bad</script><!-- /dirai:card -->')
        got = dirai_card.problems(page)
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
