"""Shared setup for the tests: DirAI's folder on sys.path, and config/state kept in a temp dir."""
import atexit
import os
import shutil
import sys
import tempfile

TOOL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(TOOL, "lib")
TMP = os.path.realpath(tempfile.mkdtemp(prefix="dirai-test-"))
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
# before any DirAI module is imported: they read these at import time
os.environ["DIRAI_CONFIG_DIR"] = os.path.join(TMP, "config")
os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(TMP, "claude")
os.environ["REVIEW_CLAUDE_CMD"] = os.path.join(TOOL, "tests", "fake_claude.py")
# Codex: the stand-in, and its home (login, session logs) in the temp dir, never the real ones
os.environ["DIRAI_CODEX_CMD"] = os.path.join(TOOL, "tests", "fake_codex.py")
os.environ["CODEX_HOME"] = os.path.join(TMP, "codex")
# no GenAI Studio key and no Ollama unless a test sets them up (not the real ones of whoever runs the tests)
os.environ["DIRAI_GENAI_KEY_FILE"] = os.path.join(TMP, "genai_key")
os.environ["OLLAMA_HOST"] = "127.0.0.1:1"
# sharing (shares.py): no gh, so no test reaches GitHub as whoever runs the tests
os.environ["DIRAI_GH"] = os.path.join(TMP, "no-gh")
os.makedirs(os.path.join(TMP, "claude", "projects"), exist_ok=True)
if LIB not in sys.path:
    sys.path.insert(0, LIB)


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
