"""Shared setup for the tests: DirAI's folder on sys.path, and config/state kept in a temp dir."""
import atexit
import os
import shutil
import sys
import tempfile

TOOL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = os.path.realpath(tempfile.mkdtemp(prefix="dirai-test-"))
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
# before any DirAI module is imported: they read these at import time
os.environ["DIRAI_CONFIG_DIR"] = os.path.join(TMP, "config")
os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(TMP, "claude")
os.environ["REVIEW_CLAUDE_CMD"] = os.path.join(TOOL, "tests", "fake_claude.py")
os.makedirs(os.path.join(TMP, "claude", "projects"), exist_ok=True)
if TOOL not in sys.path:
    sys.path.insert(0, TOOL)


def new_tree(name):
    """An empty tree (with www/) under TMP."""
    root = os.path.join(TMP, name)
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(os.path.join(root, "www"))
    return root


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
