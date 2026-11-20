"""remotes.py: a chain of three servers on this machine (a -> b -> c), linked by tests/fake_ssh.py.

Checks that a's list shows b's and c's agents, that a's forwarders open b's and c's pages as the
owner with only a's cookie, and that nothing passes without it."""
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

from tests import util

import remotes

FAKE_SSH = os.path.join(util.TOOL, "tests", "fake_ssh.py")
HOSTS = os.path.join(util.TMP, "fake_hosts")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def get(port, path, cookie=None, data=None):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=data)
    if cookie:
        req.add_header("Cookie", cookie)
    if data is not None:
        req.add_header("X-Review", "1")
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


class Machine:
    """One fake machine: its config dir (owner key, trees), ssh config and one running tree."""

    def __init__(self, name, ssh_hosts=()):
        self.name = name
        self.config = os.path.join(util.TMP, "cfg-" + name)
        self.root = util.new_tree("tree-" + name)
        self.port = free_port()
        util.write(os.path.join(self.root, "www", "dirai.json"), json.dumps({"port": self.port}))
        util.write(os.path.join(self.root, name + "1", "index.html"),
                   "<html><head><title>%s one</title></head><body><p>on %s</p></body></html>" % (name, name))
        util.write(os.path.join(self.config, "trees"), self.root + "\n")
        util.write(os.path.join(self.root, "www", "server_host.txt"),
                   "%s nojob 2026-10-24 12:00:00 1 reload %d\n" % (name, self.port))
        self.ssh_config = os.path.join(util.TMP, "ssh-" + name)
        util.write(self.ssh_config, "Host *\n  User x\n" + "".join("Host %s\n  HostName %s.example\n" % (h, h) for h in ssh_hosts))
        self.env = dict(os.environ, DIRAI_CONFIG_DIR=self.config, DIRAI_MACHINE_NAME=name, DIRAI_SSH=FAKE_SSH,
                        DIRAI_SSH_CONFIG=self.ssh_config, FAKE_SSH_HOSTS=HOSTS, HOME=os.path.join(util.TMP, "home-" + name),
                        PATH=os.path.join(util.TOOL, "bin") + os.pathsep + os.environ["PATH"])
        # how the machine upstream "logs in" here
        util.write(os.path.join(HOSTS, "fake" + name + ".json"),
                   json.dumps({k: self.env[k] for k in ("DIRAI_CONFIG_DIR", "DIRAI_MACHINE_NAME", "HOME", "PATH",
                                                        "DIRAI_SSH", "DIRAI_SSH_CONFIG")}))
        subprocess.run([sys.executable, os.path.join(util.LIB, "agent_list.py"), self.root],
                       stdout=subprocess.DEVNULL, check=True, env=self.env)
        self.log = open(os.path.join(util.TMP, "server-%s.log" % name), "w")
        self.proc = subprocess.Popen([sys.executable, os.path.join(util.LIB, "server.py"), self.root,
                                      str(self.port), "127.0.0.1"], stdout=self.log, stderr=self.log, env=self.env)
        for _ in range(100):
            try:
                get(self.port, "/www/index.html")
                break
            except OSError:
                time.sleep(0.1)
        with open(os.path.join(self.config, "key")) as f:
            self.key = f.read().strip()
        self.cookie = "review_key=" + self.key

    def api(self, body=None):
        code, out = get(self.port, "/_review/remotes", self.cookie, json.dumps(body).encode() if body else None)
        assert code == 200, (code, out)
        return json.loads(out)

    def stop(self):
        self.proc.terminate()
        self.proc.wait(15)
        self.log.close()


def wait_for(fn, timeout=60, what="condition"):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.5)
    raise AssertionError("timed out waiting for " + what)


class SshConfig(unittest.TestCase):
    def test_hosts_include_and_patterns(self):
        main = os.path.join(util.TMP, "sshcfg", "config")
        util.write(main, "Include conf.d/*\nHost nas nas-ts *.lan !x\n  User me\nHost=negishi # cluster\n")
        util.write(os.path.join(util.TMP, "sshcfg", "conf.d", "a"), "Host gilbreth\nHost nas\n")
        self.assertEqual(remotes.ssh_hosts(main), ["gilbreth", "nas", "nas-ts", "negishi"])

    def test_agent_rows(self):
        page = ('<tr><td data-v="a/b/"><a href="../a/b/index.html">a/b/</a><div class="sub">T &amp; U</div></td>'
                '<td class="num" data-v="1700000000.5">x</td></tr>'
                '<tr><td data-v="(top)"><a href="../index.html">(top)</a></td><td class="num" data-v="17">x</td></tr>')
        rows = remotes.agent_rows(page, {"a/b": {"status": "unread", "asking": True, "inbox": 2}})
        self.assertEqual({k: rows[0][k] for k in ("dir", "title", "mtime", "status", "asking", "inbox", "fav")},
                         {"dir": "a/b", "title": "T & U", "mtime": 1700000000.5, "status": "unread", "asking": True,
                          "inbox": 2, "fav": False})
        self.assertEqual(rows[1]["dir"], "")
        self.assertEqual([r["fav"] for r in remotes.agent_rows(page, {}, {""})], [False, True])

    def test_parse_home(self):
        self.assertEqual(remotes.parse_home("8080 KuaMacAirM4"), (8080, "KuaMacAirM4"))
        for bad in (None, "", "0 a", "70000 a", "80", "80 a b", '80 "x"', "80 <b>", "x 80"):
            self.assertIsNone(remotes.parse_home(bad), bad)

    def test_agent_rows_keep_whole_row(self):
        # the size and token cells come along as the row's own HTML; anything with markup in it doesn't
        row = ('<tr><td data-v="a/"><a href="../a/index.html">a/</a></td><td class="num" data-v="17">x</td>'
               '<td class="num" data-v="2048" title="measured 2026-10-25 10:00">2.0K</td>'
               '<td class="num" data-v="5" title="1 session&#10;input 5">5</td></tr>')
        bad = ('<tr><td data-v="b/"><a href="../b/index.html">b/</a><div class="sub"><img src=x onerror=alert(1)></div></td>'
               '<td class="num" data-v="17">x</td></tr>')
        rows = remotes.agent_rows(row + "\n" + bad, {})
        self.assertEqual(rows[0]["row"], row)
        self.assertNotIn("row", rows[1])
        self.assertEqual(remotes.relayed_rows([rows[0], dict(rows[0], row=bad)])[1].get("row"), None)


class DeadServer(unittest.TestCase):
    """A server_host.txt whose server is gone (died without DirAI stop) is reported down, with why."""

    def setUp(self):
        self.cfg = os.path.join(util.TMP, "cfg-dead")
        self.saved = remotes.dirai_config.TREES_FILE, remotes.dirai_config.KEY_FILE
        remotes.dirai_config.TREES_FILE = os.path.join(self.cfg, "trees")
        remotes.dirai_config.KEY_FILE = os.path.join(self.cfg, "key")

    def tearDown(self):
        remotes.dirai_config.TREES_FILE, remotes.dirai_config.KEY_FILE = self.saved

    def test_server_gone(self):
        here = socket.gethostname().split(".")[0]
        p = subprocess.Popen(["true"])
        p.wait()                                       # a pid that no longer exists
        f = lambda node, job, pid: [node, job, "2026-01-01", "00:00:00", str(pid), "reload", "8765"]
        self.assertEqual(remotes.server_gone(f(here, "nojob", p.pid), {}), "pid %d is gone" % p.pid)
        self.assertIsNone(remotes.server_gone(f(here, "nojob", os.getpid()), {}))
        self.assertIsNone(remotes.server_gone(f("othernode", "nojob", p.pid), {}))     # can't tell from here
        self.assertEqual(remotes.server_gone(f("a019", "812345", 1), {"812345": "TIMEOUT"}), "job 812345 ended (TIMEOUT)")
        self.assertEqual(remotes.server_gone(f("a019", "812345", 1), {"812345": "CANCELLED by 123"}),
                         "job 812345 ended (CANCELLED)")
        self.assertIsNone(remotes.server_gone(f("a019", "812345", 1), {"812345": "RUNNING"}))
        self.assertIsNone(remotes.server_gone(f("a019", "812345", 1), {}))            # no sacct answer

    def test_machine_report(self):
        here = socket.gethostname().split(".")[0]
        p = subprocess.Popen(["true"])
        p.wait()
        dead, live = util.new_tree("tree-dead"), util.new_tree("tree-live")
        for root, pid in ((dead, p.pid), (live, os.getpid())):
            util.write(os.path.join(root, "www", "server_host.txt"), "%s nojob 2026-01-01 00:00:00 %d reload 8765\n" % (here, pid))
        util.write(remotes.dirai_config.TREES_FILE, dead + "\n" + live + "\n")
        trees = {t["root"]: t for t in remotes.machine_report()["trees"]}
        self.assertFalse(trees[dead]["running"])
        self.assertEqual(trees[dead]["last"], "%s: pid %d is gone" % (here, p.pid))
        self.assertFalse(os.path.exists(os.path.join(dead, "www", "server_host.txt")))
        self.assertTrue(trees[live]["running"])
        self.assertNotIn("last", trees[live])
        self.assertTrue(os.path.exists(os.path.join(live, "www", "server_host.txt")))


class Chain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # a machine with no DirAI at all (only system commands on PATH): DirAI is copied there on Connect
        util.write(os.path.join(HOSTS, "fakenew.json"), json.dumps({
            "HOME": os.path.join(util.TMP, "home-new"), "DIRAI_CONFIG_DIR": os.path.join(util.TMP, "home-new", "cfg"),
            "DIRAI_MACHINE_NAME": "new", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}))
        cls.c = Machine("c")
        cls.b = Machine("b", ["fakec"])
        cls.a = Machine("a", ["fakeb", "fakec", "fakenew"])

    @classmethod
    def tearDownClass(cls):
        for m in (cls.a, cls.b, cls.c):
            m.stop()

    def tree(self, report, tid):
        return next((t for t in report["trees"] if t["id"] == tid), None)

    def test_chain(self):
        a, b, c = self.a, self.b, self.c
        # nothing is contacted before Connect; only hosts of a's ssh config can be enabled
        rep = a.api()
        self.assertEqual([(h["alias"], h["state"]) for h in rep["hosts"]], [("fakeb", "off"), ("fakec", "off"), ("fakenew", "off")])
        self.assertEqual(rep["trees"], [])
        self.assertIn("error", a.api({"op": "enable", "host": "evil; rm -rf ~"}))
        # non-owners get nothing
        self.assertEqual(get(a.port, "/_review/remotes")[0], 404)
        self.assertEqual(get(a.port, "/_review/remotes", b.cookie)[0], 404)

        self.assertEqual(a.api({"op": "enable", "host": "fakeb"}), {"ok": True})
        bid = "fakeb:" + b.root
        tb = wait_for(lambda: (lambda t: t if t and t["state"] == "alive" and t["fport"] else None)(
            self.tree(a.api(), bid)), what="b alive on a's list")
        self.assertEqual([r["dir"] for r in tb["agents"]], ["b1"])
        self.assertEqual(tb["machine"], "fakeb")
        # b's Claude usage, read from b (no login in the test: an error, but read); and a's own
        self.assertTrue(isinstance(tb["usage"], dict) and ("error" in tb["usage"] or "session" in tb["usage"]))
        self.assertIn("usage", a.api())
        self.assertTrue(isinstance(tb["load"], dict) and ("cpus" in tb["load"] or "error" in tb["load"]))   # b's node load
        # Restart of this server: here server.py runs without its dirai_serve wrapper, so it refuses
        self.assertIn("error", a.api({"op": "restart"}))

        # a's forwarder for b: b's page as the owner (panel), with a's cookie only
        code, page = get(tb["fport"], "/b1/", a.cookie)
        self.assertEqual(code, 200)
        self.assertIn("/_review/panel.js", page)
        self.assertEqual(get(tb["fport"], "/b1/")[0], 404)                 # no cookie
        self.assertEqual(get(tb["fport"], "/b1/", b.cookie)[0], 404)       # b's own key is not a's
        self.assertEqual(get(tb["fport"], "/b1/", "review_key=nope")[0], 404)

        # Add downstream of b, from a's list: b enables fakec from b's ssh config
        self.assertEqual(a.api({"op": "enable", "host": "fakec", "at": bid}), {"ok": True})
        cid = "fakeb/fakec:" + c.root
        tc = wait_for(lambda: (lambda t: t if t and t["state"] == "alive" and t["fport"] and t["agents"] else None)(
            self.tree(a.api({"op": "refresh"}) and a.api(), cid)), timeout=90, what="c on a's list through b")
        self.assertEqual([r["dir"] for r in tc["agents"]], ["c1"])
        self.assertEqual(tc["via"], ["fakeb", "fakec"])
        # two hops, each swapping keys: a's cookie opens c's page as the owner
        code, page = get(tc["fport"], "/c1/", a.cookie)
        self.assertEqual(code, 200)
        self.assertIn("/_review/panel.js", page)
        # Home leads to a's list (the first hop wins); a page opened on c directly is unchanged
        self.assertIn('href="http://127.0.0.1:%d/www/index.html"' % a.port, page)
        self.assertIn(">c: ", page)     # the machine the page is on, in its corner
        code, direct = get(c.port, "/c1/", c.cookie)
        self.assertIn('href="/www/index.html"', direct)
        self.assertNotIn("http://127.0.0.1:%d/www/index.html" % a.port, direct)
        # c's own list, opened through the chain, has Home to a's; a malformed header is ignored
        code, lst = get(tc["fport"], "/www/index.html", a.cookie)
        self.assertIn('href="http://127.0.0.1:%d/www/index.html"' % a.port, lst)
        req = urllib.request.Request("http://127.0.0.1:%d/c1/" % c.port,
                                     headers={"Cookie": c.cookie, "X-DirAI-Home": '1 "><script>x</script>'})
        with urllib.request.urlopen(req, timeout=10) as r:
            bad = r.read().decode()
        self.assertNotIn("<script>x", bad)
        self.assertIn('href="/www/index.html"', bad)
        self.assertEqual(get(tc["fport"], "/c1/")[0], 404)
        self.assertEqual(get(tc["fport"], "/c1/", c.cookie)[0], 404)
        # b's forwarder for c checks b's key: a's key there gets nothing
        bc = self.tree(b.api(), "fakec:" + c.root)
        self.assertEqual(get(bc["fport"], "/c1/", a.cookie)[0], 404)
        self.assertEqual(get(bc["fport"], "/c1/", b.cookie)[0], 200)
        # one tree, one id, whichever route reports it: c's tree as b sees it directly and as a sees it through b
        self.assertRegex(bc["tree_id"], r"^[0-9a-f]{16}$")
        self.assertEqual(tc["tree_id"], bc["tree_id"])
        self.assertNotEqual(tc["tree_id"], tb["tree_id"])

        # a request that has already passed through a machine gets nothing from it (cycles)
        req = urllib.request.Request("http://127.0.0.1:%d/_review/remotes" % b.port,
                                     headers={"Cookie": b.cookie, remotes.VIA: "a,b"})
        with urllib.request.urlopen(req, timeout=10) as r:
            self.assertEqual(json.loads(r.read())["trees"], [])

        # a machine without DirAI: Connect copies a's DirAI to ~/.local/share/dirai there, then lists it
        self.assertEqual(a.api({"op": "enable", "host": "fakenew"}), {"ok": True})
        hn = wait_for(lambda: next((h for h in a.api()["hosts"] if h["alias"] == "fakenew" and h.get("state") == "up"), None),
                      timeout=120, what="DirAI copied to fakenew")
        home = os.path.join(util.TMP, "home-new")
        inst = os.path.join(home, ".local", "share", "dirai")
        self.assertEqual(hn["tool"], os.path.realpath(inst))
        self.assertFalse(hn["behind"])        # same files: same build
        self.assertEqual(hn["build"], remotes.build_id())
        self.assertFalse(os.path.exists(os.path.join(inst, ".git")))
        self.assertFalse(os.path.exists(os.path.join(inst, "tests")))
        self.assertTrue(os.path.islink(os.path.join(home, ".local", "bin", "DirAI")))
        self.assertIn("DirAI copied to", hn["note"])
        # Update copies it again; the previous copy is kept for a roll back
        self.assertEqual(a.api({"op": "update", "host": "fakenew"}), {"ok": True})
        wait_for(lambda: os.path.isdir(inst + ".old"), what="second copy")
        # relayed down, a server holding another build refuses
        self.assertIn("error", b.api({"op": "update", "host": "fakec", "build": "000000000000"}))

        # hide is this list's view only
        self.assertEqual(a.api({"op": "hide", "tree": cid}), {"ok": True})
        self.assertTrue(self.tree(a.api(), cid)["hidden"])
        self.assertFalse(self.tree(b.api(), "fakec:" + c.root)["hidden"])
        self.assertFalse(a.api()["hidden"])
        self.assertEqual(a.api({"op": "hide", "tree": ""}), {"ok": True})     # this server's own agents
        self.assertTrue(a.api()["hidden"])

        # favorites are each server's own: a star on a's list, two hops down, lands in c's favorites.json
        self.assertTrue(a.api({"op": "call", "tree": cid, "path": "favorite", "data": {"agent": "c1", "on": True}})["ok"])
        self.assertEqual(json.loads(get(c.port, "/_review/favorites", c.cookie)[1]), ["c1"])
        # c's pause level and usage history, set and read from a's list, two hops down
        out = a.api({"op": "call", "tree": cid, "path": "usage_stop", "data": {"name": "session", "percent": 42}})
        self.assertEqual(out["stop"]["session"], 42)
        self.assertEqual(json.loads(get(c.port, "/_review/usage", c.cookie)[1])["stop"]["session"], 42)
        self.assertIn("samples", a.api({"op": "call", "tree": cid, "path": "usage_history"}))
        self.assertIn("error", a.api({"op": "call", "tree": cid, "path": "comment", "data": {}}))
        # an agent's summary card (the Tree tab's hover) through two hops: a GET with the agent in its query
        card = a.api({"op": "call", "tree": cid, "path": "card", "data": {"agent": "c1"}})
        self.assertIsInstance(card, dict)
        self.assertNotIn("error", card)
        self.assertIn("error", a.api({"op": "call", "tree": cid, "path": "card", "data": {"agent": "nope"}}) or {"error": 1})
        # New agent in c's tree from a's list (proposal 68): c's folders suggested, c's server checks the folder
        self.assertEqual(a.api({"op": "call", "tree": cid, "path": "dirs", "data": {"prefix": "c"}}), ["c1/"])   # www/ never offered
        bad = a.api({"op": "call", "tree": cid, "path": "new", "data": {"dir": "../x", "task": "t", "every": "off"}})
        self.assertIn("inside the tree", bad["error"])
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(c.root), "x")))
        self.assertIn("task", a.api({"op": "call", "tree": cid, "path": "new", "data": {"dir": "c2", "task": ""}})["error"])
        self.assertTrue(self.tree(a.api(), cid)["agents"][0]["fav"])
        # and one starred on b itself shows on a's list at the next poll
        get(b.port, "/_review/favorite", b.cookie, json.dumps({"agent": "b1", "on": True}).encode())
        wait_for(lambda: self.tree(a.api({"op": "refresh"}) and a.api(), bid)["agents"][0]["fav"], what="b's star on a")
        self.assertIn("error", a.api({"op": "call", "tree": "nope", "path": "favorite", "data": {"agent": "x", "on": True}}))

        # New tree on c, from a's list through b: init + start there, then listed
        new = os.path.join(util.TMP, "tree-c-new")
        self.assertIn("error", a.api({"op": "new", "host": "fakec", "at": bid, "path": "rel/x"}))
        self.assertIn("error", a.api({"op": "new", "host": "fakec", "at": bid, "path": new + "/../x"}))
        self.assertIn("error", a.api({"op": "new", "host": "fakec", "at": bid, "path": new, "node": "a;b"}))
        try:
            self.assertEqual(a.api({"op": "new", "host": "fakec", "at": bid, "path": new}), {"ok": True})
            nid = "fakeb/fakec:" + os.path.realpath(new)
            # listed and running (not "alive" here: its real server records this Mac's hostname as its node,
            # not the fake name c, so b would reach it through another node, which fake_ssh can't do)
            t = wait_for(lambda: (lambda t: t if t and t["running"] else None)(self.tree(a.api({"op": "refresh"}) and a.api(), nid)),
                         timeout=90, what="new tree on c")
            self.assertTrue(os.path.isfile(os.path.join(new, "www", "dirai.json")))
            # inside an existing tree: refused there, with the reason as the machine's note
            self.assertEqual(a.api({"op": "new", "host": "fakec", "at": bid, "path": os.path.join(c.root, "sub")}), {"ok": True})
            wait_for(lambda: "inside the DirAI tree" in next(h for h in self.tree(a.api({"op": "refresh"}) and a.api(), bid)["hosts"]
                                                           if h["alias"] == "fakec").get("note", ""), what="refusal note")
            self.assertFalse(os.path.exists(os.path.join(c.root, "sub", "www")))
            # Stop, relayed through b to c: DirAI stop runs there and the server goes
            self.assertIn("error", a.api({"op": "stop", "tree": "nope"}))
            self.assertEqual(a.api({"op": "stop", "tree": nid}), {"ok": True})
            wait_for(lambda: not os.path.exists(os.path.join(new, "www", "server_host.txt")), what="new tree stopped")
            # Forget, relayed the same way: DirAI forget runs on c, the tree leaves a's list, the folder stays,
            # and the outcome is fakec's note on b
            self.assertIn("error", a.api({"op": "forget", "tree": "nope"}))
            self.assertEqual(a.api({"op": "forget", "tree": nid}), {"ok": True})
            wait_for(lambda: not self.tree(a.api({"op": "refresh"}) and a.api(), nid), timeout=60, what="new tree forgotten")
            self.assertTrue(os.path.isfile(os.path.join(new, "www", "dirai.json")))
            wait_for(lambda: "Forgot " + os.path.realpath(new) in next(h for h in self.tree(a.api({"op": "refresh"}) and a.api(), bid)["hosts"]
                                                                      if h["alias"] == "fakec").get("note", ""), what="forget note")
            # this list's own tree, seen from a server it links: no stop or forget of itself
            self.assertIn("tree_id", a.api())
        finally:
            subprocess.run([os.path.join(util.TOOL, "bin", "DirAI"), "-C", new, "stop"], env=c.env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    unittest.main()
