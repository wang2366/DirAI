"""Where DirAI keeps things.

- The tool itself: one checkout, anywhere (e.g. ~/DirAI): bin/ (commands), lib/ (this Python),
  web/ (the browser side: page.css, the panel scripts), scripts/ (page_rm.sh, publish_pages.sh).
- Per tree (a git repo being served): <tree>/www/ holds the list page and state
  (index.html, reviews.json, page_sizes.json, page_tokens.json, server_host.txt, logs: all
  generated) and dirai.json, the tree's settings. dirai.json is local too (gitignored): two clones
  of one repo (e.g. home and scratch) need different ports, and it holds machine paths.
      {"port": 8765,                    # this tree's server port
       "read_dirs": ["/scratch/..."],   # extra folders page agents may read (the tree is always in)
       "allow": ["Bash(~/x/run.sh:*)"], # extra allow rules for page agents
       "slurm": ["-A", "grp", "-p", "cpu"],  # extra sbatch options for `DirAI start --job`
       "exclude": ["data", "proj/build"],    # folders the page list skips (names anywhere, or paths)
       "permissions": "allowlist"}           # or "ask" (set on the list page): see review.py
- Per user, never in a repo: ~/.config/dirai/ with the owner key (key), the "Always allow"
  grants (permissions.json), the list of trees DirAI has started (trees), and AGENT_RULE.md, a link to
  this checkout's AGENT_RULE.md that trees' CLAUDE.md import (`DirAI init|start` keep it current).
"""
import json
import os

LIB_DIR = os.path.dirname(os.path.abspath(__file__))
TOOL_DIR = os.path.dirname(LIB_DIR)                     # the checkout
WEB_DIR = os.path.join(TOOL_DIR, "web")
SCRIPTS_DIR = os.path.join(TOOL_DIR, "scripts")
CONFIG_DIR = os.path.expanduser(os.environ.get("DIRAI_CONFIG_DIR", "~/.config/dirai"))
CLAUDE_DIR = os.environ.get("CLAUDE_CONFIG_DIR", os.path.expanduser("~/.claude"))   # Claude Code's own
TRANSCRIPTS = os.path.join(CLAUDE_DIR, "projects")     # its session transcripts (*.jsonl)
KEY_FILE = os.path.join(CONFIG_DIR, "key")
PERMS_FILE = os.path.join(CONFIG_DIR, "permissions.json")
TREES_FILE = os.path.join(CONFIG_DIR, "trees")
DATA = "www"            # the data folder's name inside a tree (URLs: /www/index.html)
FIRST_PORT = 8765


def data_dir(root):
    return os.path.join(root, DATA)


def within(path, top):
    """True if path is top or inside it (both already resolved)."""
    return path == top or path.startswith(top + os.sep)


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data, **dump_args):
    """Write path atomically. The temporary file is per process, since several DirAI servers
    may write one shared file (~/.config/dirai) at once."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w") as f:
        json.dump(data, f, **dump_args)
        f.write("\n")
    os.replace(tmp, path)


def tree_config(root):
    """The tree's www/dirai.json merged over the defaults."""
    cfg = {"port": None, "read_dirs": [], "allow": [], "slurm": [], "exclude": [], "permissions": "allowlist"}
    try:
        with open(os.path.join(data_dir(root), "dirai.json")) as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    cfg["read_dirs"] = [os.path.expanduser(d) for d in cfg["read_dirs"]]
    return cfg


def set_tree_option(root, key, value):
    """Save one setting in the tree's www/dirai.json, keeping the others."""
    path = os.path.join(data_dir(root), "dirai.json")
    cfg = load_json(path, {})
    cfg[key] = value
    save_json(path, cfg, indent=1)
