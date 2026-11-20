"""Diagrams inline (svg_inline.py): what the server puts in place of <img src="x.svg">, what it leaves
alone, the copies from before a run (change marks), and a selection in a diagram quoting x.svg."""
import json
import os
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request

from tests import util
import tests.test_server as ts

import svg_inline

SVG = ('<?xml version="1.0"?>\n<!DOCTYPE svg>\n<!-- made by d.py -->\n'
       '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100" viewBox="0 0 200 100">\n'
       '<defs><marker id="arrow"><path d="M0,0 L1,1"/></marker></defs>\n'
       '<line x1="0" y1="0" x2="9" y2="9" marker-end="url(#arrow)"/>\n'
       '<text x="5" y="50">hello diagram</text>\n</svg>\n')
MPL = ('<svg xmlns="http://www.w3.org/2000/svg" width="460pt" height="345pt">\n'
       '<defs><style type="text/css">*{stroke-linecap:butt;stroke-linejoin:round;}</style></defs>\n'
       '<text>µA</text></svg>')


class Expand(unittest.TestCase):
    def setUp(self):
        self.root = util.new_tree("svg_inline")
        self.p = os.path.join(self.root, "p")
        util.write(os.path.join(self.p, "d.svg"), SVG)

    def expand(self, html, report=None):
        return svg_inline.expand(html, self.p, self.root, report)

    def test_inline(self):
        out = self.expand('<p>a</p><img src="d.svg" alt="A d" width="50%"><p>b</p>')
        self.assertTrue(out.startswith("<p>a</p><svg "))
        self.assertTrue(out.endswith("</svg><p>b</p>"))
        self.assertNotIn("<?xml", out)
        self.assertNotIn("DOCTYPE", out)
        self.assertNotIn("made by", out)
        self.assertIn('id="d-arrow"', out)
        self.assertIn('url(#d-arrow)', out)
        self.assertIn('data-dirai-src="d.svg" role="img" aria-label="A d" width="50%"', out)
        self.assertNotIn('width="200"', out)       # the <img>'s width wins, height from the viewBox
        self.assertNotIn('height="100"', out)

    def test_two_copies(self):
        out = self.expand('<img src="d.svg"><img src="d.svg">')
        self.assertIn('id="d-arrow"', out)
        self.assertIn('id="d2-arrow"', out)
        self.assertIn('url(#d2-arrow)', out)

    def test_matplotlib_style(self):
        util.write(os.path.join(self.p, "m.svg"), MPL)
        out = self.expand('<img src="m.svg">')
        self.assertNotIn("<style", out)
        self.assertIn('<svg stroke-linejoin="round" stroke-linecap="butt"', out)
        self.assertIn("µA", out)

    def test_heatmap_raster(self):
        """matplotlib's imshow/pcolormesh/colorbar: the raster as a data: PNG inside the SVG is fine."""
        img = ('<image height="10" id="img1" width="10" x="0" xlink:href="data:image/png;base64,\n'
               'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGD4DwABBAEAwS2OUAAAAABJRU5ErkJggg==\n" y="0"/>')
        util.write(os.path.join(self.p, "h.svg"), SVG.replace("<text", img + "<text"))
        out = self.expand('<img src="h.svg">')
        self.assertIn('data-dirai-src="h.svg"', out)
        self.assertIn('id="h-img1"', out)
        # a raster bigger than LIMIT: counted out of the limit, which is for the page's elements
        big = img.replace("\n\"", "A" * (svg_inline.LIMIT + 1000) + "\n\"")
        util.write(os.path.join(self.p, "hb.svg"), SVG.replace("<text", big + "<text"))
        self.assertIn('data-dirai-src="hb.svg"', self.expand('<img src="hb.svg">'))
        for name, bad in (("h_url.svg", img.replace("data:image/png;base64,", "http://x/a.png#")),
                          ("h_on.svg", img.replace(' y="0"', ' y="0" onload="x()"'))):
            util.write(os.path.join(self.p, name), SVG.replace("<text", bad + "<text"))
            self.assertNotIn("data-dirai-src", self.expand('<img src="%s">' % name), name)

    def test_skipped(self):
        cases = {"s.svg": SVG.replace("<text", "<script>x()</script><text"),
                 "c.svg": SVG.replace("<defs>", "<style>.t{fill:red}</style><defs>"),
                 "i.svg": SVG.replace("<text", '<image href="a.png"/><text'),
                 "o.svg": SVG.replace("<line ", '<line onclick="x()" '),
                 "f.svg": SVG.replace("<text", "<foreignObject><p>x</p></foreignObject><text"),
                 "big.svg": SVG.replace("<text", "<!-- %s --><text" % ("x" * svg_inline.LIMIT))}
        for name, text in cases.items():
            util.write(os.path.join(self.p, name), text)
        util.write(os.path.join(self.root, "..", "outside.svg"), SVG)
        tags = ['<img src="%s">' % n for n in cases] + [
            '<img src="../../outside.svg">', '<img src="http://x/d.svg">', '<img src="/p/d.svg">',
            '<img src="gone.svg">', '<img src="x.png">']
        report = []
        self.assertEqual(self.expand("".join(tags), report), "".join(tags))
        self.assertEqual(len(report), len(tags) - 1)   # each .svg, with why
        self.assertIn(("s.svg", "has <script"), report)
        self.assertIn(("big.svg", "over 300 kB"), report)
        self.assertIn(("o.svg", "has an on…= handler"), report)

    def test_inline_one(self):
        """A figure a page's script adds: the same <svg>, with the ids kept apart by the given prefix."""
        out = svg_inline.inline_one("d.svg", self.p, self.root, "js1-")
        self.assertTrue(out.startswith("<svg "))
        self.assertIn('id="js1-d-arrow"', out)
        self.assertIn("url(#js1-d-arrow)", out)
        self.assertIn('data-dirai-src="d.svg"', out)
        util.write(os.path.join(self.p, "s.svg"), SVG.replace("<text", "<script>x()</script><text"))
        for src in ("s.svg", "gone.svg", "x.png", 'd.svg" onload="x()', "", "../../outside.svg"):
            self.assertIsNone(svg_inline.inline_one(src, self.p, self.root, "js1-"), src)

    def test_snapshot(self):
        index = os.path.join(self.p, "index.html")
        util.write(os.path.join(self.p, "fig", "e.svg"), SVG)
        util.write(index, '<img src="d.svg"><img src="fig/e.svg"><img src="x.png">')
        snap = os.path.join(self.root, "www", "snap")
        svg_inline.snapshot(index, self.p, self.root, snap)
        self.assertEqual(sorted(os.listdir(snap)), ["d.svg", "fig"])
        self.assertFalse(svg_inline.changed(snap, self.p))
        util.write(os.path.join(self.p, "fig", "e.svg"), SVG.replace("hello", "redrawn"))
        self.assertTrue(svg_inline.changed(snap, self.p))
        with open(index) as f:
            page = f.read()
        old = svg_inline.expand(page, self.p, self.root, snapshot=snap)
        self.assertNotIn("redrawn", old)       # the drawing from before the run
        self.assertIn("redrawn", svg_inline.expand(page, self.p, self.root))


class ServerInlines(unittest.TestCase):
    """End to end: the page as sent, the file on disk, the old page, and a selection in a diagram."""
    @classmethod
    def setUpClass(cls):
        cls.root = root = util.new_tree("svg_server")
        cls.port = ts.free_port()
        util.write(os.path.join(root, "www", "dirai.json"), json.dumps({"port": cls.port}))
        cls.page = ('<html><head><title>D</title></head><body><h1>D</h1>\n<p>text</p>\n'
                    '<figure><img src="d.svg" alt="A d"><figcaption>Script: d.py</figcaption></figure>\n'
                    '</body></html>')
        util.write(os.path.join(root, "p", "index.html"), cls.page)
        util.write(os.path.join(root, "p", "d.svg"), SVG)
        subprocess.run([sys.executable, os.path.join(util.LIB, "agent_list.py"), root],
                       stdout=subprocess.DEVNULL, check=True)
        cls.log = open(os.path.join(util.TMP, "svg_server.log"), "w")
        cls.proc = subprocess.Popen([sys.executable, os.path.join(util.LIB, "server.py"),
                                     root, str(cls.port), "127.0.0.1"], stdout=cls.log, stderr=cls.log)
        for _ in range(100):
            try:
                cls.get_raw("/www/index.html")
                break
            except (OSError, urllib.error.URLError):
                time.sleep(0.1)
        with open(os.path.join(os.environ["DIRAI_CONFIG_DIR"], "key")) as f:
            cls.key = f.read().strip()

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(10)
        cls.log.close()

    get_raw = classmethod(ts.Server.get_raw.__func__)
    get = ts.Server.get
    api = ts.Server.api
    post = ts.Server.post
    wait_status = ts.Server.wait_status

    def test_page(self):
        for owner in (False, True):
            body = self.get("/p/", owner)
            self.assertNotIn('<img src="d.svg"', body)
            self.assertIn('data-dirai-src="d.svg" role="img" aria-label="A d"', body)
            self.assertIn("hello diagram</text>", body)
            self.assertIn("/_dirai/index.css", body)      # the shared style is still linked
        with open(os.path.join(self.root, "p", "index.html")) as f:
            self.assertEqual(f.read(), self.page)        # the file on disk keeps its <img>
        self.assertEqual(self.get("/p/d.svg"), SVG)      # and the SVG is still served as it is

    def test_script_added(self):
        """An <img> a page's script adds: every page loads svg_watch.js, and /_dirai/svg gives the <svg>."""
        for owner in (False, True):
            self.assertIn('<script src="/_dirai/svg_watch.js"></script>', self.get("/p/", owner))
        self.assertIn("MutationObserver", self.get("/_dirai/svg_watch.js"))
        svg = self.get("/_dirai/svg?path=/p/d.svg&n=2")
        self.assertTrue(svg.startswith("<svg "))
        self.assertIn('id="js2-d-arrow"', svg)
        self.assertIn("hello diagram</text>", svg)
        util.write(os.path.join(self.root, "p", "s.svg"), SVG.replace("<text", "<script>x()</script><text"))
        for q in ("/p/s.svg&n=1", "/p/gone.svg&n=1", "/p/index.html&n=1", "/../outside.svg&n=1", "/p/d.svg&n=x"):
            self.assertEqual(self.get_raw("/_dirai/svg?path=" + q)[0], 404, q)

    def test_selection_and_prev(self):
        """A selection in the diagram quotes d.svg and its line; after the run, /_review/prev has the
        diagram as it was drawn before it, so a redraw is marked."""
        self.assertEqual(self.post("comment", {"agent": "p", "text": "why?", "selection": {
            "text": "hello diagram", "heading": "D", "file": "d.svg", "svg": True}}), {"ok": True})
        st = self.wait_status("p", "unread")
        sel = st["thread"][0]["selection"]
        self.assertEqual((sel["file"], sel["lines"], sel["svg"]), ("d.svg", [7, 7], True))
        prev = self.get("/_review/prev?agent=p", owner=True)
        self.assertIn('data-dirai-src="d.svg"', prev)
        self.assertIn("hello diagram", prev)
        # a selection naming a file that isn't the agent's: placed by its heading only
        self.assertEqual(self.post("comment", {"agent": "p", "text": "and?", "selection": {
            "text": "x", "heading": "D", "file": "../q/d.svg", "svg": True}}), {"ok": True})
        st = self.wait_status("p", "unread")
        self.assertNotIn("file", [m for m in st["thread"] if m["role"] == "user"][-1]["selection"])


if __name__ == "__main__":
    unittest.main()
