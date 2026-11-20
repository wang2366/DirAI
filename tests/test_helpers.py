"""The pure helpers: permission rules, selections, summary cards, config, usage-limit replies."""
import os
import time
import unittest
from unittest import mock

from tests import util

import dirai_card
import dirai_config
import claude_run
import slurm
import agent_files
import colleagues
import agents
import page_undo
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
            ("Bash", {"command": "ls && rm -rf /"}, ["Bash(rm -rf /)"]),     # ls: allowed already
            ("Edit", {"file_path": "/a/b.py"}, ["Edit(//a/b.py)"]),
            ("Write", {"file_path": "rel.py"}, ["Edit(rel.py)"]),
            ("Read", {"file_path": "/etc/passwd"}, ["Read(//etc/**)"]),
            ("Grep", {"path": "/tmp"}, ["Read(//tmp/**)"]),
            ("WebFetch", {"url": "https://ex.com/a"}, ["WebFetch(domain:ex.com)"]),
            ("Foo", {"q": 1}, ["Foo"]),
        ]
        for tool, inp, rules in cases:
            self.assertEqual(perms.denial_rules({"tool_name": tool, "tool_input": inp}), rules, tool)

    def test_piece_rules(self):
        cases = [
            ("basecamp attachments download 123 --file a.m", ["Bash(basecamp attachments:*)"]),
            ("make all -j4", ["Bash(make all:*)"]),
            ("ls -l /x", ["Bash(ls -l /x)"]),                     # a flag second: exact
            ("./run.sh /data/in", ["Bash(./run.sh /data/in)"]),   # a path second: exact
            ("git push origin main", ["Bash(git push origin main)"]),   # never a prefix
            ("rm old.dat", ["Bash(rm old.dat)"]),
            ("tool 'unbalanced", ["Bash(tool 'unbalanced)"]),
            ("make", ["Bash(make)"]),
        ]
        tmp = os.path.join(util.TMP, "bin") + "/"     # stands in for ~/.local/bin
        with mock.patch.object(perms, "USER_BIN", tmp):
            for piece, rules in cases:
                self.assertEqual(perms.piece_rules(piece), rules, piece)
        # a program in ~/.local/bin: the bare name and the full path, whichever way it was called
        util.write(tmp + "tool", "")
        with mock.patch.object(perms, "USER_BIN", tmp):
            both = ["Bash(tool comments:*)", "Bash(%stool comments:*)" % tmp]
            self.assertEqual(perms.piece_rules(tmp + "tool comments list 9 --json"), both)
            self.assertEqual(perms.piece_rules("tool comments show 9"), both)

    def test_covered(self):
        bash = lambda c: {"tool_name": "Bash", "tool_input": {"command": c}}
        rules = ["Bash(basecamp attachments:*)", "Bash(cd:*)", "Bash(make)", "Read(//data/**)"]
        self.assertTrue(perms.covered(rules, bash("basecamp attachments download 1 --out x")))
        self.assertTrue(perms.covered(rules, bash("cd /x && basecamp attachments")))
        self.assertFalse(perms.covered(rules, bash("basecamp attachmentsX")))
        self.assertFalse(perms.covered(rules, bash("cd /x && basecamp comments list")))   # one piece not covered
        self.assertTrue(perms.covered(rules, bash("make")))
        self.assertFalse(perms.covered(rules, bash("make clean")))
        self.assertTrue(perms.covered(rules, {"tool_name": "Read", "tool_input": {"file_path": "/data/a.txt"}}))
        self.assertFalse(perms.covered(rules, {"tool_name": "Edit", "tool_input": {"file_path": "/data/a.txt"}}))

    def test_describe_denial(self):
        self.assertEqual(perms.describe_denial({"tool_name": "Bash", "tool_input": {"command": "ls"}}), "Bash: ls")
        self.assertEqual(perms.describe_denial({"tool_name": "Grep", "tool_input": {"path": "/t"}}),
                         'Grep: {"path": "/t"}')

    def test_request_denial(self):
        self.assertEqual(perms.request_denial({"tool_name": "Bash", "input": None}),
                         {"tool_name": "Bash", "tool_input": {}})

    def test_unusable(self):
        # F2/F4: rules no later command can match (pieces of inline scripts), from tree-view's grants
        junk = ['Bash(        self.cards = {}   # index.html path -> …)', "Bash(<b>The decision:</b> whether)",
                'Bash("""Mock-up of the agent list\'s Tree tab""")', "Bash(assert a:*)", "Bash(import os)",
                "Bash(def f(x):)", "Bash(# a comment)", "Bash(python3 - <<'EOF')", "Bash(a\nb)", "Bash(%s)" % ("x " * 120)]
        for rule in junk:
            self.assertTrue(perms.unusable(rule), rule)
        for rule in ["Bash(git status)", "Bash(ls -l /x)", "Bash(make all:*)", "Bash(cd /x)", "Bash(./run.sh /data)",
                     "Bash(FOO=1 ls)", "Bash(%s/agent_rm.sh x)" % util.TMP, "Edit(//x/y.py)", "Read(//data/**)", "WebFetch"]:
            self.assertEqual(perms.unusable(rule), "", rule)
        self.assertEqual(perms.keepable(["Bash(import os)", "Bash(ls -l /x)"]), ["Bash(ls -l /x)"])
        heredoc = perms.denial_rules({"tool_name": "Bash", "tool_input": {
            "command": "python3 - <<'EOF'\na = 1; b = 2 | 3\nEOF\n"}})
        self.assertEqual(perms.keepable(heredoc), [])                 # Always keeps none of it
        self.assertEqual(perms.keepable(perms.denial_rules({"tool_name": "Bash", "tool_input": {"command": "assert a == 1"}})), [])

    def test_always_denied(self):
        for rule, denied in [("Bash(git push --force origin)", True), ("Bash(git push)", False),
                             ("Bash(sudo)", True), ("Bash(rm -rf x)", True), ("Bash(rm -rfx)", False),
                             ("Read", False), ("Bash(git -C x push)", True), ("Bash(git reset --hard)", True),
                             ("Bash(git checkout -- x/index.html)", False), ("Bash(git restore x)", False)]:
            self.assertEqual(perms.always_denied(rule), denied, rule)


class Scope(unittest.TestCase):
    def setUp(self):
        self.root = util.new_tree("scope")
        os.makedirs(os.path.join(self.root, "a", "b"))
        os.makedirs(os.path.join(self.root, "a", ".git"))
        util.write(os.path.join(self.root, "c", "f.txt"), "")

    def test_shared_grants(self):
        self.assertEqual(perms.shared_grants(["Bash(make)", "Edit(//x/y.py)", "Read(//data/**)"]),
                         ["Bash(make)", "Read(//data/**)"])
        for mode in ("own", "all"):     # F5: a writable colleague passes its edits on too
            self.assertEqual(perms.shared_grants(["Bash(make)", "Edit(//x/y.py)"], mode), ["Bash(make)", "Edit(//x/y.py)"])

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
        self.assertEqual(d["dirs"], [{"name": "child", "agent": True, "out": False},
                                     {"name": "sub", "agent": False, "out": False,
                                      "count": {"files": 1, "dirs": 0, "capped": False}}])
        self.assertEqual(d["more"], 0)

    def test_scratch_not_shown(self):
        # F6: the agent's tmp/ is its scratch place, not part of its page; a tmp/ deeper down is shown
        util.write(os.path.join(self.dir, "tmp", "patch.py"), "x")
        util.write(os.path.join(self.dir, "sub", "tmp", "keep.txt"), "x")
        self.assertNotIn("tmp", [x["name"] for x in agent_files.folder_files(self.dir)["dirs"]])
        self.assertIsNone(agent_files.folder_files(self.dir, "tmp"))
        self.assertIsNone(agent_files.file_path(self.dir, "tmp/patch.py"))
        self.assertIn("tmp", [x["name"] for x in agent_files.folder_files(self.dir, "sub")["dirs"]])

    def test_dir_listing(self):
        d = agent_files.dir_listing(self.dir, "")
        self.assertEqual([x["name"] for x in d["files"]], ["big.csv", "data.bin", "index.html", "link.txt", "notes.md", "plot.png", "run.sh"])
        self.assertEqual(d["files"][0]["size"], agent_files.FILE_MAX + 1)              # nothing is read
        self.assertEqual(d["dirs"], [{"name": "child", "agent": True, "out": False}, {"name": "sub", "agent": False, "out": False}])
        self.assertEqual([x["name"] for x in agent_files.dir_listing(self.dir, "child")["files"]], ["index.html"])
        self.assertEqual([x["name"] for x in agent_files.dir_listing(self.dir, "sub")["files"]], ["deep.txt"])
        for bad in ("..", "sub/..", "nope", ".hidden", "run.sh", "/etc", "a//b", None, 3):
            self.assertIsNone(agent_files.dir_listing(self.dir, bad), bad)

    def test_dir_listing_link_out(self):
        os.symlink(util.TMP, os.path.join(self.dir, "out"))
        self.assertIn({"name": "out", "agent": False, "out": True}, agent_files.dir_listing(self.dir, "")["dirs"])
        self.assertIsNone(agent_files.dir_listing(self.dir, "out"))

    def test_file_path(self):
        self.assertTrue(agent_files.file_path(self.dir, "run.sh"))
        for bad in ("../x.txt", ".env", "index.html", "plot.png", "link.txt", "nope", "", None, 3):
            self.assertIsNone(agent_files.file_path(self.dir, bad), bad)

    def test_sub(self):
        self.assertTrue(agent_files.file_path(self.dir, "sub/deep.txt"))
        for bad in ("sub/../run.sh", "sub/nope.txt", "child/x.txt", "./run.sh", "sub//deep.txt", ".git/x", "sub\\deep.txt"):
            self.assertIsNone(agent_files.file_path(self.dir, bad), bad)
        d = agent_files.folder_files(self.dir, "sub")
        self.assertEqual([f["name"] for f in d["files"]], ["deep.txt"])
        for bad in ("..", "sub/..", "child", "nope", ".hidden", "sub/deep.txt", "/etc", None):
            self.assertIsNone(agent_files.folder_files(self.dir, bad), bad)

    def test_sub_link_out(self):
        os.symlink(util.TMP, os.path.join(self.dir, "out"))
        d = agent_files.folder_files(self.dir)
        self.assertEqual([x for x in d["dirs"] if x["name"] == "out"], [{"name": "out", "agent": False, "out": True}])
        self.assertIsNone(agent_files.folder_files(self.dir, "out"))

    def test_count_capped(self):
        for i in range(agent_files.COUNT_MAX + 5):
            util.write(os.path.join(self.dir, "many", "f%d" % i), "x")
        c = [x for x in agent_files.folder_files(self.dir)["dirs"] if x["name"] == "many"][0]["count"]
        self.assertEqual((c["files"], c["capped"]), (agent_files.COUNT_MAX, True))

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


class Colleagues(unittest.TestCase):
    def setUp(self):
        self.root = util.new_tree("colleagues")
        util.write(os.path.join(self.root, "a", "index.html"), "<html></html>")
        util.write(os.path.join(self.root, "x y", "b", "index.html"),
                   prompts.STARTER_INDEX.format(title="B", task="find the peak", date="2026-10-16"))
        util.write(os.path.join(self.root, "nocard", "index.html"), "<html></html>")
        os.makedirs(os.path.join(self.root, "empty"))

    def test_parse_link(self):
        b = os.path.join(self.root, "x y", "b")
        for link in ("http://127.0.0.1:18767/x%20y/b/index.html", "https://host:1/x%20y/b/", "/x y/b/index.html",
                     "x y/b", b, b + "/index.html", "  x y/b/  "):
            self.assertEqual(colleagues.parse_link(link, self.root, "a"), ("x y/b", None), link)
        util.write(os.path.join(self.root, "index.html"), "<html></html>")
        self.assertEqual(colleagues.parse_link("http://h/index.html", self.root, "a"), ("", None))   # the top agent
        for link, why in (("", "Paste"), ("a", "itself"), ("empty", "no index.html"), ("http://h/www/", "no index.html"),
                          ("/etc", "isn't inside"), ("http://h/../../etc/", "isn't inside")):
            got = colleagues.parse_link(link, self.root, "a")
            self.assertIsNone(got[0], link)
            self.assertIn(why, got[1], link)

    def test_prompt_block(self):
        self.assertEqual(colleagues.prompt_block(self.root, [], "/c.py"), "")
        self.assertEqual(colleagues.prompt_block(self.root, ["gone"], "/c.py"), "")
        block = colleagues.prompt_block(self.root, ["x y/b", "nocard", "gone"], "/c.py")
        self.assertIn('run "python3 /c.py <folder>"', block)
        self.assertIn("- %s/x y/b: Objective: find the peak | Result: none yet" % self.root, block)
        self.assertIn("Updated: 2026-10-16", block)
        self.assertIn("- %s/nocard: no summary card; read its index.html" % self.root, block)
        self.assertNotIn("gone", block)
        many = colleagues.prompt_block(self.root, ["nocard"] * 10, "/c.py")
        self.assertEqual(many.count("no summary card"), colleagues.PROMPT_MAX)
        self.assertIn("(2 more colleagues not shown)", many)
        self.assertEqual(colleagues.cut("x" * 400)[-3:], "...")

    def test_card_row(self):
        self.assertEqual(colleagues.card_row(self.root, []), "")
        row = colleagues.card_row(self.root, ["x y/b", "nocard", "gone"])
        self.assertIn('<a href="/x%20y/b/index.html" title="x y/b">b</a> (2026-10-16 ✓)', row)
        self.assertIn('<a href="/nocard/index.html" title="Summary card: index.html has no summary card">nocard</a> (no card ✗)', row)
        self.assertIn("<s title=", row)
        self.assertTrue(row.startswith('<dt class="dirai-colls">Colleagues</dt>'))
        page = prompts.STARTER_INDEX.format(title="A", task="t", date="2026-10-16").encode()
        out = colleagues.add_card_row(page, row)
        self.assertIn(("<dd>2026-10-16</dd>\n  " + row + "</dl>").encode(), out)
        self.assertEqual(colleagues.add_card_row(b"<dl></dl><p>no card</p>", row), b"<dl></dl><p>no card</p>")
        self.assertEqual(colleagues.add_card_row(page, ""), page)


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


class PageUndo(unittest.TestCase):
    def test_blocks(self):
        d = util.new_tree("page-undo")
        index, before, after = (os.path.join(d, n) for n in ("index.html", "before.html", "after.html"))
        old = "<body>\n<p>a</p>\n<p>b</p>\n<p>c</p>\n<script>\nx = 1\n</script>\n</body>\n"
        new = "<body>\n<p>A</p>\n<p>b</p>\n<script>\nx = 2\n</script>\n</body>\n"
        util.write(before, old)
        util.write(index, new)
        st = page_undo.state(index, before, after, [])   # no after copy yet: the page is the run's
        self.assertEqual(st[2], [(1, 2), (3, 3), (4, 5)])
        # each block's mark at its first tag; the removed <p>c</p> at the next one; none inside the script
        marked = page_undo.mark(new, st[2], {1})
        self.assertIn('\n<template data-dirai-block="0"></template><p>A</p>', marked)
        self.assertIn('<template data-dirai-block="1" data-undone></template><script>', marked)
        self.assertIn('</script><template data-dirai-block="2"></template>\n</body>', marked)
        self.assertEqual(page_undo.toggle(index, before, after, [], 1), [1])
        self.assertIn("<p>c</p>", page_undo.read(index))
        self.assertEqual(page_undo.toggle(index, before, after, [1], 0), [0, 1])
        self.assertEqual(page_undo.toggle(index, before, after, [0, 1], 2), [0, 1, 2])
        self.assertEqual(page_undo.read(index), old)
        self.assertEqual(page_undo.toggle(index, before, after, [0, 1, 2], 1), [0, 2])
        self.assertEqual(page_undo.toggle(index, before, after, [0, 2], 0), [2])
        self.assertEqual(page_undo.toggle(index, before, after, [2], 2), [])
        self.assertEqual(page_undo.read(index), new)
        util.write(index, new + "x")
        self.assertIn("by hand", page_undo.toggle(index, before, after, [], 0))
