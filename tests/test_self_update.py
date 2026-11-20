"""self_update: the top server's Pull (git pull --ff-only and its checks) on throwaway repos:
an upstream (bare), DirAI's checkout cloned from it, and another clone that pushes new commits."""
import os
import subprocess
import time
import unittest
from unittest import mock

from tests import util

import self_update

ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
           GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def git(cwd, *args):
    return subprocess.run(["git"] + list(args), cwd=cwd, env=ENV, check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, universal_newlines=True).stdout.strip()


class Pull(unittest.TestCase):
    def setUp(self):
        base = util.new_tree("pull-" + self.id().rsplit(".", 1)[1])
        self.up, self.tool, self.other = (os.path.join(base, n) for n in ("up.git", "tool", "other"))
        git(base, "init", "-q", "--bare", self.up)     # not "-b main": git before 2.28 has no -b
        git(self.up, "symbolic-ref", "HEAD", "refs/heads/main")
        git(base, "clone", "-q", self.up, self.other)
        util.write(os.path.join(self.other, "lib", "a.py"), "a = 1\n")
        util.write(os.path.join(self.other, "README.md"), "readme\n")
        git(self.other, "add", "-A")
        git(self.other, "commit", "-q", "-m", "first")
        git(self.other, "push", "-q", "origin", "HEAD:main")
        git(base, "clone", "-q", self.up, self.tool)
        self_update._state.update(fetched=time.time(), fetch_error="", pulled="", note="")   # no background fetch

    def push_change(self, path="lib/a.py", text="a = 2\n", msg="second"):
        util.write(os.path.join(self.other, path), text)
        git(self.other, "commit", "-qam", msg)
        git(self.other, "push", "-q", "origin", "HEAD:main")
        git(self.tool, "fetch", "-q")

    def test_up_to_date(self):
        st = self_update.status(self.tool)
        self.assertEqual((st["pull"], st["upstream"], st["behind"], st["ahead"]), (True, "origin/main", 0, 0))
        self.assertIn("already up to date", self_update.pull(self.tool)["error"])

    def test_pull_fast_forward_keeps_other_changes(self):
        self.push_change()
        util.write(os.path.join(self.tool, "README.md"), "my local note\n")     # not touched by the pull
        st = self_update.status(self.tool)
        self.assertEqual((st["behind"], len(st["incoming"])), (1, 1))
        self.assertTrue(st["incoming"][0].endswith("second"))
        out = self_update.pull(self.tool)
        self.assertTrue(out["ok"], out)
        with open(os.path.join(self.tool, "lib", "a.py")) as f:
            self.assertEqual(f.read(), "a = 2\n")
        with open(os.path.join(self.tool, "README.md")) as f:
            self.assertEqual(f.read(), "my local note\n")
        self.assertEqual(self_update.status(self.tool)["behind"], 0)
        self.assertIn(" → ", self_update.status(self.tool)["pulled"])

    def test_refuses_when_a_changed_file_is_touched(self):
        self.push_change()
        util.write(os.path.join(self.tool, "lib", "a.py"), "a = 99\n")
        out = self_update.pull(self.tool)
        self.assertIn("uncommitted changes here: lib/a.py", out["error"])
        self.assertTrue(any(c.startswith("git diff") for c in out["commands"]))
        with open(os.path.join(self.tool, "lib", "a.py")) as f:
            self.assertEqual(f.read(), "a = 99\n")

    def test_refuses_when_diverged(self):
        self.push_change()
        util.write(os.path.join(self.tool, "lib", "b.py"), "b = 1\n")
        git(self.tool, "add", "lib/b.py")
        git(self.tool, "commit", "-qm", "local")
        out = self_update.pull(self.tool)
        self.assertIn("not a fast-forward", out["error"])
        self.assertEqual(git(self.tool, "log", "-1", "--format=%s"), "local")

    def test_refuses_during_a_commit(self):
        self.push_change()
        util.write(os.path.join(self.tool, ".git", "index.lock"), "")
        self.assertIn("a git command is running", self_update.pull(self.tool)["error"])

    def test_copy_or_no_upstream_never_pulls(self):
        util.write(os.path.join(self.tool, "BUILD"), "{}")
        self.assertEqual(self_update.status(self.tool), {"pull": False})
        os.remove(os.path.join(self.tool, "BUILD"))
        git(self.tool, "branch", "-q", "--unset-upstream")
        self.assertEqual(self_update.status(self.tool), {"pull": False})

    def rewrite(self, with_map=True, then=None):
        """Rewrite the upstream's history (each commit's tree, new message, so new ids), add the map
        (REWRITE_MAP) if with_map and then a change (path, text) if given, force-push, fetch in tool."""
        parent, lines = None, ["# a test rewrite"]
        for old in git(self.other, "rev-list", "--reverse", "HEAD").split():
            tree = git(self.other, "rev-parse", old + "^{tree}")
            parent = git(self.other, "commit-tree", tree, "-m", "rewritten " + old[:7], *(["-p", parent] if parent else []))
            lines.append("%s %s" % (old, parent))
        git(self.other, "reset", "-q", "--hard", parent)
        if with_map:
            util.write(os.path.join(self.other, self_update.REWRITE_MAP), "\n".join(lines) + "\n")
            git(self.other, "add", "-A")
            git(self.other, "commit", "-qm", "map")
        if then:
            util.write(os.path.join(self.other, then[0]), then[1])
            git(self.other, "commit", "-qam", "after")
        git(self.other, "push", "-qf", "origin", "HEAD:main")
        git(self.tool, "fetch", "-q")

    def commit_local(self, path="lib/b.py", text="b = 1\n"):
        util.write(os.path.join(self.tool, path), text)
        git(self.tool, "add", path)
        git(self.tool, "commit", "-qm", "local")

    def test_rewritten_history_moves_the_checkout(self):
        self.push_change()
        util.write(os.path.join(self.tool, "README.md"), "my local note\n")     # same in old and new history
        self.rewrite()
        st = self_update.status(self.tool)
        self.assertEqual(st["rewritten"]["own"], 0)
        out = self_update.pull(self.tool)
        self.assertTrue(out["ok"], out)
        self.assertEqual(git(self.tool, "rev-parse", "HEAD"), git(self.tool, "rev-parse", "@{u}"))
        with open(os.path.join(self.tool, "README.md")) as f:
            self.assertEqual(f.read(), "my local note\n")
        st = self_update.status(self.tool)
        self.assertEqual((st["ahead"], st["behind"], st["rewritten"]), (0, 0, None))

    def test_rewritten_history_keeps_own_commits_on_top(self):
        self.commit_local()
        self.rewrite()
        self.assertEqual(self_update.status(self.tool)["rewritten"]["own"], 1)
        out = self_update.pull(self.tool)
        self.assertTrue(out["ok"], out)
        self.assertEqual(git(self.tool, "log", "-1", "--format=%s"), "local")
        self.assertEqual(git(self.tool, "rev-parse", "HEAD^"), git(self.tool, "rev-parse", "@{u}"))
        st = self_update.status(self.tool)
        self.assertEqual((st["ahead"], st["behind"]), (1, 0))

    def test_rewritten_history_own_commits_need_a_clean_checkout(self):
        self.commit_local()
        util.write(os.path.join(self.tool, "README.md"), "my local note\n")
        self.rewrite()
        head = git(self.tool, "rev-parse", "HEAD")
        out = self_update.pull(self.tool)
        self.assertIn("needs no uncommitted changes", out["error"])
        self.assertIn("git stash", out["commands"])
        self.assertEqual(git(self.tool, "rev-parse", "HEAD"), head)

    def test_rewritten_history_conflict_is_undone(self):
        self.commit_local("lib/a.py", "a = 5\n")
        self.rewrite(then=("lib/a.py", "a = 7\n"))
        head = git(self.tool, "rev-parse", "HEAD")
        out = self_update.pull(self.tool)
        self.assertIn("conflicted (undone)", out["error"])
        self.assertEqual(git(self.tool, "rev-parse", "HEAD"), head)
        self.assertEqual(git(self.tool, "status", "--porcelain"), "")

    def test_rewritten_history_without_map_is_refused_with_reset_advice(self):
        self.rewrite(with_map=False)
        head = git(self.tool, "rev-parse", "HEAD")
        st = self_update.status(self.tool)
        self.assertEqual((st["ahead"], st["behind"], st["rewritten"]), (1, 1, None))
        out = self_update.pull(self.tool)
        self.assertIn("shares no history", out["error"])
        self.assertTrue(any(c.startswith("git reset --keep @{u}") for c in out["commands"]))
        self.assertEqual(git(self.tool, "rev-parse", "HEAD"), head)

    def install_sh(self):
        """Run install.sh as the curl line does (piped into bash), with the clone in self.tool."""
        home = os.path.join(os.path.dirname(self.tool), "home")
        os.makedirs(home, exist_ok=True)
        env = dict(ENV, HOME=home, DIRAI_HOME=self.tool, DIRAI_BIN=os.path.join(home, "bin"),
                   DIRAI_CLAUDE_CMD="/bin/true", OLLAMA_HOST="127.0.0.1:9")
        with open(os.path.join(REPO, "install.sh")) as f:
            r = subprocess.run(["bash"], stdin=f, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               universal_newlines=True)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(git(self.tool, "rev-parse", "HEAD"), git(self.tool, "rev-parse", "origin/main"))
        self.assertEqual(git(self.tool, "status", "--porcelain", "--untracked-files=no"), "")
        return r.stdout

    def test_install_sh_updates_a_rewritten_install(self):
        self.push_change()
        self.rewrite()
        self.install_sh()

    def test_install_sh_makes_the_install_match_origin_and_prunes_the_rest(self):
        self.commit_local()
        mine = git(self.tool, "rev-parse", "HEAD")
        util.write(os.path.join(self.tool, "README.md"), "my local note\n")
        git(self.tool, "stash", "-q")
        util.write(os.path.join(self.tool, "README.md"), "my local note\n")
        git(self.tool, "branch", "-q", "other")
        self.push_change()
        self.rewrite()
        old = git(self.tool, "rev-parse", "HEAD~1")
        self.install_sh()
        self.assertEqual(git(self.tool, "for-each-ref", "--format=%(refname)"), "refs/heads/main\nrefs/remotes/origin/main")
        for gone in (mine, old):        # no longer on disk at all
            self.assertNotEqual(subprocess.run(["git", "-C", self.tool, "cat-file", "-e", gone], env=ENV).returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.tool, "lib", "b.py")))
        self.install_sh()               # run again: still fine

    def test_restart_when_idle_waits_for_runs(self):
        runs, done = [2], []
        with mock.patch.object(self_update, "IDLE_CHECK_S", 0.05):
            self_update.restart_when_idle(lambda: runs[0], lambda: done.append(1))
            time.sleep(0.2)
            self.assertEqual((done, self_update._state["note"]), ([], "restart waits: 2 agent runs going"))
            runs[0] = 0
            for _ in range(40):
                if done:
                    break
                time.sleep(0.05)
        self.assertEqual(done, [1])


if __name__ == "__main__":
    unittest.main()
