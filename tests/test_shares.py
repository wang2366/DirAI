"""Sharing agents (lib/shares.py): publish into an agent repo, read it from another tree, copy and update.
GitHub is stood in for by bare repos under the temp dir (DIRAI_SHARE_GIT_URL); gh isn't called."""
import os
import shutil
import subprocess
import unittest

from tests import util

REMOTE = os.path.join(util.TMP, "remote")
os.environ["DIRAI_SHARE_GIT_URL"] = REMOTE + "/%s.git"
os.environ["DIRAI_SHARE_GIT_URL_HOST"] = REMOTE + "/%s/%s.git"
os.environ["DIRAI_GH"] = os.path.join(util.TMP, "no-gh")

import shares  # noqa: E402

FULL = "wang-dirai/wang_agent_repo"
PURDUE = "git.example.edu/kubis/wang_agent_repo"     # a repo on another GitHub server (Enterprise)


FAKE_GH = """#!/usr/bin/env python3
import os, sys
a = sys.argv[1:]
host = a[a.index("--hostname") + 1] if "--hostname" in a else None
if a[:2] == ["auth", "status"]:
    if host in (None, "github.com"):
        print("github.com\\n  \\u2713 Logged in to github.com account purdue-me (keyring)\\n  - Active account: true\\n"
              "  \\u2713 Logged in to github.com account personal-me (keyring)\\n  - Active account: false")
    if host in (None, "git.example.edu"):
        print("git.example.edu\\n  \\u2713 Logged in to git.example.edu account wang (keyring)\\n  - Active account: true")
elif a[:2] == ["auth", "token"]:
    print("tok-%s-%s" % (host, a[a.index("--user") + 1]))
else:
    print("host=%s\\ntoken=%s" % (os.environ.get("GH_HOST"), os.environ.get("GH_TOKEN")))
"""


def sh(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                            GIT_COMMITTER_EMAIL="t@t"))


def make_remote(full=FULL):
    """An agent repo as create_repo leaves it: the empty marker and a README, on main."""
    bare = os.path.join(REMOTE, full + ".git")
    shutil.rmtree(bare, ignore_errors=True)
    os.makedirs(bare)
    sh(bare, "git", "init", "-q", "--bare")
    work = os.path.join(util.TMP, "seed")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    util.write(os.path.join(work, shares.MARKER), "")
    util.write(os.path.join(work, "README.md"), "x\n")
    for args in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "start"], ["branch", "-M", "main"],
                 ["remote", "add", "origin", bare], ["push", "-q", "-u", "origin", "main"]):
        sh(work, "git", *args)
    sh(bare, "git", "symbolic-ref", "HEAD", "refs/heads/main")


def ready(s):
    """As if gh and ssh were set up and the repo were found."""
    s.ready = lambda checks=None: True
    s.found = lambda force=False: {"mine": [{"full": FULL, "agents": 0}], "shared": [], "invitations": []}


class TestShares(unittest.TestCase):
    def setUp(self):
        make_remote()
        self.root = util.new_tree("sharer")
        a = os.path.join(self.root, "proj", "fit")
        util.write(os.path.join(a, "index.html"), "<h1>Fit <i>results</i></h1>")
        util.write(os.path.join(a, "fit.py"), "print(1)\n")
        util.write(os.path.join(a, "run.log"), "noise\n")
        util.write(os.path.join(a, "tmp", "scratch.txt"), "x\n")
        util.write(os.path.join(a, "demo", "index.html"), "<h1>Demo</h1>")
        util.write(os.path.join(a, ".hidden"), "x\n")
        with open(os.path.join(a, "big.bin"), "wb") as f:
            f.write(b"0" * (shares.FILE_MAX + 1))
        self.s = shares.Shares(self.root)
        ready(self.s)

    def test_folder_leaves_out_and_finds_children(self):
        files, out, children = self.s.folder("proj/fit")
        self.assertEqual(sorted(r for r, _ in files), ["fit.py", "index.html"])
        self.assertEqual(sorted(r for r, _ in out), ["big.bin", "run.log", "tmp/"])
        self.assertEqual(children, ["proj/fit/demo"])

    def test_warnings(self):
        util.write(os.path.join(self.root, "proj/fit/conf.py"), 'password = "hunter22"\ndata = "/home/bob/x.h5"\n')
        w = self.s.warnings("proj/fit", self.s.folder("proj/fit")[0])
        self.assertTrue(any("password" in x for x in w), w)
        self.assertTrue(any("/home/bob/x.h5" in x for x in w), w)

    def test_publish_read_update(self):
        r = self.s.act({"op": "publish", "repos": [FULL], "children": ["proj/fit/demo"]}, "proj/fit")
        self.assertEqual(r, {"ok": True})
        t = self.s.state()["targets"]
        self.assertEqual(t["proj/fit"][FULL]["slug"], "fit")          # no tree path in the repo
        self.assertEqual(t["proj/fit/demo"][FULL]["slug"], "fit/demo")     # inside its parent, as in the tree
        self.assertEqual(self.s.changed("proj/fit", FULL, "fit"), 0)       # its child's files aren't counted
        self.assertEqual(self.s.changed("proj/fit/demo", FULL, "fit/demo"), 0)
        util.write(os.path.join(self.root, "proj/fit/fit.py"), "print(2)\n")
        self.assertEqual(self.s.changed("proj/fit", FULL, "fit"), 1)

        # a reader's tree connects the repo and sees both agents, the child under its parent
        reader = shares.Shares(util.new_tree("reader"))
        self.assertIsNone(reader.connect(FULL))
        box = reader.box(FULL)
        self.assertEqual([(a["slug"], a["parent"], a["title"]) for a in box["agents"]],
                         [("fit", None, "Fit results"), ("fit/demo", "fit", "Demo")])
        self.assertEqual(reader.shared_page("www/shares/%s/agents/fit/demo" % FULL)["slug"], "fit/demo")
        self.assertEqual(box["owner"], "wang-dirai")

        # the reader copies it into their tree
        page = "www/shares/%s/agents/fit" % FULL
        self.assertIsNone(reader.copy(page, "mine/fit"))
        self.assertEqual(reader.origin("mine/fit")["files"], [])
        util.write(os.path.join(reader.root, "mine/fit/index.html"), "<h1>my notes</h1>")

        # the owner publishes again; the reader's fetch marks it, opening the page clears the mark
        self.assertEqual(self.s.act({"op": "publish", "repos": [FULL]}, "proj/fit"), {"ok": True})
        mine = os.path.join(self.s.clone_dir(FULL, mine=True), "agents")
        self.assertTrue(os.path.isfile(os.path.join(mine, "fit/demo/index.html")))   # the parent alone keeps its child
        util.write(os.path.join(self.root, "proj/fit/index.html"), "<h1>Fit v3</h1>")
        self.assertEqual(self.s.act({"op": "publish", "repos": [FULL]}, "proj/fit"), {"ok": True})
        self.assertIsNone(reader.fetch(FULL))
        self.assertEqual(reader.box(FULL)["updated"], 1)
        self.assertEqual(reader.shared_page(page)["slug"], "fit")
        self.assertEqual(reader.box(FULL)["updated"], 0)

        # the copy: fit.py untouched there is updated; index.html, changed by the reader, is kept
        self.assertEqual(sorted(reader.origin("mine/fit")["files"]), ["fit.py", "index.html"])
        done, kept = reader.update_copy("mine/fit")
        self.assertEqual((done, kept), (["fit.py"], ["index.html"]))
        with open(os.path.join(reader.root, "mine/fit/fit.py")) as f:
            self.assertEqual(f.read(), "print(2)\n")
        with open(os.path.join(reader.root, "mine/fit/index.html")) as f:
            self.assertEqual(f.read(), "<h1>my notes</h1>")
        with open(os.path.join(reader.root, "mine/fit/index.html.theirs")) as f:
            self.assertEqual(f.read(), "<h1>Fit v3</h1>")
        self.assertEqual(reader.origin("mine/fit")["files"], [])

        # unshare removes it and its child in a new commit; the reader's next fetch drops them
        self.assertEqual(self.s.act({"op": "unshare", "repo": FULL}, "proj/fit"), {"ok": True})
        self.assertEqual(self.s.state()["targets"], {})
        reader.fetch(FULL)
        self.assertEqual(reader.box(FULL)["agents"], [])
        self.assertIsNone(reader.disconnect(FULL))
        self.assertFalse(os.path.exists(reader.clone_dir(FULL)))

    def test_publish_refuses_unknown_repo_and_unready(self):
        self.assertIn("error", self.s.act({"op": "publish", "repos": ["x/y_agent_repo"]}, "proj/fit"))
        self.s.ready = lambda checks=None: False
        self.assertIn("error", self.s.act({"op": "publish", "repos": [FULL]}, "proj/fit"))

    def test_unshare_one_child(self):
        self.s.act({"op": "publish", "repos": [FULL], "children": ["proj/fit/demo"]}, "proj/fit")
        self.assertIn("error", self.s.act({"op": "unshare", "repo": "*", "child": "proj/other"}, "proj/fit"))
        self.assertEqual(self.s.act({"op": "unshare", "repo": "*", "child": "proj/fit/demo"}, "proj/fit"), {"ok": True})
        self.assertEqual(sorted(self.s.state()["targets"]), ["proj/fit"])
        mine = os.path.join(self.s.clone_dir(FULL, mine=True), "agents")
        self.assertFalse(os.path.exists(os.path.join(mine, "fit/demo")))
        self.assertTrue(os.path.isfile(os.path.join(mine, "fit/index.html")))

    def test_old_flat_child_moves_inside_parent(self):
        self.s.act({"op": "publish", "repos": [FULL], "children": ["proj/fit/demo"]}, "proj/fit")
        mine = os.path.join(self.s.clone_dir(FULL, mine=True), "agents")
        # as published before 2026-11-19: the child side by side, as fit--demo
        with self.s.lock:
            s = self.s.state()
            s["targets"]["proj/fit/demo"][FULL]["slug"] = "fit--demo"
            self.s.save(s)
        clone = os.path.dirname(mine)
        for args in (["mv", "agents/fit/demo", "agents/fit--demo"], ["commit", "-q", "-m", "old layout"],
                     ["push", "-q", "origin", "HEAD"]):
            sh(clone, "git", *args)
        self.s.act({"op": "publish", "repos": [FULL], "children": ["proj/fit/demo"]}, "proj/fit")
        self.assertEqual(self.s.state()["targets"]["proj/fit/demo"][FULL]["slug"], "fit/demo")
        self.assertFalse(os.path.exists(os.path.join(mine, "fit--demo")))
        self.assertTrue(os.path.isfile(os.path.join(mine, "fit/demo/index.html")))

    def test_unshare_parent_removes_old_flat_child(self):
        self.s.act({"op": "publish", "repos": [FULL], "children": ["proj/fit/demo"]}, "proj/fit")
        mine = os.path.join(self.s.clone_dir(FULL, mine=True), "agents")
        with self.s.lock:     # as published before 2026-11-19: fit and fit--demo side by side
            s = self.s.state()
            s["targets"]["proj/fit/demo"][FULL]["slug"] = "fit--demo"
            self.s.save(s)
        clone = os.path.dirname(mine)
        for args in (["mv", "agents/fit/demo", "agents/fit--demo"], ["commit", "-q", "-m", "old layout"],
                     ["push", "-q", "origin", "HEAD"]):
            sh(clone, "git", *args)
        self.assertEqual(self.s.act({"op": "unshare", "repo": FULL}, "proj/fit"), {"ok": True})
        self.assertFalse(os.path.exists(os.path.join(mine, "fit")))
        self.assertFalse(os.path.exists(os.path.join(mine, "fit--demo")))
        self.assertEqual(self.s.state()["targets"], {})

    def test_unshare_ticked_agents_from_ticked_repos(self):
        # the popover's one Unshare… next to Publish: the ticked agents, the ticked repos
        self.s.act({"op": "publish", "repos": [FULL], "children": ["proj/fit/demo"]}, "proj/fit")
        mine = os.path.join(self.s.clone_dir(FULL, mine=True), "agents")
        self.assertIn("error", self.s.act({"op": "unshare", "repos": [FULL], "agents": ["proj/other"]}, "proj/fit"))
        self.assertIn("error", self.s.act({"op": "unshare", "repos": ["someone/else"], "agents": ["proj/fit"]}, "proj/fit"))
        self.assertEqual(self.s.act({"op": "unshare", "repos": [FULL], "agents": ["proj/fit/demo"]}, "proj/fit"), {"ok": True})
        self.assertTrue(os.path.isfile(os.path.join(mine, "fit/index.html")))
        self.assertFalse(os.path.exists(os.path.join(mine, "fit/demo")))
        self.s.act({"op": "publish", "repos": [FULL], "children": ["proj/fit/demo"]}, "proj/fit")
        self.assertEqual(self.s.act({"op": "unshare", "repos": [FULL], "agents": ["proj/fit", "proj/fit/demo"]}, "proj/fit"), {"ok": True})
        self.assertFalse(os.path.exists(os.path.join(mine, "fit")))
        self.assertEqual(self.s.state()["targets"], {})

    def test_copy_publishes_back_to_its_place(self):
        # a child copied out of the shared repo goes back to its place there (fit/demo), not to a new demo/
        self.s.act({"op": "publish", "repos": [FULL], "children": ["proj/fit/demo"]}, "proj/fit")
        self.assertIsNone(self.s.connect(FULL))
        self.assertIsNone(self.s.copy("www/shares/%s/agents/fit/demo" % FULL, "copies/demo"))
        util.write(os.path.join(self.root, "copies/demo/index.html"), "<h1>Demo v2</h1>")
        # the original still holds that place in this tree: refused, and nothing changes
        r = self.s.act({"op": "publish", "repos": [FULL]}, "copies/demo")
        self.assertIn("proj/fit/demo is already shared at fit/demo", r.get("error", ""))
        self.assertNotIn("copies/demo", self.s.state()["targets"])
        # once the original is unshared there, the copy goes back to fit/demo
        self.assertEqual(self.s.act({"op": "unshare", "repos": [FULL], "agents": ["proj/fit/demo"]}, "proj/fit"), {"ok": True})
        self.assertEqual(self.s.act({"op": "publish", "repos": [FULL]}, "copies/demo"), {"ok": True})
        t = self.s.state()["targets"]
        self.assertEqual(t["copies/demo"][FULL]["slug"], "fit/demo")
        self.assertNotIn("proj/fit/demo", t)
        # and now the original, ticked in its parent's Publish, is the one refused
        self.assertIn("copies/demo is already shared at fit/demo",
                      self.s.act({"op": "publish", "repos": [FULL], "children": ["proj/fit/demo"]}, "proj/fit").get("error", ""))
        mine = os.path.join(self.s.clone_dir(FULL, mine=True), "agents")
        with open(os.path.join(mine, "fit/demo/index.html")) as f:
            self.assertEqual(f.read(), "<h1>Demo v2</h1>")
        self.assertFalse(os.path.exists(os.path.join(mine, "demo")))
        self.assertIsNone(self.s.fetch(FULL))
        self.assertEqual(self.s.origin("copies/demo")["files"], [])   # its own Publish isn't "a newer version"
        # a copy whose origin is another repo gets a name of its own
        util.write(os.path.join(self.root, "copies/x/index.html"), "<h1>X</h1>")
        util.write(os.path.join(self.root, "copies/x/.dirai-origin"), '{"repo": "alice-dirai/alice_agent_repo", "slug": "x/y"}')
        self.assertEqual(self.s.act({"op": "publish", "repos": [FULL]}, "copies/x"), {"ok": True})
        self.assertEqual(self.s.state()["targets"]["copies/x"][FULL]["slug"], "x")

    def test_slugs_stay_unique(self):
        util.write(os.path.join(self.root, "other/fit/index.html"), "<h1>Other</h1>")
        self.s.act({"op": "publish", "repos": [FULL]}, "proj/fit")
        self.s.act({"op": "publish", "repos": [FULL]}, "other/fit")
        self.assertEqual(self.s.state()["targets"]["other/fit"][FULL]["slug"], "fit-2")

    def test_share_as_account(self):
        # a gh holding two github.com accounts, the Purdue one active (written by the test, never the real gh)
        fake = os.path.join(util.TMP, "fake-gh")
        util.write(fake, FAKE_GH)
        os.chmod(fake, 0o755)
        old = shares.GH
        shares.GH = fake
        try:
            self.assertEqual(shares.gh_accounts(), (["purdue-me", "personal-me"], "purdue-me"))
            a = shares.auth(force=True)
            self.assertEqual((a["login"], a["token"]), ("purdue-me", "tok-github.com-purdue-me"))     # nothing chosen: the active one
            self.assertEqual(self.s.act({"op": "account", "account": "nobody"})["error"][:6], "gh hol")
            self.assertEqual(self.s.act({"op": "account", "account": "personal-me"}), {"ok": True})
            self.assertEqual(shares.chosen_account(), "personal-me")
            a = shares.auth()
            self.assertEqual((a["login"], a["token"]), ("personal-me", "tok-github.com-personal-me"))
            # gh runs as that account, on github.com, whatever the caller's own GH_TOKEN/GH_HOST
            rc, out = shares.gh("api", "user")
            self.assertEqual(out.splitlines(), ["host=github.com", "token=tok-github.com-personal-me"])
            # another GitHub server gh is logged in to: its own account and token, github.com's unchanged
            self.assertEqual(shares.gh_hosts(), ["git.example.edu"])
            rc, out = shares.gh("api", "user", host="git.example.edu")
            self.assertEqual(out.splitlines(), ["host=git.example.edu", "token=tok-git.example.edu-wang"])
            self.assertEqual(shares.auth()["login"], "personal-me")
            # a chosen account this machine's gh doesn't hold: refused, not run as the active one
            shares.choose_account("elsewhere")
            self.assertEqual(shares.gh("api", "user")[0], 1)
            self.assertIsNone(shares.auth()["token"])
        finally:
            shares.GH = old
            shares._auth.clear()
            if os.path.exists(shares.ACCOUNT_FILE):
                os.remove(shares.ACCOUNT_FILE)

    def test_repo_on_another_server(self):
        # D7: a repo on another GitHub server ("<host>/<owner>/<repo>"), published to with github.com's in one go
        make_remote(PURDUE)
        self.assertEqual(shares.split_full(PURDUE), ("git.example.edu", "kubis/wang_agent_repo"))
        self.assertEqual(shares.split_full(FULL), ("github.com", FULL))
        self.assertEqual(shares.web_url(PURDUE), "https://git.example.edu/kubis/wang_agent_repo")
        self.s.found = lambda force=False: {"mine": [{"full": FULL}, {"full": PURDUE}], "shared": [], "invitations": []}
        self.assertEqual(self.s.act({"op": "publish", "repos": [FULL, PURDUE]}, "proj/fit"), {"ok": True})
        self.assertEqual(sorted(self.s.state()["targets"]["proj/fit"]), sorted([FULL, PURDUE]))
        self.assertTrue(os.path.isfile(os.path.join(self.s.clone_dir(PURDUE, mine=True), "agents/fit/index.html")))
        reader = shares.Shares(util.new_tree("reader2"))
        self.assertIsNone(reader.connect(PURDUE))
        self.assertTrue(reader.clone_dir(PURDUE).endswith("www/shares/git.example.edu/kubis/wang_agent_repo"))
        box = reader.box(PURDUE)
        self.assertEqual((box["owner"], box["repo"], box["host"]), ("kubis", "wang_agent_repo", "git.example.edu"))
        page = box["agents"][0]["url"].strip("/")
        sp = reader.shared_page(page)
        self.assertEqual((sp["full"], sp["slug"], sp["owner"]), (PURDUE, "fit", "kubis"))
        self.assertIsNone(reader.shared_page("www/shares/git.example.edu/kubis/agents/fit"))   # too short

    def test_create_repo_refuses_unknown_server_and_visibility(self):
        self.assertIn("no login", self.s._create_repo("x", "nowhere.example.org", "kubis", "private"))
        self.assertIn("private or internal", self.s._create_repo("x", "github.com", "kubis", "public"))

    def test_remove_repo_from_list(self):
        # Remove from list: off this tree's Share to list and the Connect row's "yours"; nothing on GitHub changes
        self.s.checks = lambda force=False: [{"login": "wang"}, {}, {"ok": True, "org": "wang-dirai"}, {}]
        self.s.act({"op": "publish", "repos": [FULL]}, "proj/fit")
        self.assertIn("error", self.s.act({"op": "hide", "repo": "someone/else_agent_repo"}, "proj/fit"))
        self.assertEqual(self.s.act({"op": "hide", "repo": FULL}, "proj/fit"), {"ok": True})
        p = self.s.page_state("proj/fit")
        self.assertEqual((p["repos"], p["hidden"]), ([], [{"full": FULL, "shared": True}]))
        self.assertEqual(self.s.report()["mine"], [])
        self.assertIn(FULL, self.s.state()["targets"]["proj/fit"])          # still published there
        self.assertTrue(os.path.isdir(self.s.clone_dir(FULL, mine=True)))
        self.assertEqual(self.s.act({"op": "unhide", "repo": FULL}, "proj/fit"), {"ok": True})
        p = self.s.page_state("proj/fit")
        self.assertEqual(([r["full"] for r in p["repos"]], p["hidden"]), ([FULL], []))

    def test_remove_copy_only_inside_copies(self):
        origin = '{"repo": "x/y", "slug": "fit", "commit": "abc"}'
        for rel in ("copies/fit", "elsewhere/fit", "copies/plain"):
            util.write(os.path.join(self.root, rel, "index.html"), "<h1>C</h1>")
            util.write(os.path.join(self.root, rel, "a.py"), "1\n")
        for rel in ("copies/fit", "elsewhere/fit"):          # a copy by name; and one moved out of copies/
            util.write(os.path.join(self.root, rel, ".dirai-origin"), origin)
        self.assertTrue(self.s.removable("copies/fit"))
        self.assertFalse(self.s.removable("elsewhere/fit"))   # outside copies/
        self.assertFalse(self.s.removable("copies/plain"))    # no .dirai-origin
        self.assertFalse(self.s.removable("copies"))
        self.assertFalse(self.s.removable("copies/../elsewhere/fit"))
        self.assertFalse(self.s.removable(""))
        self.assertIn("only an agent inside copies/", self.s.remove_copy("elsewhere/fit"))
        self.assertTrue(os.path.isdir(os.path.join(self.root, "elsewhere/fit")))
        self.assertEqual(self.s.copy_info("copies/fit")["files"], 2)     # index.html, a.py (.dirai-origin is hidden)
        self.assertIsNone(self.s.remove_copy("copies/fit"))
        self.assertFalse(os.path.exists(os.path.join(self.root, "copies/fit")))
        trash = os.path.join(self.root, "www", "trash")
        self.assertEqual(len(os.listdir(trash)), 1)                      # moved there, not deleted
        self.assertTrue(os.path.isfile(os.path.join(trash, os.listdir(trash)[0], "a.py")))

    def test_org_name(self):
        self.assertEqual(shares.org_name("wang2366", "-dirai"), "wang2366-dirai")
        self.assertEqual(len(shares.org_name("a" * 39, "-dirai-agents")), 39)


if __name__ == "__main__":
    unittest.main()
