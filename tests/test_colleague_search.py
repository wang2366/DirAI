"""Keyword search over the tree's agents (colleague_search.py), on a throw-away tree."""
import os
import unittest

from tests import util

import colleague_search as cs

CARD = """<!doctype html><html><head><title>%s</title></head><body><h1>x</h1>
<!-- dirai:card --><details id="dirai-card" open><summary>Summary</summary><dl>
<dt>Objective</dt><dd>%s</dd><dt>Inputs</dt><dd>%s</dd><dt>Outputs</dt><dd>%s</dd>
<dt>Result</dt><dd>r</dd><dt>Open</dt><dd>none</dd><dt>Updated</dt><dd>2026-10-25</dd></dl>
</details><!-- /dirai:card --><p>%s</p></body></html>"""


def make(root, rel, title, obj="o", inp="none", out="none", body=""):
    util.write(os.path.join(root, rel, "index.html"), CARD % (title, obj, inp, out, body))
    return os.path.join(root, rel)


class SearchTest(unittest.TestCase):
    def setUp(self):
        r = self.root = util.new_tree("colleague-search")
        d = make(r, "projA/calib", "Calibration", out="calib.csv v2")
        util.write(os.path.join(d, "data", "calib.csv"), "")
        make(r, "projA/fit", "Fit", inp="reads calib.csv from projA/calib")
        make(r, "notes", "Notes", body="calib.csv looks off at the edges")
        make(r, "other", "Other", obj="unrelated")
        self.agents = [{"dir": p, "title": t} for p, t in
                       (("projA/calib", "Calibration"), ("projA/fit", "Fit"), ("notes", "Notes"),
                        ("other", "Other"))]
        self.agents.append({"dir": "far/agent", "title": "Calib remote", "machine": "hpc"})
        self.idx = cs.build_index(r, self.agents)

    def test_ranking(self):
        got = cs.search(self.idx, "calib.csv")
        self.assertEqual([g["path"] for g in got], ["projA/calib", "projA/fit", "notes"])
        self.assertEqual([g["rank"] for g in got], [1, 3, 4])
        self.assertEqual(got[0]["why"], "file: data/calib.csv")

    def test_remote_rows_skipped(self):
        self.assertNotIn("far/agent", [e["path"] for e in self.idx])
        self.assertEqual(cs.search(self.idx, "remote"), [])

    def test_all_words_and_exclude(self):
        self.assertEqual([g["path"] for g in cs.search(self.idx, "calib fit")], ["projA/fit"])
        self.assertNotIn("projA/calib", [g["path"] for g in cs.search(self.idx, "calib", exclude="projA/calib")])

    def test_empty_and_limit(self):
        self.assertEqual(cs.search(self.idx, "  "), [])
        self.assertEqual(len(cs.search(self.idx, "projA", limit=1)), 1)

    def test_index_file_round_trip(self):
        cs.save_index(self.root, self.idx)
        self.assertEqual(cs.load_index(self.root), self.idx)


if __name__ == "__main__":
    unittest.main()
