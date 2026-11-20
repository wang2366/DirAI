"""An agent's colleagues: other agents of the tree it may read (or edit, see MODES), which the owner adds in
its panel by pasting a link to one. agents.py keeps the list (st["colleagues"], paths relative to
the tree, "" for the tree's top agent), lets each run read them and puts their summary cards in
its instructions (prompt_block()); server.py adds a Colleagues row linking them to the agent's
card when it serves its index.html (card_row(), add_card_row()), so the file itself never has it.
"""
import html
import json
import os
import re
import time
from urllib.parse import quote, unquote, urlparse

import dirai_card
from dirai_config import within

PROMPT_MAX = 8        # colleagues whose cards go in a run's instructions
FIELD_MAX = 300       # characters of each card field there
CARD_END_RE = re.compile(rb"<!--\s*/dirai:card\s*-->", re.I)
# What the agent may do in a colleague's folder (st["coll_mode"][rel]; missing = "read"), cycled by a
# click on its chip: read it; "own": also edit its own files, not the folders of agents inside it;
# "all": edit all of it. A colleague with no agents inside goes read -> own -> read.
MODES = ("read", "own", "all")
PRUNE = {".git", "node_modules", "__pycache__", ".claude", ".venv", "venv", "site-packages"}
MODE_SAYS = {"read": "read-only", "own": "may edit its own files, not the folders of the agents inside it",
             "all": "may edit everything in its folder"}


def folder(root, rel):
    return os.path.join(root, rel) if rel else root


def nested_agents(root, rel, agent_dir=None):
    """The folders of the agents inside a colleague's folder (the outermost ones; an agent's own
    agents are inside its folder anyway). agent_dir, the agent's own folder, is never one, nor is
    a folder holding it: their other agents inside are listed instead. A walk: once per run."""
    base, out = folder(root, rel), []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in PRUNE and not (
            d == "www" and os.path.isfile(os.path.join(dirpath, d, "dirai.json"))))
        if dirpath == base or "index.html" not in filenames:
            continue
        if agent_dir and dirpath == agent_dir:
            dirnames[:] = []
        elif not (agent_dir and within(agent_dir, dirpath)):
            out.append(dirpath)
            dirnames[:] = []
    return out


_has_nested = {}      # folder -> (time, bool), so the panel's polls don't walk the tree each time
NESTED_TTL_S = 60


def has_nested(root, rel):
    base = folder(root, rel)
    t, yes = _has_nested.get(base, (0, False))
    if time.time() - t > NESTED_TTL_S:
        yes = bool(nested_agents(root, rel))
        _has_nested[base] = (time.time(), yes)
    return yes


def next_mode(root, rel, mode):
    """The state a click on the chip moves to: read -> own -> all -> read; own -> read for a
    colleague with no agents inside (own is all of it already)."""
    if mode == "read":
        return "own"
    if mode == "own" and has_nested(root, rel):
        return "all"
    return "read"


def parse_link(link, root, agent):
    """(path relative to root, None) of the agent a pasted link names, or (None, why not). A link is
    a page's URL as the browser shows it (any host and port: a tunnel or another port works too),
    its /path/index.html, an absolute folder or file path, or a path relative to the tree."""
    link = link.strip()
    if not link:
        return None, "Paste a link to the other agent's page."
    url = urlparse(link)
    if url.scheme in ("http", "https"):
        full = os.path.join(root, unquote(url.path).lstrip("/"))
    else:
        path = os.path.expanduser(unquote(link.split("#", 1)[0].split("?", 1)[0]))
        # "/a/b": a page path like /a/b/index.html, unless only a path on disk by that name exists
        full = os.path.join(root, path.lstrip("/"))
        if path.startswith("/") and os.path.exists(path) and not os.path.exists(full):
            full = path
    full = os.path.realpath(full)
    if os.path.basename(full).lower() in ("index.html", "index.htm") or os.path.isfile(full):
        full = os.path.dirname(full)
    if not within(full, root):
        return None, "That link isn't inside this tree (%s)." % root
    if not os.path.isfile(os.path.join(full, "index.html")):
        return None, "No agent there: %s has no index.html." % full
    rel = "" if full == root else os.path.relpath(full, root)
    if rel == agent:
        return None, "That is this agent itself."
    if rel == "www":
        return None, "That is the agent list, not an agent."
    return rel, None


def href(rel):
    """The colleague's page, root-relative so the link works on any host and port."""
    return "/" + (quote(rel) + "/" if rel else "") + "index.html"


def info(root, rels, modes=None):
    """For the panel: [{"path", "url", "gone", "mode", "next"}] (gone: its folder or index.html is no
    longer there; mode: read, own or all; next: the state a click on its chip moves to)."""
    modes, out = modes or {}, []
    for rel in rels:
        mode = modes.get(rel, "read")
        out.append({"path": rel, "url": href(rel), "mode": mode, "next": next_mode(root, rel, mode),
                    "gone": not os.path.isfile(os.path.join(folder(root, rel), "index.html"))})
    return out


def cut(text, limit=FIELD_MAX):
    return text if len(text) <= limit else text[:limit] + "..."


def prompt_block(root, rels, card_py, modes=None):
    """The part of a run's instructions about its colleagues and what their cards say ("" if none).
    A writable one (modes[rel] own or all) says so first: every one stays in the block."""
    modes = modes or {}
    rels = sorted(rels, key=lambda r: modes.get(r, "read") == "read")
    lines = []
    for i, rel in enumerate(rels):
        mode = modes.get(rel, "read")
        if i >= PROMPT_MAX and mode == "read":
            break
        d = folder(root, rel)
        try:
            card = dirai_card.extract(d)
        except OSError:
            continue        # gone: the panel shows it struck through
        says = "" if mode == "read" else "%s; don't delete there, and list what you changed in your reply. " % MODE_SAYS[mode]
        if card is None:
            lines.append("- %s: %sno summary card; read its index.html" % (d, says))
            continue
        lines.append("- %s: %sObjective: %s | Result: %s | Open: %s | Updated: %s" % (
            d, says, cut(card["objective"]), cut(card["result"]), cut(card["open"]), card["updated"]))
        if card["results"] is not None:
            lines.append("  results: " + cut(json.dumps(card["results"]), 2 * FIELD_MAX))
    if not lines:
        return ""
    more = len(rels) - max(PROMPT_MAX, sum(modes.get(r, "read") != "read" for r in rels))
    return ("\n\nYour colleagues: other agents of this tree the owner lets you read, read-only (never write "
            "to their folders) unless the line says what you may edit. Their summary cards, as of this run, follow; for more, run "
            "\"python3 %s <folder>\" or read their index.html.\n%s%s" % (
                card_py, "\n".join(lines),
                "\n(%d more colleague%s not shown)" % (more, "" if more == 1 else "s") if more > 0 else ""))


def card_row(root, rels, modes=None):
    """The Colleagues <dt>/<dd> pair for the agent's card: a link to each colleague with its
    Updated date and whether its card is complete (✓/✗), ✎ before a writable one (✎✎: all of
    it); a gone one struck through."""
    modes, items = modes or {}, []
    for rel in rels:
        mode = modes.get(rel, "read")
        mark = {"own": '<span title="May edit its own files">✎</span> ',
                "all": '<span title="May edit everything in its folder">✎✎</span> '}.get(mode, "")
        d = folder(root, rel)
        name = html.escape(os.path.basename(d) or rel)
        try:
            card = dirai_card.extract(d)
        except OSError:
            items.append('<s title="%s is gone">%s</s>' % (html.escape(d), name))
            continue
        bad = dirai_card.problems(d)
        state = ("%s %s" % (card["updated"] or "?", "✗" if bad else "✓")) if card else "no card ✗"
        title = "Summary card: " + "; ".join(bad) if bad else rel or "the tree's top agent"
        items.append('%s<a href="%s" title="%s">%s</a> (%s)' % (mark, href(rel), html.escape(title), name, state))
    return ('<dt class="dirai-colls">Colleagues</dt> <dd class="dirai-colls">%s</dd>\n'
            % " · ".join(items)) if items else ""


def add_card_row(page, row):
    """page (index.html bytes) with row put at the end of its card's <dl>; unchanged if it has no card."""
    m = CARD_END_RE.search(page)
    if not row or not m:
        return page
    i = page.lower().rfind(b"</dl>", 0, m.start())
    start = page.lower().rfind(b"dirai:card", 0, m.start())
    if i < 0 or i < start:
        return page
    return page[:i] + row.encode() + page[i:]
