#!/usr/bin/env python3
"""The summary card at the top of an agent's index.html (AGENT_RULE.md): six fields between two
markers, plus optional JSON results, so what an agent found can be read without the rest of it.

Usage: dirai_card.py FOLDER_OR_INDEX...   prints each index.html's card as short text

    <!-- dirai:card -->
    <details id="dirai-card" open>
      <summary>Summary</summary>
      <dl>
        <dt>Objective</dt> <dd>...</dd>   (and Inputs, Outputs, Result, Open, Updated: all required,
        ...                                "none" when nothing applies; Updated is YYYY-MM-DD)
      </dl>
      <script type="application/json" id="dirai-results">{...}</script>   (optional)
    </details>
    <!-- /dirai:card -->

agents.py checks the card after every run that changed index.html (problems()) and asks the
agent to fix it once if needed.
"""
import html
import json
import os
import re
import sys

FIELDS = ("Objective", "Inputs", "Outputs", "Result", "Open", "Updated")
BLOCK_RE = re.compile(r"<!--\s*dirai:card\s*-->(.*?)<!--\s*/dirai:card\s*-->", re.S | re.I)
PAIR_RE = re.compile(r"<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>", re.S | re.I)
RESULTS_RE = re.compile(r"<script[^>]*\bid=[\"']dirai-results[\"'][^>]*>(.*?)</script>", re.S | re.I)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def text(fragment):
    """Visible text of an HTML fragment, whitespace collapsed."""
    fragment = re.sub(r"(?i)<(?:br|/?p|/?li|/?div|/?ul|/?ol|/?tr|/?td)\b[^>]*>", " ", fragment)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", fragment)).split())


def parse(source):
    """(fields {name: text}, results JSON text or None) of the card in index.html source, or None if it has none."""
    m = BLOCK_RE.search(source)
    if not m:
        return None
    block = m.group(1)
    r = RESULTS_RE.search(block)
    fields = {}
    for dt, dd in PAIR_RE.findall(RESULTS_RE.sub("", block)):
        fields.setdefault(text(dt).rstrip(":").capitalize(), text(dd))
    return fields, (r.group(1).strip() if r else None)


def read(path):
    if os.path.isdir(path):
        path = os.path.join(path, "index.html")
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def extract(path):
    """The card as {"objective": ..., ..., "results": parsed JSON or None}, or None if no card."""
    card = parse(read(path))
    if card is None:
        return None
    fields, results = card
    out = {k.lower(): fields.get(k, "") for k in FIELDS}
    try:
        out["results"] = json.loads(results) if results else None
    except ValueError:
        out["results"] = None
    return out


def problems(path, today=None):
    """What's wrong with the card in index.html at path (empty list: nothing). today ("YYYY-MM-DD"):
    also require Updated to be that date, for an index.html a run has just changed."""
    try:
        card = parse(read(path))
    except OSError as e:
        return ["can't read index.html: %s" % e]
    if card is None:
        return ["index.html has no summary card"]
    fields, results = card
    out = ["%s is missing" % k if k not in fields else "%s is empty (write \"none\" if nothing applies)" % k
           for k in FIELDS if not fields.get(k)]
    updated = fields.get("Updated", "")
    if updated and not DATE_RE.match(updated):
        out.append("Updated is \"%s\", not a YYYY-MM-DD date" % updated)
    elif updated and today and updated != today:
        out.append("Updated is %s, but index.html changed today (%s)" % (updated, today))
    if results is not None:
        try:
            json.loads(results)
        except ValueError as e:
            out.append("the dirai-results JSON doesn't parse: %s" % e)
    return out


def main(paths):
    for i, path in enumerate(paths):
        print(("\n" if i else "") + "== %s" % path)
        try:
            card = extract(path)
        except OSError as e:
            print("(can't read: %s)" % e)
            continue
        if card is None:
            print("(no summary card)")
            continue
        for k in FIELDS:
            print("%s: %s" % (k, card[k.lower()] or "(empty)"))
        if card["results"] is not None:
            print("Results: %s" % json.dumps(card["results"]))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__.split("\n\n")[1])
    main(sys.argv[1:])
