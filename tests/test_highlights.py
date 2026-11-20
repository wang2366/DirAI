"""The change marks in the browser (tests/highlights.js): yellow for what the latest run added or
changed, red and collapsed for what it removed, in index.html and in the folder's files. Needs node
and Playwright's chromium; skipped without them."""
import os
import shutil
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def node_path():
    """NODE_PATH that finds playwright (a global install too), or None when node or it is missing."""
    if not shutil.which("node"):
        return None
    paths = [p for p in os.environ.get("NODE_PATH", "").split(os.pathsep) if p]
    if shutil.which("npm"):
        root = subprocess.run(["npm", "root", "-g"], stdout=subprocess.PIPE, universal_newlines=True).stdout.strip()
        if root:
            paths.append(root)
    env = dict(os.environ, NODE_PATH=os.pathsep.join(paths))
    found = subprocess.run(["node", "-e", "require.resolve('playwright')"], env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return env["NODE_PATH"] if found.returncode == 0 else None


class HighlightTest(unittest.TestCase):
    def test_marks(self):
        np = node_path()
        if np is None:
            self.skipTest("needs node and playwright")
        run = subprocess.run(["node", os.path.join(HERE, "highlights.js")], env=dict(os.environ, NODE_PATH=np),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=120)
        if "Executable doesn't exist" in run.stdout + run.stderr:
            self.skipTest("needs Playwright's chromium")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
