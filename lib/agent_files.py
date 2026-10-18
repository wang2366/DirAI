"""The files of an agent's folder, which server.py shows the owner at the end of its index.html: the
text files raw (collapsed, with line numbers), and the names of the rest and of its subfolders.
"""
import os
import re

from dirai_config import within

FILE_MAX = 1 << 20      # bytes; a bigger file is listed, not shown
TOTAL_MAX = 4 << 20     # bytes shown per agent in all; files after that are listed, not shown
SHOW_MAX = 30           # files shown per agent
LIST_MAX = 100          # names of files not shown, and of subfolders, per agent
SEL_KEY = 30            # characters (markdown and whitespace removed) that find a selection's start/end
MD_SKIP_RE = re.compile(r"[\s*_`#>\[\]()!~|=-]")   # markdown the rendered text doesn't show
NOT_SHOWN = {"index.html"}
IMAGES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp", ".tif", ".tiff", ".pdf")


def text_of(path):
    """The file's text, or None if it looks binary (a NUL byte in its first 8 KB)."""
    with open(path, "rb") as f:
        data = f.read(FILE_MAX + 1)
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", "replace")


def file_path(agent_dir, name):
    """The path of the file called name directly in agent_dir that folder_files() shows, or None
    (anything but a plain visible file name, index.html, an image, a link out of the folder)."""
    if not isinstance(name, str) or not name or name.startswith(".") or "/" in name or "\\" in name:
        return None
    if name in NOT_SHOWN or name.lower().endswith(IMAGES):
        return None
    path = os.path.join(agent_dir, name)
    real = os.path.realpath(path)
    if not os.path.isfile(real) or not within(real, os.path.realpath(agent_dir)):
        return None
    return path


def folder_files(agent_dir):
    """What the agent's folder holds, by name: {"files": [{"name", "size", "mtime", "text"}] shown,
    "other": [{"name", "size", "why"}] not shown, "dirs": [{"name", "agent"}] its subfolders (agent:
    holding an index.html of its own), "more": how many names were left out of other and dirs}."""
    out = {"files": [], "other": [], "dirs": [], "more": 0}
    try:
        names = sorted(n for n in os.listdir(agent_dir) if not n.startswith("."))
    except OSError:
        return out
    total = 0
    for name in names:
        full = os.path.join(agent_dir, name)
        if os.path.isdir(full):
            if len(out["dirs"]) < LIST_MAX:
                out["dirs"].append({"name": name, "agent": os.path.isfile(os.path.join(full, "index.html"))})
            else:
                out["more"] += 1
            continue
        if name in NOT_SHOWN:
            continue
        path = file_path(agent_dir, name)
        why = None
        try:
            st = os.stat(full)
        except OSError:
            continue
        if path is None:
            why = "image" if name.lower().endswith(IMAGES) else "not in this folder"
        elif st.st_size > FILE_MAX:
            why = "over %d MB" % (FILE_MAX >> 20)
        elif len(out["files"]) >= SHOW_MAX or total + st.st_size > TOTAL_MAX:
            why = "too many to show"
        else:
            try:
                text = text_of(path)
            except OSError:
                continue
            if text is None:
                why = "binary"
            else:
                out["files"].append({"name": name, "size": st.st_size, "mtime": st.st_mtime, "text": text})
                total += st.st_size
                continue
        if len(out["other"]) < LIST_MAX:
            out["other"].append({"name": name, "size": st.st_size, "why": why})
        else:
            out["more"] += 1
    return out


def selected_lines(path, lines):
    """(first, last) of the lines the owner selected in the file at path (the browser reports them),
    kept within the file; None if lines isn't two line numbers."""
    try:
        a, b = (int(x) for x in lines)
        with open(path, encoding="utf-8", errors="replace") as f:
            n = f.read().count("\n") + 1
    except (TypeError, ValueError, OSError):
        return None
    a, b = sorted((max(1, min(a, n)), max(1, min(b, n))))
    return a, b


def rendered_lines(path, block, text):
    """(first, last) source lines of text selected in a rendered .md at path. block: the (first, last)
    lines of the rendered blocks the selection spans, as the browser reports them; narrowed to the
    lines holding the selection's start and end when they can be found there, else block itself."""
    block = selected_lines(path, block)
    if block is None:
        return None
    a, b = block
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().split("\n")
    chars, where = [], []
    for n in range(a, b + 1):
        for c in MD_SKIP_RE.sub("", lines[n - 1]):
            chars.append(c)
            where.append(n)
    src, sel = "".join(chars), MD_SKIP_RE.sub("", text)
    head, tail = sel[:SEL_KEY], sel[-SEL_KEY:]
    i = src.find(head) if head else -1
    if i < 0:
        return a, b
    j = src.find(tail, i)
    return (where[i], b) if j < 0 else (where[i], where[j + len(tail) - 1])
