"""html_server.py end to end: a real server on a temp tree, with tests/fake_claude.py as claude."""
import json
import os
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request

from tests import util


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = root = util.new_tree("server")
        cls.port = free_port()
        util.write(os.path.join(root, "www", "dirai.json"), json.dumps({"port": cls.port}))
        util.write(os.path.join(root, "p1", "index.html"),
                   "<html><head><title>P one</title></head><body><p>hello</p></body></html>")
        util.write(os.path.join(root, "p1", "x.png"), "png")
        util.write(os.path.join(root, "p1", "x.txt"), "secret")
        subprocess.run([sys.executable, os.path.join(util.LIB, "build_index.py"), root],
                       stdout=subprocess.DEVNULL, check=True)
        cls.log = open(os.path.join(util.TMP, "server.log"), "w")
        cls.proc = subprocess.Popen([sys.executable, os.path.join(util.LIB, "html_server.py"),
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

    @classmethod
    def get_raw(cls, path, owner=False, data=None):
        """(status, headers, body bytes); follows no redirects."""
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (cls.port, path), data=data)
        if owner:
            req.add_header("Cookie", "review_key=" + cls.key)
        if data is not None:
            req.add_header("X-Review", "1")
            req.add_header("Content-Type", "application/json")
        opener = urllib.request.build_opener(NoRedirect)
        try:
            with opener.open(req, timeout=10) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def get(self, path, owner=False):
        return self.get_raw(path, owner)[2].decode()

    def api(self, path, **query):
        q = "&".join("%s=%s" % kv for kv in query.items())
        return json.loads(self.get("/_review/%s%s" % (path, "?" + q if q else ""), owner=True))

    def post(self, action, body):
        return json.loads(self.get_raw("/_review/" + action, True, json.dumps(body).encode())[2])

    def wait_status(self, page, status, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            st = self.api("state", page=page)
            if st["status"] == status:
                return st
            time.sleep(0.2)
        self.fail("%s never became %s: %s" % (page, status, st["status"]))

    # --- every visitor ------------------------------------------------------------------
    def test_anonymous_page(self):
        body = self.get("/p1/")
        self.assertTrue(body.startswith('<html><head><link rel="stylesheet" href="/_dirai/page.css"><title>'))
        self.assertIn("&#8962; Home</a></body>", body)
        self.assertNotIn("/_review/", body)

    def test_only_html_and_images(self):
        self.assertEqual(self.get_raw("/p1/x.txt")[0], 404)
        self.assertEqual(self.get_raw("/p1/x.png")[2], b"png")
        self.assertEqual(self.get_raw("/www/dirai.json")[0], 404)
        self.assertEqual(self.get_raw("/../../etc/passwd")[0], 404)

    def test_folder_redirect(self):
        code, headers, _ = self.get_raw("/p1")
        self.assertEqual(code, 301)
        self.assertTrue(headers["Location"].endswith("/p1/"))

    def test_page_css(self):
        code, headers, _ = self.get_raw("/_dirai/page.css")
        self.assertEqual((code, headers["Content-Type"], headers["Cache-Control"]),
                         (200, "text/css; charset=utf-8", "no-cache"))

    def test_api_needs_owner(self):
        self.assertEqual(self.get_raw("/_review/all")[0], 404)
        self.assertEqual(self.get_raw("/_review/panel.js")[0], 404)

    def test_bad_login_key(self):
        self.assertEqual(self.get_raw("/_review/login?key=wrong")[0], 404)
        code, headers, _ = self.get_raw("/_review/login?key=" + self.key)
        self.assertEqual(code, 302)
        self.assertIn("review_key=" + self.key, headers["Set-Cookie"])

    # --- owner --------------------------------------------------------------------------
    def test_owner_page_and_list(self):
        self.assertIn('<script src="/_review/panel.js" data-page="p1"></script>'
                      '<script src="/_review/newagent.js" data-base="p1" data-root="%s"></script>' % self.root,
                      self.get("/p1/", owner=True))
        lst = self.get("/www/index.html", owner=True)
        self.assertIn('<script src="/_review/list.js"></script>', lst)
        self.assertIn('data-base="" data-root="%s"' % self.root, lst)

    def test_ui_scripts(self):
        code, headers, _ = self.get_raw("/_review/panel.js", owner=True)
        self.assertEqual((code, headers["Content-Type"], headers["Cache-Control"]),
                         (200, "application/javascript", "no-store"))

    def test_small_endpoints(self):
        self.assertEqual(self.api("dirs", prefix="p"), ["p1/"])
        self.assertEqual(self.api("permissions"), {"mode": "allowlist", "modes": ["allowlist", "ask"]})
        self.assertIn("error", self.post("new", {"dir": "../x", "task": "t"}))
        self.assertIn("error", self.post("new", {"dir": "www/x", "task": "t"}))
        self.assertIn("error", self.post("new", {"dir": "ok", "task": " "}))
        self.assertEqual(self.post("usage_stop", {"name": "session", "percent": 50}),
                         {"ok": True, "stop": {"session": 50, "weekly": 100}})
        self.assertIn("error", self.post("usage_stop", {"name": "session", "percent": 500}))
        self.assertIn("error", self.post("permissions", {"mode": "yolo"}))
        self.assertEqual(self.get_raw("/_review/state?page=nope", owner=True)[0], 404)

    def test_comment_run(self):
        """A comment runs claude, which edits the page, asks and withdraws, and fixes the card."""
        self.assertEqual(self.post("comment", {"page": "p1", "text": "please look",
                                               "selection": {"text": "hello", "heading": ""}}), {"ok": True})
        st = self.wait_status("p1", "unread")
        th = st["thread"]
        self.assertEqual([m["role"] for m in th], ["user", "ask", "claude", "system"])
        self.assertEqual(th[0]["selection"]["lines"], [1, 1])
        self.assertEqual((th[1]["answer"], th[1]["rules"]), ("withdrawn", ["Bash(ls)", "Bash(rm -rf /x)"]))
        self.assertEqual((th[2]["text"], th[2]["cost"], th[2]["model"]), ("did it", 0.7, "sonnet"))
        self.assertEqual(th[3]["text"], "The summary card needed fixing; it still has problems: "
                                        "the page has no summary card.")
        self.assertEqual(st["session_id"], "sess1")
        self.assertEqual(st["denials"], [{"text": "Read: /etc/hosts", "rules": ["Read(//etc/**)"],
                                          "blocked": False, "granted": False}])
        # the page as it was before the run, for the panel's highlights
        self.assertEqual(self.get("/_review/prev?page=p1", owner=True),
                         "<html><head><title>P one</title></head><body><p>hello</p></body></html>")
        # follow-ups on an idle page with a session
        self.assertEqual(self.post("model", {"page": "p1", "model": "opus"}), {"ok": True})
        self.assertEqual(self.post("status", {"page": "p1", "status": "closed"}), {"ok": True})
        self.assertIn("error", self.post("cancel", {"page": "p1"}))
        self.assertIn("error", self.post("grant", {"page": "p1", "rules": ["Bash(sudo x)"], "always": False}))
        self.assertEqual(self.post("newchat", {"page": "p1"}), {"ok": True})
        self.assertIsNone(self.api("state", page="p1")["session_id"])

    def test_new_agent(self):
        r = self.post("new", {"dir": "n/new1", "task": "make <a> thing", "every": "week"})
        self.assertEqual(r, {"ok": True, "url": "/n/new1/"})
        self.wait_status("n/new1", "unread")
        page = os.path.join(self.root, "n", "new1")
        with open(os.path.join(page, "argv.json")) as f:
            argv = json.load(f)
        self.assertEqual(argv[:12],
                         ["-p", "--model", "sonnet", "--input-format", "stream-json", "--output-format",
                          "stream-json", "--verbose", "--permission-mode", "dontAsk", "--restricted",
                          "--strict-mcp-config"])
        self.assertEqual(argv[argv.index("--add-dir") + 1], page)
        self.assertIn("Edit(/%s/**)" % page, argv)
        self.assertIn("Bash(sudo:*)", argv[argv.index("--disallowedTools"):])
        with open(os.path.join(page, "index.html")) as f:
            self.assertIn("make &lt;a&gt; thing", f.read())
        self.assertEqual(self.api("all")["n/new1"]["repeat"], "week")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


if __name__ == "__main__":
    unittest.main()
