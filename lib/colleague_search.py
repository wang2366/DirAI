"""Keyword search over this tree's agents, for the Colleagues box (proposal 23, D1 "search only", D2
"this server only"). Uses dirai_card and the agent dicts of agent_list.find_agents(). Not wired into
agent_list.py / server.py / panel.js yet.

build_index(root, agents)  -> list of entries, one per local agent
search(index, query, exclude="", limit=10) -> [{"path", "title", "rank", "why"}]

Every word of the query must match somewhere in the entry. The best rank wins:
  1 a file name in the agent's folder   2 the agent's path or page title
  3 card Inputs / Outputs               4 other card fields or the page text
Rows of other servers (agents carrying "remote" or "machine") are never indexed.
"""
import json
import os
import re

import dirai_card
import dirai_config

INDEX_NAME = "colleague_index.json"     # in <root>/www, rewritten with the agent list
MAX_RESULTS = 10
FILE_DEPTH = 2            # folder levels below the agent whose file names are searched
TEXT_MAX = 200_000        # bytes of index.html read for the page text
KEEP_TEXT = 30_000        # characters of it kept in the index file
PRUNE = {".git", "node_modules", "__pycache__", ".claude", ".venv", "venv", "site-packages"}
TAG_RE = re.compile(r"<script.*?</script>|<style.*?</style>|<[^>]+>", re.I | re.S)
WHY = {1: "file", 2: "path or title", 3: "card Inputs/Outputs", 4: "card or page text"}


def is_remote(agent):
    return bool(agent.get("remote") or agent.get("machine"))


def file_names(folder):
    """File names under folder, down to FILE_DEPTH levels, as paths relative to it."""
    out, base = [], folder.rstrip(os.sep)
    for dirpath, dirnames, filenames in os.walk(folder):
        depth = dirpath[len(base):].count(os.sep)
        dirnames[:] = [] if depth + 1 >= FILE_DEPTH else sorted(d for d in dirnames if d not in PRUNE)
        out += [os.path.relpath(os.path.join(dirpath, n), folder) for n in filenames]
    return out


def page_text(folder):
    try:
        with open(os.path.join(folder, "index.html"), "rb") as f:
            raw = f.read(TEXT_MAX).decode("utf-8", "replace")
    except OSError:
        return ""
    return " ".join(TAG_RE.sub(" ", raw).split())[:KEEP_TEXT]


def build_index(root, agents):
    entries = []
    for a in agents:
        if is_remote(a):
            continue
        folder = os.path.join(root, a["dir"]) if a["dir"] else root
        try:
            card = dirai_card.extract(folder) or {}
        except OSError:
            continue
        entries.append({
            "path": a["dir"], "title": a.get("title", ""), "files": file_names(folder),
            "io": " ".join(card.get(k, "") for k in ("inputs", "outputs")),
            "card": " ".join(card.get(k, "") for k in ("objective", "result", "open")),
            "text": page_text(folder)})
    return entries + shared_entries(root)


def shared_entries(root):
    """The agents of connected shared repos (www/shares/<owner>/<repo>/agents/<slug>/), which the agent list's
    scan skips, so the Colleagues box finds them too (proposal 72). Path is relative to the tree, as a link
    to one would give it."""
    out, base = [], os.path.join(dirai_config.data_dir(root), "shares")
    try:
        owners = sorted(o for o in os.listdir(base) if not o.startswith("."))
    except OSError:
        return out
    for owner in owners:
        try:
            repos = sorted(os.listdir(os.path.join(base, owner)))
        except OSError:
            continue
        top_dirs = [(r, os.path.join(base, owner, r, "agents")) for r in repos]
        for repo, top in top_dirs:
            for d, dirs, names in os.walk(top):
                dirs[:] = sorted(n for n in dirs if not n.startswith("."))
                if d == top or "index.html" not in names:
                    continue
                try:
                    card = dirai_card.extract(d) or {}
                except OSError:
                    continue
                title = re.sub(r"\s+", " ", TAG_RE.sub("", (re.search(r"<h1[^>]*>(.*?)</h1>", page_text_raw(d), re.S | re.I) or [None, ""])[1])).strip()
                out.append({
                    "path": os.path.relpath(d, root).replace(os.sep, "/"), "title": title, "files": file_names(d),
                    "io": " ".join(card.get(k, "") for k in ("inputs", "outputs")),
                    "card": " ".join(card.get(k, "") for k in ("objective", "result", "open")),
                    "text": page_text(d)})
    return out


def page_text_raw(folder):
    try:
        with open(os.path.join(folder, "index.html"), "rb") as f:
            return f.read(TEXT_MAX).decode("utf-8", "replace")
    except OSError:
        return ""


def index_path(root):
    return os.path.join(root, "www", INDEX_NAME)


def save_index(root, index):
    dirai_config.save_json(index_path(root), index)


def load_index(root):
    return dirai_config.load_json(index_path(root), [])


def rank_of(entry, word):
    """Best rank at which word matches the entry, or None."""
    w = word.lower()
    for rank, hay in ((1, "\n".join(entry["files"])), (2, entry["path"] + "\n" + entry["title"]),
                      (3, entry["io"]), (4, entry["card"] + "\n" + entry["text"])):
        if w in hay.lower():
            return rank
    return None


def search(index, query, exclude=None, limit=MAX_RESULTS):
    words = query.split()
    if not words:
        return []
    hits = []
    for e in index:
        if e["path"] == exclude:
            continue
        ranks = [rank_of(e, w) for w in words]
        if None in ranks:
            continue
        hits.append((min(ranks), sum(ranks), e["path"], e))
    hits.sort(key=lambda h: h[:3])
    out = []
    for best, _, path, e in hits[:limit]:
        why = WHY[best]
        if best == 1:
            w = words[0].lower()
            f = next((f for f in e["files"] if w in f.lower()), None)
            why = "file: " + f if f else why
        out.append({"path": path, "title": e["title"], "rank": best, "why": why})
    return out
