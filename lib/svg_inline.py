"""Diagrams inline, so their text can be selected, searched and quoted (improvement 67).

The server sends index.html with each <img src="x.svg"> of a local SVG replaced by the file's
<svg>...</svg> (expand()); index.html on disk keeps the short <img> line. An SVG stays an <img> when it
is over LIMIT, outside the tree, or has something that would act on the whole page: <script>, an
on...= handler, <foreignObject>, <iframe>, an <image> of a file or URL (one holding its own PNG/JPEG
as data:, as matplotlib's heatmaps do, is fine), or a <style> of its own (matplotlib's one
two-property block is fine: it becomes attributes).

for_page(svg, prefix) makes the file's text fit for a page, in three steps: strip_header() (no XML
prolog, DOCTYPE or comments), mpl_style_to_attrs() (matplotlib's <style> as attributes) and prefix_ids()
(every id prefixed, with url(#id) / href="#id" rewritten, so two diagrams on one page can't clash).

inline_one() (server.py's /_dirai/svg, web/svg_watch.js): the same for an <img src="x.svg"> that a page's
own script adds in the browser, which expand() never sees (a viewer that builds its figures from JSON).

snapshot() / changed() (agents.py): the SVGs a page shows, copied at run start, so the panel's change
marks compare a redrawn diagram with its drawing from before the run (expand(..., snapshot=)).
"""
import filecmp
import os
import re
import shutil

LIMIT = 300 * 1024          # bigger SVGs (dense scatters) stay <img>; counted without embedded rasters
FILE_LIMIT = 3 * 1024 * 1024   # (a heatmap's PNG data is bytes the browser fetches either way, not page elements)
# matplotlib's one block, in either order, with or without spaces (3.3 writes
# "*{stroke-linecap:butt;stroke-linejoin:round;}", others "*{stroke-linejoin: round; stroke-linecap: butt}")
_DECL = r"\s*stroke-line(?:join:\s*round|cap:\s*butt)\s*;?"
MPL_STYLE = re.compile(r"<style[^>]*>\s*\*\s*\{(?:%s){2}\s*\}\s*</style>" % _DECL, re.S | re.I)
UNSAFE = re.compile(r"<(script|style|image|foreignObject|iframe)[\s>/]|<[a-z][^<>]*\son\w+\s*=", re.I)   # on…= only inside a tag
# an <image> holding its own raster (matplotlib's heatmaps, imshow, colorbars) loads nothing and runs nothing: fine
DATA_IMAGE = re.compile(r'<image\b[^<>]*?\s(?:xlink:)?href\s*=\s*"data:image/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/=\s]*"[^<>]*>', re.I)


def _rasters_out(svg):
    """svg without the data: of its embedded rasters: its size is what the page's elements cost."""
    return DATA_IMAGE.sub("<image/>", svg)


def _safe_images_out(svg):
    return DATA_IMAGE.sub(lambda m: m.group(0) if re.search(r"\son\w+\s*=", m.group(0), re.I) else "", svg)
IMG = re.compile(r"<img\b[^>]*>", re.I)


def attr(tag, name):
    m = re.search(r'\s%s\s*=\s*("([^"]*)"|\'([^\']*)\'|([^\s>]+))' % name, tag, re.I)
    return None if not m else next(g for g in m.groups()[1:] if g is not None)


def strip_header(svg):
    """The file's XML prolog, DOCTYPE and comments removed: they mean nothing inside a page."""
    return re.sub(r"<\?xml.*?\?>|<!DOCTYPE.*?>|<!--.*?-->", "", svg, flags=re.S).strip()


def mpl_style_to_attrs(svg):
    """matplotlib's one <style> block as attributes on <svg>: a <style> in the page would switch off index.css."""
    if not MPL_STYLE.search(svg):
        return svg
    svg = MPL_STYLE.sub("", svg)
    return re.sub(r"<svg\b", '<svg stroke-linejoin="round" stroke-linecap="butt"', svg, count=1)


def prefix_ids(svg, prefix):
    """Every id="x" made "PREFIX-x", with each url(#x) / href="#x" to it, so two diagrams on one page can't
    share an id (and take each other's clip paths or arrowheads). One pass over the text: a pass per id
    grew with size squared (4.5 s for a 306 kB map)."""
    ids = set(re.findall(r'\sid="([^"]+)"', svg))
    if not ids:
        return svg

    def ref(m):
        return m.group(1) + ("%s-%s" % (prefix, m.group(2)) if m.group(2) in ids else m.group(2)) + m.group(3)
    return re.sub(r'(\sid="|url\(#|(?:xlink:)?href="#)([^")]+)("|\))', ref, svg)


def for_page(svg, prefix):
    """An SVG file's text made fit to sit inside a page: the three steps above."""
    return prefix_ids(mpl_style_to_attrs(strip_header(svg)), prefix)


def _local(src, folder, root):
    """The real path of a local .svg <img src> inside root, or None."""
    if not src or not src.lower().endswith(".svg") or re.match(r"[a-z][a-z0-9+.-]*:|/", src, re.I):
        return None
    path = os.path.realpath(os.path.join(folder, src))
    if not path.startswith(os.path.realpath(root) + os.sep) or not os.path.isfile(path):
        return None
    return path


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def load(src, folder, root, snapshot=None):
    """(svg text, None) for an inlinable <img src>, else (None, why it stays <img>)."""
    path = _local(src, folder, root)
    if path is None:
        return None, "not a local .svg in the tree"
    if snapshot:   # the copy from before the latest run, if there is one
        rel = os.path.relpath(path, os.path.realpath(folder))
        old = os.path.join(snapshot, rel)
        if not rel.startswith("..") and os.path.isfile(old):
            path = old
    try:
        if os.path.getsize(path) > FILE_LIMIT:
            return None, "over %d MB" % (FILE_LIMIT // 1024 // 1024)
        svg = _read(path)
    except OSError:
        return None, "unreadable"
    if len(_rasters_out(svg)) > LIMIT:
        return None, "over %d kB" % (LIMIT // 1024)
    m = UNSAFE.search(_safe_images_out(MPL_STYLE.sub("", svg)))
    if m:
        return None, "has %s" % ("<" + m.group(1) if m.group(1) else "an on…= handler")
    if not re.search(r"<svg\b[^>]*>", svg):
        return None, "no <svg>"
    return svg, None


def expand(html, folder, root, report=None, snapshot=None, id_prefix=""):
    """html (str) with its local SVG <img>s inlined; report, if a list, gets (src, why) for each skipped.
    snapshot: a folder of SVG copies from before the latest run (snapshot()); a file found there is
    used instead, so /_review/prev shows the old drawing and the panel marks the redrawn one.
    id_prefix: put before each diagram's id prefix (inline_one(): "js3-" keeps a script's figures apart)."""
    seen = {}

    def one(m):
        tag = m.group(0)
        src = attr(tag, "src")
        svg, why = load(src, folder, root, snapshot)
        if svg is None:
            if report is not None and src and src.lower().endswith(".svg"):
                report.append((src, why))
            return tag
        stem = re.sub(r"\W", "_", os.path.splitext(os.path.basename(src))[0])
        seen[stem] = seen.get(stem, 0) + 1
        prefix = id_prefix + (stem if seen[stem] == 1 else "%s%d" % (stem, seen[stem]))
        svg = for_page(svg, prefix)
        add = {"data-dirai-src": src}   # panel.js: a selection inside it quotes x.svg, not index.html
        alt, width = attr(tag, "alt"), attr(tag, "width")
        if alt:
            add.update({"role": "img", "aria-label": alt})
        drop = set(add)
        if width:       # the <img>'s width wins; height follows from the viewBox (index.css: height auto)
            add["width"] = width
            drop |= {"width", "height"}
        m = re.search(r"<svg\b([^>]*?)(/?)>", svg)
        kept = re.sub(r'\s(%s)\s*=\s*("[^"]*"|\'[^\']*\')' % "|".join(map(re.escape, drop)), "", m.group(1))
        new = "<svg%s%s%s>" % (kept, "".join(' %s="%s"' % (k, v.replace("&", "&amp;").replace('"', "&quot;"))
                                             for k, v in add.items()), m.group(2))
        return svg[:m.start()] + new + svg[m.end():]

    return IMG.sub(one, html)


def inline_one(src, folder, root, id_prefix):
    """The <svg> expand() puts for <img src=src> on a page in folder, or None if it stays a picture.
    For figures a page's own script adds after it arrives (/_dirai/svg, web/svg_watch.js)."""
    if not src or re.search(r"[\"'<>&]", src):
        return None
    out = expand('<img src="%s">' % src, folder, root, id_prefix=id_prefix)
    return out if out.startswith("<svg") else None


def shown(html, folder, root):
    """Paths, relative to folder, of the SVGs inside folder that html shows with <img> (at most FILE_LIMIT)."""
    out, real = [], os.path.realpath(folder)
    for tag in IMG.findall(html):
        path = _local(attr(tag, "src"), folder, root)
        if path and os.path.getsize(path) <= FILE_LIMIT:
            rel = os.path.relpath(path, real)
            if not rel.startswith("..") and rel not in out:
                out.append(rel)
    return out


def snapshot(index, folder, root, dest):
    """Copy the SVGs index (a path) shows into dest, by their path in folder. dest is replaced."""
    shutil.rmtree(dest, ignore_errors=True)
    try:
        rels = shown(_read(index), folder, root)
    except OSError:
        return
    for rel in rels:
        try:
            os.makedirs(os.path.dirname(os.path.join(dest, rel)), exist_ok=True)
            shutil.copyfile(os.path.join(folder, rel), os.path.join(dest, rel))
        except OSError:
            pass


def changed(dest, folder):
    """True if a copy in dest (snapshot()) differs from that file in folder now, or the file is gone."""
    for d, _, files in os.walk(dest):
        for f in files:
            now = os.path.join(folder, os.path.relpath(os.path.join(d, f), dest))
            if not os.path.isfile(now) or not filecmp.cmp(os.path.join(d, f), now, shallow=False):
                return True
    return False
