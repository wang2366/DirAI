"""One tree reached by two routes is one tree: remotes.tree_id, its place in DirAI list --json, and the
agent list's choice of the route that lists it (agent_list.js listedRoute, run with node)."""
import json
import os
import re
import shutil
import subprocess
import unittest

from tests import util

import dirai_config
import remotes

JS = os.path.join(util.TOOL, "web", "agent_list.js")


class TreeId(unittest.TestCase):
    def test_same_key_and_root_same_id(self):
        root = util.new_tree("tid-a")
        a = remotes.tree_id("k1", root)
        self.assertRegex(a, r"^[0-9a-f]{16}$")
        self.assertEqual(a, remotes.tree_id("k1", root))
        self.assertNotEqual(a, remotes.tree_id("k1", util.new_tree("tid-b")))   # another tree
        self.assertNotEqual(a, remotes.tree_id("k2", root))                      # another user's DirAI
        self.assertEqual(remotes.tree_id("", root), "")                          # no key yet: no id, not merged

    def test_a_link_to_the_root_is_the_same_tree(self):
        root = util.new_tree("tid-real")
        link = os.path.join(util.TMP, "tid-link")
        if os.path.lexists(link):
            os.remove(link)
        os.symlink(root, link)
        self.assertEqual(remotes.tree_id("k", link), remotes.tree_id("k", root))

    def test_machine_report_has_it(self):
        root = util.new_tree("tid-listed")
        os.makedirs(dirai_config.CONFIG_DIR, exist_ok=True)
        keep = {}
        for p in (dirai_config.KEY_FILE, dirai_config.TREES_FILE):
            if os.path.exists(p):
                with open(p) as f:
                    keep[p] = f.read()
        try:
            util.write(dirai_config.KEY_FILE, "secret-key\n")
            util.write(dirai_config.TREES_FILE, root + "\n")
            rep = remotes.machine_report()
            t = [x for x in rep["trees"] if x["root"] == root][0]
            self.assertEqual(t["tree_id"], remotes.tree_id("secret-key", root))
            self.assertNotIn("secret-key", json.dumps(rep["trees"]))    # only the hash, per tree
        finally:
            for p in (dirai_config.KEY_FILE, dirai_config.TREES_FILE):
                if p in keep:
                    util.write(p, keep[p])
                elif os.path.exists(p):
                    os.remove(p)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class ListedRoute(unittest.TestCase):
    """listedRoute(rep) -> {tree id: id of the route whose agents are listed}."""

    def run_js(self, trees):
        with open(JS) as f:
            src = f.read()
        fn = re.search(r"\n  function listedRoute\(rep\) \{.*?\n  \}\n", src, re.S).group(0)
        prog = fn + "\nconsole.log(JSON.stringify(listedRoute(%s)));" % json.dumps({"trees": trees})
        r = subprocess.run(["node", "-e", prog], capture_output=True, text=True, check=True)
        return json.loads(r.stdout)

    @staticmethod
    def tree(tid, via, tree_id="t1", state="alive", stale=False, checked=100, hidden=False, agents=1):
        return {"id": tid, "via": via, "tree_id": tree_id, "state": state, "stale": stale, "checked": checked,
                "hidden": hidden, "agents": [{"dir": "a"}] * agents}

    def test_direct_route_lists_a_tree_reached_twice(self):
        out = self.run_js([self.tree("negishi:/s", ["negishi"], checked=100),
                           self.tree("nas/negishi:/s", ["nas", "negishi"], checked=105)])
        self.assertEqual(out, {"negishi:/s": "negishi:/s", "nas/negishi:/s": "negishi:/s"})

    def test_a_live_route_beats_a_stale_one(self):
        out = self.run_js([self.tree("negishi:/s", ["negishi"], state="not answering", stale=True),
                           self.tree("nas/negishi:/s", ["nas", "negishi"])])
        self.assertEqual(out["negishi:/s"], "nas/negishi:/s")

    def test_a_hidden_route_is_not_picked(self):
        out = self.run_js([self.tree("negishi:/s", ["negishi"], hidden=True),
                           self.tree("nas/negishi:/s", ["nas", "negishi"])])
        self.assertEqual(out["negishi:/s"], "nas/negishi:/s")
        self.assertEqual(out["nas/negishi:/s"], "nas/negishi:/s")

    def test_other_trees_and_trees_without_an_id_are_kept_apart(self):
        out = self.run_js([self.tree("negishi:/s", ["negishi"], tree_id="t1"),
                           self.tree("negishi:/h", ["negishi"], tree_id="t2"),
                           self.tree("old:/x", ["old"], tree_id=""),
                           self.tree("nas/old:/x", ["nas", "old"], tree_id="")])
        self.assertEqual(out, {"negishi:/s": "negishi:/s", "negishi:/h": "negishi:/h",
                               "old:/x": "old:/x", "nas/old:/x": "nas/old:/x"})


if __name__ == "__main__":
    unittest.main()
