"""The files of an agent's folder, which server.py shows the owner at the end of its index.html: the
text files raw (collapsed, with line numbers), and the names of the rest and of its subfolders.
"""
import os
import re

from dirai_config import within

FILE_MAX = 1 << 20      # bytes; a bigger file is listed, not shown
TOTAL_MAX = 4 << 20     # bytes shown per agent in all; files after that are listed, not shown
SHOW_MAX = 30           # files shown per agent
LIST_MAX = 100          # names of files not shown, and of subfolders, per folder
COUNT_MAX = 200         # entries counted in a closed subfolder ("200+ items"); one level, no walk
DIR_MAX = 500          # names listed per folder in the Tree tab's Show files mode
SEL_KEY = 30            # characters (markdown and whitespace removed) that find a selection's start/end
MD_SKIP_RE = re.compile(r"[\s*_`#>\[\]()!~|=-]")   # markdown the rendered text doesn't show
NOT_SHOWN = {"index.html"}
SCRATCH = "tmp"         # the agent's scratch folder (patches, one-off scripts): not shown, like dot-names
IMAGES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp", ".tif", ".tiff", ".pdf")


def text_of(path):
    """The file's text, or None if it looks binary (a NUL byte in its first 8 KB)."""
    with open(path, "rb") as f:
        data = f.read(FILE_MAX + 1)
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", "replace")


def sub_dir(agent_dir, sub):
    """The folder sub (a relative path like "rerun/nemo5"; "" is agent_dir itself) of the agent's folder,
    or None: a hidden or ".." part, the scratch folder tmp/, a part that isn't a folder, a child agent's
    folder (one holding an index.html of its own: its files are not this page's), or a link out of the
    agent's folder."""
    if not isinstance(sub, str):
        return None
    base = os.path.realpath(agent_dir)
    cur = agent_dir
    for i, part in enumerate(sub.split("/") if sub else []):
        if not part or part.startswith(".") or "\\" in part or (i == 0 and part == SCRATCH):
            return None
        cur = os.path.join(cur, part)
        if not os.path.isdir(cur) or os.path.isfile(os.path.join(cur, "index.html")):
            return None
        if not within(os.path.realpath(cur), base):
            return None
    return cur


def file_path(agent_dir, name, any_type=False):
    """The path of the file called name (a plain name, or a relative path like "rerun/fit.py") in
    agent_dir that folder_files() shows, or None (a hidden or ".." part, index.html, an image, a path
    through a child agent, a link out of the folder). any_type: every file the Files section lists,
    images and binaries too (the ⤓ download)."""
    if not isinstance(name, str) or not name:
        return None
    folder, _, base = name.rpartition("/")
    if not base or base.startswith(".") or "\\" in base:
        return None
    if not any_type and (base in NOT_SHOWN or base.lower().endswith(IMAGES)):
        return None
    where = sub_dir(agent_dir, folder)
    if where is None:
        return None
    path = os.path.join(where, base)
    real = os.path.realpath(path)
    if not os.path.isfile(real) or not within(real, os.path.realpath(agent_dir)):
        return None
    return path


def zip_members(agent_dir, sub=""):
    """(path, name in the zip) of every file in the folder sub of the agent's folder and below, for its
    ⤓ .zip: what the Files section can reach. Skips hidden names, the scratch folder tmp/ (at the top),
    child agents' folders, and links (to folders or files) out of the agent's folder; links to folders
    are not followed at all (no loops). None if sub isn't a folder to show (sub_dir())."""
    top = sub_dir(agent_dir, sub)
    if top is None:
        return None
    base = os.path.realpath(agent_dir)
    out = []
    for cur, dirs, files in os.walk(top):
        rel = os.path.relpath(cur, top)
        rel = "" if rel == "." else rel.replace(os.sep, "/") + "/"
        dirs[:] = [d for d in sorted(dirs)
                   if not (d.startswith(".") or (cur == agent_dir and d == SCRATCH)
                           or os.path.islink(os.path.join(cur, d))
                           or os.path.isfile(os.path.join(cur, d, "index.html")))]
        for f in sorted(files):
            full = os.path.join(cur, f)
            if f.startswith(".") or not os.path.isfile(full) or not within(os.path.realpath(full), base):
                continue
            out.append((full, rel + f))
    return out


def count_of(path):
    """What a closed subfolder holds, cheaply: {"files", "dirs", "capped"} over its first COUNT_MAX
    visible entries (capped: there are more). One level, never a walk."""
    out = {"files": 0, "dirs": 0, "capped": False}
    try:
        with os.scandir(path) as it:
            for e in it:
                if e.name.startswith("."):
                    continue
                if out["files"] + out["dirs"] >= COUNT_MAX:
                    out["capped"] = True
                    break
                out["dirs" if e.is_dir() else "files"] += 1
    except OSError:
        pass
    return out


def folder_files(agent_dir, sub=""):
    """What the folder sub of the agent's folder holds ("" is the agent's folder itself), by name:
    {"files": [{"name", "size", "mtime", "text"}] shown, "other": [{"name", "size", "why"}] not shown,
    "dirs": [{"name", "agent", "out", "count"}] its subfolders (agent: holding an index.html of its own;
    out: a link out of the agent's folder, named and not followed; count: count_of() for the others),
    "more": how many names were left out of other and dirs}. None if sub isn't a folder to show."""
    root, agent_dir = agent_dir, sub_dir(agent_dir, sub)
    if agent_dir is None:
        return None
    base = os.path.realpath(root)
    prefix = sub + "/" if sub else ""
    out = {"files": [], "other": [], "dirs": [], "more": 0}
    try:
        names = sorted(n for n in os.listdir(agent_dir) if not n.startswith(".") and not (n == SCRATCH and not sub))
    except OSError:
        return out
    total = 0
    for name in names:
        full = os.path.join(agent_dir, name)
        if os.path.isdir(full):
            if len(out["dirs"]) < LIST_MAX:
                agent = os.path.isfile(os.path.join(full, "index.html"))
                link_out = not within(os.path.realpath(full), base)
                d = {"name": name, "agent": agent, "out": link_out}
                if not agent and not link_out:
                    d["count"] = count_of(full)
                out["dirs"].append(d)
            else:
                out["more"] += 1
            continue
        if name in NOT_SHOWN:
            continue
        path = file_path(root, prefix + name)
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


def dir_listing(root, rel):
    """The folder rel (like "a/b"; "" is root itself) of the tree at root, by name only, nothing read:
    {"dirs": [{"name", "agent": holds an index.html, "out": a link out of root, named and not followed}],
    "files": [{"name", "size"}], "more": names left out}. None: a hidden or ".." part, a part that isn't a
    folder, or a link out of root. Hidden names (.git, .env) are not listed."""
    if not isinstance(rel, str):
        return None
    base = os.path.realpath(root)
    cur = root
    for part in (rel.split("/") if rel else []):
        if not part or part.startswith(".") or "\\" in part:
            return None
        cur = os.path.join(cur, part)
        if not os.path.isdir(cur) or not within(os.path.realpath(cur), base):
            return None
    out = {"dirs": [], "files": [], "more": 0}
    try:
        names = sorted(n for n in os.listdir(cur) if not n.startswith("."))
    except OSError:
        return out
    for name in names:
        full = os.path.join(cur, name)
        if len(out["dirs"]) + len(out["files"]) >= DIR_MAX:
            out["more"] += 1
        elif os.path.isdir(full):
            link_out = not within(os.path.realpath(full), base)
            out["dirs"].append({"name": name, "agent": os.path.isfile(os.path.join(full, "index.html")), "out": link_out})
        else:
            try:
                out["files"].append({"name": name, "size": os.stat(full).st_size})
            except OSError:
                pass
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
