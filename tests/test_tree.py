"""The Tree tab's model (web/agent_tree.js, tests/tree_model.js) under node; skipped without node."""
import os
import shutil
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


class TreeModelTest(unittest.TestCase):
    def test_model(self):
        if not shutil.which("node"):
            self.skipTest("needs node")
        run = subprocess.run(["node", os.path.join(HERE, "tree_model.js")], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             universal_newlines=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout)


if __name__ == "__main__":
    unittest.main()
