"""Per-block Undo / Redo of an agent run's changes to its index.html, for agents.py and server.py.

A run that changes index.html leaves two copies in www/: before_run/ (the page before the run)
and after_run/ (the page as the run left it). Their line diff splits the run's edit into numbered
blocks; the page is always the run's copy with the owner's undone blocks (st["undone"]) put back
as they were before. If the page no longer matches that (edited since by hand), per-block undo
is refused rather than guessing.

The owner's copy of the page gets an empty <template data-dirai-block="N"> where each block starts,
so the panel can put that block's Undo or Redo button there (panel.js).
"""
import difflib
import html.parser
import os

ENC = dict(encoding="utf-8", errors="surrogateescape")   # any bytes survive the round trip


def read(path):
    try:
        with open(path, **ENC) as f:
            return f.read()
    except OSError:
        return None


def write(path, text):
    tmp = path + ".undo"
    with open(tmp, "w", newline="", **ENC) as f:
        f.write(text)
    os.replace(tmp, path)


def blocks(before, after):
    """The run's changed blocks: (i1, i2, j1, j2) line ranges, before[i1:i2] -> after[j1:j2]."""
    a, b = before.splitlines(True), after.splitlines(True)
    ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    return a, b, [(i1, i2, j1, j2) for tag, i1, i2, j1, j2 in ops if tag != "equal"]


def build(before, after, undone):
    """The page with the blocks in undone put back as they were: (text, [(start, end) line range of
    each block in it])."""
    a, b, bl = blocks(before, after)
    out, spans, j = [], [], 0
    for k, (i1, i2, j1, j2) in enumerate(bl):
        out += b[j:j1]
        start = len(out)
        out += a[i1:i2] if k in undone else b[j1:j2]
        spans.append((start, len(out)))
        j = j2
    out += b[j:]
    return "".join(out), spans


def state(index, before_path, after_path, undone):
    """(before, after, spans) when index.html is the run's copy with the undone blocks put back,
    else None. A tree whose run predates after_run/ has none: the page as it is now is the run's copy."""
    before, page = read(before_path), read(index)
    if before is None or page is None:
        return None
    after = read(after_path)
    if after is None:
        if undone:
            return None
        write(after_path, page)
        after = page
    text, spans = build(before, after, set(undone))
    return (before, after, spans) if text == page else None


def toggle(index, before_path, after_path, undone, block):
    """Undo block (or redo it, if it is in undone): writes index.html and returns the new undone
    list, or an error message."""
    st = state(index, before_path, after_path, undone)
    if st is None:
        return "index.html was changed after the agent's latest run (by hand?), so its blocks can't be undone one by one."
    before, after, spans = st
    if not 0 <= block < len(spans):
        return "No such change."
    undone = set(undone) ^ {block}
    write(index, build(before, after, undone)[0])
    return sorted(undone)


class _Spots(html.parser.HTMLParser):
    """Offsets where an element may go: the start of each tag, comment or text, except inside
    <script>, <style>, <textarea> and <title> (their text and end tag)."""
    RAW = ("script", "style", "textarea", "title")

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.spots, self.raw = [], None

    def at(self):
        self.spots.append(self.getpos())

    def handle_starttag(self, tag, attrs):
        self.at()
        if tag in self.RAW:
            self.raw = tag

    def handle_startendtag(self, tag, attrs):
        self.at()

    def handle_endtag(self, tag):
        if tag == self.raw:   # (just before it is still inside the script)
            self.raw = None
        else:
            self.at()

    def handle_data(self, data):
        if not self.raw:
            self.at()

    handle_comment = handle_entityref = handle_charref = lambda self, *a: self.at()


def mark(page, spans, undone):
    """page with <template data-dirai-block="N" [data-undone]> where each block starts (the first
    spot in its lines; the next one after them for a block with none, e.g. one that is only removed lines)."""
    p = _Spots()
    try:
        p.feed(page)
        p.close()
    except Exception:   # malformed HTML: no buttons rather than a broken page
        return page
    starts = [0]
    for line in page.splitlines(True):
        starts.append(starts[-1] + len(line))
    spots = sorted(starts[ln - 1] + col for ln, col in p.spots)
    marks = {}
    for k, (s, e) in enumerate(spans):
        lo, hi = starts[min(s, len(starts) - 1)], starts[min(e, len(starts) - 1)]
        found = [x for x in spots if lo <= x < hi] or [x for x in spots if x >= lo]
        if found:
            marks.setdefault(found[0], []).append(
                '<template data-dirai-block="%d"%s></template>' % (k, " data-undone" if k in undone else ""))
    for x in sorted(marks, reverse=True):
        page = page[:x] + "".join(marks[x]) + page[x:]
    return page
