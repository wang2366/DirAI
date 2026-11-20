"""Files the owner drops on an agent's chat panel: saved in the agent's folder under PASTED/, where the
agent may read them without a grant, and named in the message that goes with them (web/panel.js).
PASTED/ is git-ignored (bin/DirAI ignore_generated).
"""
import base64
import binascii
import os
import re
import time

PASTED = "pasted"
FILE_MAX = 20 << 20     # bytes per file
NAME_MAX = 80           # characters kept of the file's own name
UNSAFE_RE = re.compile(r"[^A-Za-z0-9._+-]+")
# a file with one of these names must start like one (so a renamed file can't pass as an image or PDF)
MAGIC = {".png": (b"\x89PNG\r\n\x1a\n",), ".jpg": (b"\xff\xd8\xff",), ".jpeg": (b"\xff\xd8\xff",),
         ".gif": (b"GIF87a", b"GIF89a"), ".webp": (b"RIFF",), ".pdf": (b"%PDF-",)}
# served as a page (and an index.html would make PASTED/ an agent of its own): kept as text
AS_TEXT = (".html", ".htm")


def clean_name(name):
    """The file's name, safe in a path: its last part, odd characters as "_", no leading dot,
    at most NAME_MAX characters (its extension kept); .html/.htm get ".txt" added."""
    base = UNSAFE_RE.sub("_", os.path.basename(str(name or "").replace("\\", "/"))).lstrip("._") or "file"
    stem, ext = os.path.splitext(base)
    base = stem[:max(1, NAME_MAX - len(ext))] + ext[:NAME_MAX // 2]
    return base + ".txt" if base.lower().endswith(AS_TEXT) else base


def save(agent_dir, name, data):
    """Save one dropped file (data: its bytes in base64) in agent_dir/PASTED/ as
    YYMMDD_HHMMSS_<name> (_2, _3 … if taken): its path relative to agent_dir. ValueError: why not."""
    try:
        raw = base64.b64decode(str(data or ""), validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("The file didn't arrive whole; drop it again.")
    if not raw:
        raise ValueError("The file is empty.")
    if len(raw) > FILE_MAX:
        raise ValueError("The file is over %d MB." % (FILE_MAX >> 20))
    base = clean_name(name)
    ext = os.path.splitext(base)[1].lower()
    if ext in MAGIC and not raw.startswith(MAGIC[ext]):
        raise ValueError("%s isn't a %s file inside." % (base, ext[1:].upper()))
    folder = os.path.join(agent_dir, PASTED)
    os.makedirs(folder, exist_ok=True)
    stem, ext = os.path.splitext(time.strftime("%y%m%d_%H%M%S_") + base)
    for n in range(1, 1000):
        out = stem + ("_%d" % n if n > 1 else "") + ext
        try:
            with open(os.path.join(folder, out), "xb") as f:   # x: never over a file already there
                f.write(raw)
            return PASTED + "/" + out
        except FileExistsError:
            continue
    raise ValueError("Too many files called %s this second." % base)
