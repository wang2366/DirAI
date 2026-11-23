"""server.py end to end: a real server on a temp tree, with tests/fake_claude.py as claude."""
import base64
import hashlib
import http.client
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
import zipfile

from tests import util

import agent_prompts


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
        subprocess.run([sys.executable, os.path.join(util.LIB, "agent_list.py"), root],
                       stdout=subprocess.DEVNULL, check=True)
        cls.log = open(os.path.join(util.TMP, "server.log"), "w")
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

    def wait_status(self, agent, status, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            st = self.api("state", agent=agent)
            if st["status"] == status:
                return st
            time.sleep(0.2)
        self.fail("%s never became %s: %s" % (agent, status, st["status"]))

    # --- every visitor ------------------------------------------------------------------
    def test_anonymous_index(self):
        body = self.get("/p1/")
        self.assertTrue(body.startswith('<html><head><link rel="stylesheet" href="/_dirai/index.css"><title>'))
        self.assertIn("&#8962; Home</a>", body)
        self.assertIn('title="The server this page is on"', body)   # then the server's name and path
        self.assertTrue(body.endswith("/p1</div></body></html>"))
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

    def test_index_css(self):
        code, headers, _ = self.get_raw("/_dirai/index.css")
        self.assertEqual((code, headers["Content-Type"], headers["Cache-Control"]),
                         (200, "text/css; charset=utf-8", "no-cache"))

    def test_api_needs_owner(self):
        self.assertEqual(self.get_raw("/_review/all")[0], 404)
        self.assertEqual(self.get_raw("/_review/panel.js")[0], 404)

    def test_bad_login_key(self):
        self.assertEqual(self.get_raw("/_review/login?key=wrong")[0], 404)
        code, headers, _ = self.get_raw("/_review/login?key=" + self.key)
        self.assertEqual(code, 302)
        name = "review_key_" + hashlib.sha256(self.key.encode()).hexdigest()[:10]
        self.assertIn("%s=%s;" % (name, self.key), headers["Set-Cookie"])
        # that cookie, or the plain review_key of earlier versions, makes you the owner
        for cookie in (name, "review_key"):
            req = urllib.request.Request("http://127.0.0.1:%d/_review/all" % self.port,
                                         headers={"Cookie": "%s=%s" % (cookie, self.key)})
            with urllib.request.urlopen(req, timeout=10) as r:
                self.assertEqual(r.status, 200, cookie)
        # another machine's cookie (another key) beside it doesn't get in the way
        req = urllib.request.Request("http://127.0.0.1:%d/_review/all" % self.port, headers={
            "Cookie": "review_key_0123456789=other; %s=%s" % (name, self.key)})
        with urllib.request.urlopen(req, timeout=10) as r:
            self.assertEqual(r.status, 200)

    # --- owner --------------------------------------------------------------------------
    def test_owner_index_and_agent_list(self):
        self.assertIn('<script src="/_review/panel.js" data-agent="p1"></script>'
                      '<script src="/_review/new_agent.js" data-base="p1" data-root="%s"></script>' % self.root,
                      self.get("/p1/", owner=True))
        lst = self.get("/www/index.html", owner=True)
        self.assertIn('<script src="/_review/agent_list.js"></script>', lst)
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
        self.assertEqual(self.get_raw("/_review/state?agent=nope", owner=True)[0], 404)

    def test_agent_card_for_the_tree_tab(self):
        card = ('<h1>c</h1><!-- dirai:card --><details id="dirai-card"><dl><dt>Objective</dt><dd>Find <b>it</b>.</dd>'
                '<dt>Result</dt><dd>42 &plusmn; 1</dd><dt>Open</dt><dd>none</dd><dt>Updated</dt><dd>2026-10-28</dd></dl>'
                '</details><!-- /dirai:card -->')
        util.write(os.path.join(self.root, "pcard", "index.html"), "<html><body>%s</body></html>" % card)
        try:
            got = self.api("card", agent="pcard")
            self.assertEqual((got["objective"], got["open"], got["updated"]), ("Find it.", "none", "2026-10-28"))
            self.assertEqual(self.api("card", agent="p1"), {})                       # no card: {}
            self.assertEqual(self.get_raw("/_review/card?agent=nope", owner=True)[0], 404)
            self.assertEqual(self.get_raw("/_review/card?agent=../x", owner=True)[0], 404)
            self.assertEqual(self.get_raw("/_review/card?agent=pcard")[0], 404)       # owner only
        finally:
            shutil.rmtree(os.path.join(self.root, "pcard"), ignore_errors=True)

    def test_agent_list_loads_the_tree_script(self):
        lst = self.get("/www/index.html", owner=True)
        self.assertLess(lst.index("/_review/agent_list.js"), lst.index("/_review/agent_tree.js"))
        self.assertEqual(self.get_raw("/_review/agent_tree.js", owner=True)[0], 200)

    def test_tab_alert_script_only_on_agent_pages(self):
        lst = self.get("/www/index.html", owner=True)   # the agent list's tab gets no mark
        self.assertNotIn("/_review/tab_alert.js", lst)
        page = self.get("/p1/", owner=True)
        self.assertLess(page.index("/_review/tab_alert.js"), page.index("/_review/panel.js"))
        self.assertEqual(self.get_raw("/_review/tab_alert.js", owner=True)[0], 200)

    def test_share_pill_and_shared_pages(self):
        # your agent's page: the Share pill; its quick state needs no gh
        self.assertIn('<script src="/_review/share.js" data-agent="p1"></script>', self.get("/p1/", owner=True))
        self.assertEqual(self.api("share", agent="p1", quick="1"), {"origin": None, "ready": None, "shared": []})
        # someone else's agent, cloned under www/shares/: the read-only pill, no chat and no actions on it
        full, page = "alice-dirai/alice_agent_repo", "www/shares/alice-dirai/alice_agent_repo/agents/fit"
        util.write(os.path.join(self.root, page, "index.html"), "<html><body><h1>Fit</h1></body></html>")
        util.write(os.path.join(self.root, "www", "shares.json"), json.dumps({"connected": {full: {"updated": []}}}))
        body = self.get("/%s/" % page, owner=True)
        self.assertIn('<script src="/_review/share.js" data-agent="%s" data-shared="1"></script>' % page, body)
        self.assertNotIn("/_review/panel.js", body)
        self.assertEqual(self.api("share", agent=page)["shared"]["owner"], "alice-dirai")
        self.assertIn("error", self.post("comment", {"agent": page, "text": "hi"}))
        self.assertEqual(self.post("share", {"agent": page, "op": "publish"}), {"error": "a shared agent is read-only"})
        self.assertIn("error", self.post("share", {"agent": page, "op": "copy", "dest": "../x"}))
        r = self.post("share", {"agent": page, "op": "copy", "dest": "copies/fit"})
        self.assertEqual(r, {"ok": True, "url": "/copies/fit/"})
        with open(os.path.join(self.root, "copies", "fit", ".dirai-origin")) as f:
            self.assertEqual(json.load(f)["repo"], full)
        # the Machines map gets the shares report (no gh here: nothing found, the clone as a box)
        sh = self.api("remotes")["shares"]
        self.assertEqual((sh["gh"], [g["full"] for g in sh["connected"]]), (False, [full]))
        # the same report for a server upstream (D8: each tree's connected repos in its Machines box)
        self.assertEqual([g["full"] for g in self.api("shares")["connected"]], [full])
        # a star is the one action allowed on a shared agent (the list's rows of shared agents)
        self.assertEqual(self.post("favorite", {"agent": page, "on": True})["favorites"], [page])

    def test_favorites(self):
        self.assertEqual(self.api("favorites"), [])
        self.assertEqual(self.post("favorite", {"agent": "p1", "on": True}), {"ok": True, "favorites": ["p1"]})
        self.assertEqual(self.post("favorite", {"agent": "p1", "on": True}), {"ok": True, "favorites": ["p1"]})
        self.assertEqual(self.api("favorites"), ["p1"])
        self.assertEqual(self.post("favorite", {"agent": "p1", "on": False}), {"ok": True, "favorites": []})
        self.assertIn("error", self.post("favorite", {"agent": "nope", "on": True}))

    def test_attach(self):
        """A file dropped on the panel is saved in the agent's pasted/; a fake image and a too big body are refused."""
        r = self.post("attach", {"agent": "p1", "name": "plot.png", "data": base64.b64encode(b"\x89PNG\r\n\x1a\nxx").decode()})
        self.assertTrue(r["path"].startswith("pasted/") and r["path"].endswith("_plot.png"), r)
        with open(os.path.join(self.root, "p1", r["path"]), "rb") as f:
            self.assertEqual(f.read(), b"\x89PNG\r\n\x1a\nxx")
        self.assertIn("error", self.post("attach", {"agent": "p1", "name": "fake.png", "data": base64.b64encode(b"text").decode()}))
        self.assertIn("error", self.post("attach", {"agent": "nope", "name": "a.txt", "data": "YQ=="}))
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)   # says 40 MB, sends none of it
        conn.putrequest("POST", "/_review/attach")
        for k, v in (("Cookie", "review_key=" + self.key), ("X-Review", "1"), ("Content-Length", str(40 << 20))):
            conn.putheader(k, v)
        conn.endheaders()
        self.assertEqual(conn.getresponse().status, 413)
        conn.close()

    def test_comment_while_busy_is_queued(self):
        """A message to a busy agent waits in its inbox; the inbox action edits, removes and sends."""
        util.write(os.path.join(self.root, "busy1", "index.html"), "<html><body>b</body></html>")
        path = os.path.join(self.root, "www", "agents.json")
        with open(path) as f:
            data = json.load(f)
        data["busy1"] = {"status": "working", "thread": [], "session_id": None, "denials": [], "grants": []}
        with open(path, "w") as f:
            json.dump(data, f)
        self.assertEqual(self.post("comment", {"agent": "busy1", "text": "later"}), {"ok": True, "queued": True})
        inbox = self.api("state", agent="busy1")["inbox"]
        self.assertEqual([m["text"] for m in inbox], ["later"])
        self.assertEqual(self.api("all")["busy1"]["inbox"], 1)
        self.assertEqual(self.post("inbox", {"agent": "busy1", "op": "edit", "id": inbox[0]["id"], "text": "edited"}), {"ok": True})
        self.assertIn("error", self.post("inbox", {"agent": "busy1", "op": "send"}))     # still busy
        self.assertEqual(self.post("inbox", {"agent": "busy1", "op": "remove", "id": inbox[0]["id"]}), {"ok": True})
        self.assertIn("error", self.post("inbox", {"agent": "busy1", "op": "remove", "id": inbox[0]["id"]}))
        self.assertNotIn("inbox", self.api("state", agent="busy1"))

    def test_comment_run(self):
        """A message runs claude, which edits index.html, asks and withdraws, and fixes the card."""
        self.assertEqual(self.post("comment", {"agent": "p1", "text": "please look",
                                               "selection": {"text": "hello", "heading": ""}}), {"ok": True})
        st = self.wait_status("p1", "unread")
        th = st["thread"]
        self.assertEqual([m["role"] for m in th], ["user", "ask", "claude", "system"])
        self.assertEqual(th[0]["selection"]["lines"], [1, 1])
        self.assertEqual((th[1]["answer"], th[1]["rules"]), ("withdrawn", ["Bash(rm -rf /x)"]))
        self.assertEqual((th[2]["text"], th[2]["cost"], th[2]["model"]), ("did it", 0.7, "sonnet"))
        self.assertEqual(th[3]["text"], "The summary card needed fixing; it still has problems: "
                                        "index.html has no summary card.")
        self.assertEqual(st["session_id"], "sess1")
        self.assertEqual(st["denials"], [{"text": "Read: /etc/hosts", "rules": ["Read(//etc/**)"], "keep": ["Read(//etc/**)"],
                                          "blocked": False, "granted": False, "count": 1, "label": "", "why": ""}])
        # index.html as it was before the run, for the panel's highlights
        self.assertEqual(self.get("/_review/prev?agent=p1", owner=True),
                         "<html><head><title>P one</title></head><body><p>hello</p></body></html>")
        # Undo / Redo of each changed block: marked in the owner's copy of the page only
        index = os.path.join(self.root, "p1", "index.html")
        with open(index) as f:
            after = f.read()
        self.assertIn('<template data-dirai-block="0"></template>', self.get("/p1/index.html", owner=True))
        self.assertNotIn("data-dirai-block", self.get("/p1/index.html"))
        self.assertIn("error", self.post("undo", {"agent": "p1", "block": 1}))
        self.assertEqual(self.post("undo", {"agent": "p1", "block": 0}), {"ok": True})
        with open(index) as f:
            self.assertEqual(f.read(), "<html><head><title>P one</title></head><body><p>hello</p></body></html>")
        self.assertIn('<template data-dirai-block="0" data-undone></template>', self.get("/p1/index.html", owner=True))
        self.assertEqual(self.post("undo", {"agent": "p1", "block": 0}), {"ok": True})
        with open(index) as f:
            self.assertEqual(f.read(), after)
        self.assertEqual(self.api("state", agent="p1")["thread"][-1]["text"],
                         "Redid change 1 of the latest run in index.html.")
        with open(index, "a") as f:   # edited by hand since: no per-block undo
            f.write("\n")
        self.assertIn("by hand", self.post("undo", {"agent": "p1", "block": 0})["error"])
        self.assertNotIn("data-dirai-block", self.get("/p1/index.html", owner=True))
        with open(index, "w") as f:
            f.write(after)
        # follow-ups on an idle agent with a session
        self.assertEqual(self.post("model", {"agent": "p1", "model": "opus"}), {"ok": True})
        # "page": what panel scripts loaded before 2026-10 send
        self.assertEqual(self.post("status", {"page": "p1", "status": "closed"}), {"ok": True})
        self.assertEqual(self.api("state", page="p1")["model"], "opus")
        self.assertIn("error", self.post("cancel", {"agent": "p1"}))
        self.assertIn("error", self.post("grant", {"agent": "p1", "rules": ["Bash(sudo x)"], "always": False}))
        self.assertEqual(self.post("newchat", {"agent": "p1"}), {"ok": True})
        self.assertIsNone(self.api("state", agent="p1")["session_id"])

    def test_folder_files_shown_to_the_owner(self):
        util.write(os.path.join(self.root, "m1", "index.html"), "<html><body><p>m</p></body></html>")
        util.write(os.path.join(self.root, "m1", "run.sh"), "echo one\necho two\n")
        tag = '<script src="/_review/files.js" data-agent="m1"></script>'
        self.assertIn(tag, self.get("/m1/", owner=True))
        self.assertNotIn("files.js", self.get("/m1/"))                    # visitors: no folder
        self.assertEqual(self.get_raw("/m1/run.sh")[0], 404)              # never served as a file
        self.assertEqual(self.get_raw("/_review/files?agent=m1")[0], 404) # API: owner only
        self.assertEqual(self.get_raw("/_review/files.js", owner=True)[0], 200)
        d = self.api("files", agent="m1")
        self.assertEqual([(f["name"], f["text"]) for f in d["files"]], [("run.sh", "echo one\necho two\n")])

    def test_subfolder_files_and_selection(self):
        util.write(os.path.join(self.root, "m4", "index.html"), "<html><body><p>m</p></body></html>")
        util.write(os.path.join(self.root, "m4", "d", "x.sh"), "echo one\necho two\n")
        util.write(os.path.join(self.root, "m4", "kid", "index.html"), "<html><body></body></html>")
        d = self.api("files", agent="m4", sub="d")
        self.assertEqual([(f["name"], f["text"]) for f in d["files"]], [("x.sh", "echo one\necho two\n")])
        top = self.api("files", agent="m4")
        self.assertEqual({x["name"]: x["agent"] for x in top["dirs"]}, {"d": False, "kid": True})
        for bad in ("..", "kid", "nope", "d/.."):
            self.assertEqual(self.get_raw("/_review/files?agent=m4&sub=" + bad, owner=True)[0], 404, bad)
        self.assertEqual(self.get_raw("/_review/files?agent=m4&sub=d")[0], 404)   # owner only
        self.assertEqual(self.post("comment", {"agent": "m4", "text": "say three", "selection": {
            "text": "echo two", "file": "d/x.sh", "lines": [2, 2]}}), {"ok": True})
        st = self.wait_status("m4", "unread")
        self.assertEqual(st["thread"][0]["selection"],
                         {"text": "echo two", "heading": "", "file": "d/x.sh", "lines": [2, 2]})

    def test_download_and_zip(self):
        r = os.path.join(self.root, "dl")
        util.write(os.path.join(r, "index.html"), "<html><body></body></html>")
        util.write(os.path.join(r, "run.sh"), "echo hi\n")
        util.write(os.path.join(r, "d", "fig.png"), "png")
        util.write(os.path.join(r, "tmp", "x"), "scratch")
        util.write(os.path.join(r, ".git", "config"), "secret")
        util.write(os.path.join(r, "kid", "index.html"), "<html></html>")
        util.write(os.path.join(r, "kid", "k.txt"), "k")
        util.write(os.path.join(self.root, "outside.txt"), "out")
        os.symlink(os.path.join(self.root, "outside.txt"), os.path.join(r, "link.txt"))
        with open(os.path.join(r, "data.bin"), "wb") as f:
            f.write(bytes(range(256)) * 10)
        code, headers, body = self.get_raw("/_review/download?agent=dl&name=data.bin", owner=True)
        self.assertEqual((code, body), (200, bytes(range(256)) * 10))
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertEqual(self.get_raw("/_review/download?agent=dl&name=d/fig.png", owner=True)[2], b"png")
        for bad in ("../p1/x.txt", ".git/config", "tmp/x", "link.txt", "kid/k.txt", "nope", ""):
            self.assertEqual(self.get_raw("/_review/download?agent=dl&name=" + bad, owner=True)[0], 404, bad)
        self.assertEqual(self.get_raw("/_review/download?agent=dl&name=run.sh")[0], 404)   # owner only
        code, headers, body = self.get_raw("/_review/zip?agent=dl", owner=True)
        z = zipfile.ZipFile(io.BytesIO(body))
        self.assertEqual(sorted(z.namelist()), ["d/fig.png", "data.bin", "index.html", "run.sh"])
        self.assertEqual(z.read("data.bin"), bytes(range(256)) * 10)
        self.assertIn('filename="dl.zip"', headers["Content-Disposition"])
        body = self.get_raw("/_review/zip?agent=dl&sub=d", owner=True)[2]
        self.assertEqual(zipfile.ZipFile(io.BytesIO(body)).namelist(), ["fig.png"])
        for bad in ("kid", "tmp", "..", ".git", "nope"):
            self.assertEqual(self.get_raw("/_review/zip?agent=dl&sub=" + bad, owner=True)[0], 404, bad)
        self.assertEqual(self.get_raw("/_review/zip?agent=dl")[0], 404)   # owner only

    def test_file_selection_message(self):
        util.write(os.path.join(self.root, "m2", "index.html"), "<html><body><p>m</p></body></html>")
        util.write(os.path.join(self.root, "m2", "run.sh"), "echo one\necho two\n")
        self.assertIn("error", self.post("comment", {"agent": "m2", "text": "x", "selection": {
            "text": "one", "file": "../p1/index.html", "lines": [1, 1]}}))
        self.assertEqual(self.post("comment", {"agent": "m2", "text": "say three", "selection": {
            "text": "echo two", "file": "run.sh", "lines": [2, 2]}}), {"ok": True})
        st = self.wait_status("m2", "unread")
        self.assertEqual(st["thread"][0]["selection"],
                         {"text": "echo two", "heading": "", "file": "run.sh", "lines": [2, 2]})

    def test_rendered_md_selection(self):
        util.write(os.path.join(self.root, "m3", "index.html"), "<html><body><p>m</p></body></html>")
        util.write(os.path.join(self.root, "m3", "notes.md"), "# Notes\n\n- one\n- two item\n")
        self.assertEqual(self.post("comment", {"agent": "m3", "text": "fix", "selection": {
            "text": "two item", "file": "notes.md", "lines": [3, 4], "rendered": True}}), {"ok": True})
        st = self.wait_status("m3", "unread")
        self.assertEqual(st["thread"][0]["selection"]["lines"], [4, 4])   # the list block, narrowed

    def test_colleagues(self):
        for name, task in (("c1", "summarize"), ("c2", "find the peak")):
            util.write(os.path.join(self.root, name, "index.html"),
                       agent_prompts.STARTER_INDEX.format(title=name, task=task, date="2026-10-16"))
        self.assertIn("isn't inside", self.post("colleague", {"agent": "c1", "add": "/etc"})["error"])
        self.assertEqual(self.post("colleague", {"agent": "c1", "add": "http://localhost:9/c2/index.html"}), {"ok": True})
        self.assertEqual(self.api("state", agent="c1")["colleagues"],
                         [{"path": "c2", "url": "/c2/index.html", "gone": False, "mode": "read", "next": "own"}])
        row = '<dt class="dirai-colls">Colleagues</dt> <dd class="dirai-colls"><a href="/c2/index.html" title="c2">c2</a> (2026-10-16 ✓)</dd>'
        self.assertIn(row, self.get("/c1/"))                       # every visitor sees it
        self.assertNotIn("dirai-colls", self.get("/c2/"))
        with open(os.path.join(self.root, "c1", "index.html")) as f:
            self.assertNotIn("dirai-colls", f.read())            # the file itself never has it
        # F5: a click on the chip makes it writable; the card row marks it
        self.assertEqual(self.post("colleague", {"agent": "c1", "mode": "c2", "value": "own"}), {"ok": True})
        self.assertEqual(self.api("state", agent="c1")["colleagues"][0]["mode"], "own")
        self.assertIn('<span title="May edit its own files">✎</span> <a href="/c2/index.html"', self.get("/c1/"))
        self.assertIn("error", self.post("colleague", {"agent": "c1", "mode": "c2", "value": "write"}))
        self.assertEqual(self.post("colleague", {"agent": "c1", "remove": "c2"}), {"ok": True})
        self.assertNotIn("dirai-colls", self.get("/c1/"))

    def test_ungrant(self):
        # F4: the × after a rule in the card's Permissions list
        util.write(os.path.join(self.root, "u1", "index.html"), "<html><body><p>u</p></body></html>")
        path = os.path.join(self.root, "www", "agents.json")
        with open(path) as f:
            data = json.load(f)
        data["u1"] = {"status": "none", "thread": [], "denials": [], "grants": ["Bash(import os)", "Bash(make)"]}
        with open(path, "w") as f:
            json.dump(data, f)
        self.assertEqual([g["unusable"] != "" for g in self.api("state", agent="u1")["grant_info"]], [True, False])
        self.assertEqual(self.post("ungrant", {"agent": "u1", "rules": ["Bash(import os)"]}), {"ok": True})
        self.assertEqual([g["rule"] for g in self.api("state", agent="u1")["grant_info"]], ["Bash(make)"])
        self.assertIn("error", self.post("ungrant", {"agent": "u1", "rules": ["Bash(import os)"]}))

    def test_schedule(self):
        util.write(os.path.join(self.root, "s1", "index.html"), "<html><body><p>hello</p></body></html>")
        p = lambda body: self.post("schedule", dict({"agent": "s1"}, **body))   # noqa: E731
        prev = p({"op": "preview", "kind": "weekly", "days": [4], "time": "15:00"})
        self.assertEqual(len(prev["next"]), 2)
        self.assertTrue(prev["next"][0].startswith("Fri ") and " 15:00 " in prev["next"][0], prev)
        self.assertEqual(p({"op": "preview", "kind": "weekly", "days": [], "time": "15:00"}),
                         {"error": "Pick at least one day."})
        self.assertEqual(p({"kind": "daily", "time": "08:00"}), {"error": "Write the message to send."})
        self.assertEqual(p({"kind": "daily", "time": "08:00", "text": "check queue"}), {"ok": True})
        t = time.localtime(time.time() + 7200)
        self.assertEqual(p({"kind": "once", "date": time.strftime("%Y-%m-%d", t), "time": time.strftime("%H:%M", t),
                            "text": "rerun", "session": "continue",
                            "selection": {"text": "hello", "heading": ""}}), {"ok": True})
        st = self.api("state", agent="s1")
        sch = st["schedules"]
        self.assertEqual(sorted(s["label"] for s in sch), ["daily 08:00", "once"])
        self.assertTrue(st["tz"] and st["now"] and all(s["when"] for s in sch))
        self.assertEqual([s for s in sch if s["kind"] == "once"][0]["selection"]["text"], "hello")
        daily = [s for s in sch if s["kind"] == "daily"][0]
        self.assertEqual(p({"id": daily["id"], "kind": "daily", "time": "09:00", "text": "check queue"}), {"ok": True})
        self.assertEqual(p({"op": "pause", "id": daily["id"]}), {"ok": True})
        self.assertTrue([s for s in self.api("state", agent="s1")["schedules"] if s["id"] == daily["id"]][0]["paused"])
        self.assertEqual(p({"op": "resume", "id": daily["id"]}), {"ok": True})
        self.assertEqual(self.api("all")["s1"]["schedules"], 2)
        self.assertEqual(p({"op": "delete", "id": daily["id"]}), {"ok": True})
        self.assertIn("error", p({"op": "delete", "id": daily["id"]}))

    def test_refresh(self):
        os.remove(os.path.join(self.root, "www", "index.html"))
        self.assertEqual(self.post("refresh", {}), {"ok": True})
        self.assertTrue(os.path.exists(os.path.join(self.root, "www", "index.html")))   # rebuilt before the reply

    def test_new_agent(self):
        r = self.post("new", {"dir": "n/new1", "task": "make <a> thing", "every": "week"})
        self.assertEqual(r, {"ok": True, "url": "/n/new1/"})
        self.wait_status("n/new1", "unread")
        agent = os.path.join(self.root, "n", "new1")
        with open(os.path.join(agent, "argv.json")) as f:
            argv = json.load(f)
        self.assertEqual(argv[:12],
                         ["-p", "--model", "sonnet", "--input-format", "stream-json", "--output-format",
                          "stream-json", "--verbose", "--permission-mode", "dontAsk", "--restricted",
                          "--strict-mcp-config"])
        self.assertEqual(argv[argv.index("--add-dir") + 1], agent)
        self.assertIn("Edit(/%s/**)" % agent, argv)
        self.assertIn("Bash(sudo:*)", argv[argv.index("--disallowedTools"):])
        with open(os.path.join(agent, "index.html")) as f:
            self.assertIn("make &lt;a&gt; thing", f.read())
        self.assertEqual(self.api("all")["n/new1"]["schedules"], 1)      # weekly, from next week
        self.assertEqual(self.api("state", agent="n/new1")["schedules"][0]["kind"], "weekly")
        # the agent list is rebuilt for the new agent (in the background)
        for _ in range(50):
            with open(os.path.join(self.root, "www", "index.html")) as f:
                if 'href="../n/new1/index.html"' in f.read():
                    break
            time.sleep(0.1)
        else:
            self.fail("the agent list was not rebuilt with n/new1")


class AgentList(unittest.TestCase):
    def setUp(self):
        self.root = util.new_tree("agent-list-" + self.id().rsplit(".", 1)[1])   # own folder: the
        # background --sizes run of one test may still be writing into its tree
        util.write(os.path.join(self.root, "a", "index.html"), "<html><head><title>A</title></head></html>")
        util.write(os.path.join(self.root, "b", "c", "index.html"), "<html></html>")

    def build(self, *args):
        subprocess.run([sys.executable, os.path.join(util.LIB, "agent_list.py"), self.root] + list(args),
                       stdout=subprocess.DEVNULL, check=True)
        with open(os.path.join(self.root, "www", "index.html")) as f:
            return f.read()

    def test_private(self):
        out = self.build()
        self.assertIn('href="../a/index.html"', out)
        self.assertIn('href="../b/c/index.html"', out)
        self.assertIn(">Tokens</th>", out)
        self.assertTrue(os.path.exists(os.path.join(self.root, "www", "agent_tokens.json")))


class StartSetsUp(unittest.TestCase):
    """DirAI start sets up a folder that isn't a tree yet (proposal 26); connect is gone (proposal 22)."""
    def dirai(self, folder, *args, home=None):
        env = dict(os.environ, HOME=home or os.path.join(util.TMP, "home"))
        os.makedirs(env["HOME"], exist_ok=True)
        # no terminal: no questions, no browser
        return subprocess.run([os.path.join(util.TOOL, "bin", "DirAI"), "-C", folder] + list(args),
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=env, universal_newlines=True, timeout=180)

    def plain(self, name):
        """A new folder that is neither a tree nor in a git repo."""
        d = os.path.join(util.TMP, name)
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
        return d

    def test_start_sets_up_then_starts(self):
        d = self.plain("start-new")
        try:
            out = self.dirai(d, "start", "--no-open")
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            self.assertIn("Setting up a new DirAI tree at " + os.path.realpath(d), out.stdout)
            self.assertIn("Up on ", out.stdout)
            with open(os.path.join(d, "www", "dirai.json")) as f:
                self.assertIsInstance(json.load(f)["port"], int)
            self.assertFalse(os.path.exists(os.path.join(d, "CLAUDE.md")))   # outside git, no terminal: left alone
            again = self.dirai(d, "start", "--no-open")                     # an existing tree: no setup
            self.assertNotIn("Setting up", again.stdout)
            self.assertIn("Already running", again.stdout)
        finally:
            self.dirai(d, "stop")

    def test_start_stops_a_leftover_server_first(self):
        # server_host.txt names a server that doesn't answer but still runs (hung; this fake also ignores
        # TERM): start stops it (TERM, then KILL after 10 s) before starting a new one
        d = self.plain("start-leftover")
        self.assertEqual(self.dirai(d, "init").returncode, 0)
        root = os.path.realpath(d)
        fake = os.path.join(util.TMP, "fakebin", "dirai_serve")
        util.write(fake, "#!/bin/bash\ntrap '' TERM\nwhile true; do sleep 1; done\n")
        os.chmod(fake, 0o755)
        old = subprocess.Popen([fake, root], start_new_session=True)
        node = subprocess.run(["hostname", "-s"], stdout=subprocess.PIPE, universal_newlines=True).stdout.strip()
        host = os.path.join(d, "www", "server_host.txt")
        util.write(host, "%s nojob 2026-01-01 00:00:00 %d reload 1\n" % (node, old.pid))
        try:
            # written under a minute ago: it may still be coming up, so start leaves it alone
            out = self.dirai(d, "start", "--no-open")
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("under a minute ago", out.stderr)
            self.assertIsNone(old.poll())
            past = time.time() - 120
            os.utime(host, (past, past))
            out = self.dirai(d, "start", "--no-open")
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            self.assertIn("isn't answering: making sure it is gone first", out.stdout)
            self.assertIn("ignored TERM: killed", out.stdout)
            self.assertIsNotNone(old.wait(5))
            self.assertIn("Up on ", out.stdout)
        finally:
            if old.poll() is None:
                old.kill()
            self.dirai(d, "stop")

    def test_forget(self):
        # forget stops a running tree, takes it off the trees list and keeps the folder; a folder already
        # deleted only loses its line; a folder inside a tree is refused (never the enclosing tree)
        trees = os.path.join(os.environ["DIRAI_CONFIG_DIR"], "trees")
        def listed(r):
            with open(trees) as f:
                return r in f.read().split("\n")
        d, gone = self.plain("forget-live"), self.plain("forget-gone")
        root, groot = os.path.realpath(d), os.path.realpath(gone)
        try:
            self.assertEqual(self.dirai(d, "start", "--no-open").returncode, 0)
            self.assertEqual(self.dirai(gone, "init").returncode, 0)
            self.assertTrue(listed(root) and listed(groot))
            os.makedirs(os.path.join(d, "sub"))
            out = self.dirai(d, "forget", os.path.join(root, "sub"))
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("is not a tree (it is inside " + root, out.stderr)
            self.assertTrue(listed(root))
            out = self.dirai(d, "forget", root)
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            self.assertIn("Stopped " + root, out.stdout)
            self.assertIn("Forgot %s (folder kept)" % root, out.stdout)
            self.assertFalse(os.path.exists(os.path.join(d, "www", "server_host.txt")))
            self.assertTrue(os.path.isdir(os.path.join(d, "www")))
            self.assertFalse(listed(root))
            shutil.rmtree(gone)
            out = self.dirai(util.TMP, "forget", groot + "/")
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            self.assertIn("Forgot %s (its folder is already gone)" % groot, out.stdout)
            self.assertFalse(listed(groot))
            self.assertIn("forgotten already", self.dirai(util.TMP, "forget", groot).stdout)
        finally:
            self.dirai(d, "stop")

    def test_bare_command_never_sets_up(self):
        d = self.plain("start-bare")
        out = self.dirai(d)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("DirAI start", out.stderr)
        self.assertFalse(os.path.exists(os.path.join(d, "www")))

    def test_other_commands_point_to_start(self):
        d = self.plain("start-status")
        out = self.dirai(d, "status")
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("run  DirAI start  in the folder to serve", out.stderr)

    def test_refuses_home(self):
        d = self.plain("start-home")
        out = self.dirai(d, "start", "--no-open", home=d)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("Refusing to serve", out.stderr)
        self.assertFalse(os.path.exists(os.path.join(d, "www", "dirai.json")))

    def test_init_sets_up_without_starting(self):
        d = self.plain("init-only")
        out = self.dirai(d, "init")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("Ready. Start it with: DirAI start", out.stdout)
        self.assertTrue(os.path.isfile(os.path.join(d, "www", "dirai.json")))
        self.assertFalse(os.path.exists(os.path.join(d, "www", "server_host.txt")))

    def test_connect_is_gone(self):
        d = self.plain("no-connect")
        self.dirai(d, "init")
        out = self.dirai(d, "connect")
        self.assertNotEqual(out.returncode, 0)
        self.assertNotIn("dirai-", out.stdout)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


if __name__ == "__main__":
    unittest.main()
