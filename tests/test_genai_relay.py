"""genai_relay: the rate limiter, and the relay against a stand-in for GenAI Studio on loopback."""
import http.client
import http.server
import json
import os
import subprocess
import sys
import threading
import unittest
from urllib.parse import urlsplit

from tests import util

import genai_relay


class LimiterTest(unittest.TestCase):
    def test_waits_for_the_oldest_to_be_a_minute_old(self):
        t, slept = [100.0], []

        def sleep(s):
            slept.append(s)
            t[0] += s
        lim = genai_relay.Limiter(3, os.path.join(util.TMP, "sent1.json"), clock=lambda: t[0], sleep=sleep)
        for _ in range(3):
            self.assertEqual(lim.wait(), 0)
            t[0] += 1
        self.assertEqual(lim.wait(), 57)        # first went at 100, now 103: wait until 160
        self.assertEqual(t[0], 160)
        t[0] = 300
        self.assertEqual(lim.wait(), 0)         # all old by now
        self.assertEqual(slept, [57])

    def test_count_is_shared_by_processes(self):
        path = os.path.join(util.TMP, "sent2.json")
        code = "import sys; sys.path.insert(0, %r); import genai_relay; genai_relay.Limiter(5, %r).wait()" % (util.LIB, path)
        for _ in range(2):
            subprocess.run([sys.executable, "-c", code], check=True)
        lim = genai_relay.Limiter(5, path)
        self.assertEqual(lim.recent(), 2)
        lim.wait()
        self.assertEqual(lim.recent(), 3)

    def test_claim_is_one_process_at_a_time(self):
        path = os.path.join(util.TMP, "run.lock")
        code = "import sys; sys.path.insert(0, %r); import genai_relay; print(genai_relay.claim(%r) is not None)" % (util.LIB, path)
        held = genai_relay.claim(path)
        self.assertTrue(held)
        other = subprocess.run([sys.executable, "-c", code], stdout=subprocess.PIPE, universal_newlines=True)
        self.assertEqual(other.stdout.strip(), "False")
        held.close()
        other = subprocess.run([sys.executable, "-c", code], stdout=subprocess.PIPE, universal_newlines=True)
        self.assertEqual(other.stdout.strip(), "True")


class Upstream(http.server.BaseHTTPRequestHandler):
    """Answers /api/v1/messages: `null` while Upstream.nulls > 0, else SSE or JSON."""
    seen, nulls = [], 0

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Upstream.seen.append((self.path, self.headers.get("Authorization"), self.headers.get("x-api-key")))
        if Upstream.nulls:
            Upstream.nulls -= 1
            data, kind = b"null", "application/json"
        elif body.get("stream"):
            data, kind = b"event: message_start\ndata: {}\n\nevent: message_stop\ndata: {}\n\n", "text/event-stream"
        else:
            data, kind = json.dumps({"type": "message", "content": [{"type": "text", "text": "hi"}]}).encode(), \
                "application/json"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class RelayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.up = http.server.HTTPServer(("127.0.0.1", 0), Upstream)
        threading.Thread(target=cls.up.serve_forever, daemon=True).start()
        cls.relay = genai_relay.Relay("http://127.0.0.1:%d/api" % cls.up.server_address[1], lambda: "KEY", rpm=100,
                                      sent_file=os.path.join(util.TMP, "sent3.json"))
        cls.relay.retry_wait_s = 0

    @classmethod
    def tearDownClass(cls):
        cls.up.shutdown()
        cls.relay.httpd.shutdown()

    def setUp(self):
        Upstream.seen, Upstream.nulls = [], 0

    def post(self, body, token=None):
        u = urlsplit(self.relay.url)
        conn = http.client.HTTPConnection(u.hostname, u.port, timeout=10)
        conn.request("POST", "/v1/messages", json.dumps(body),
                     {"Content-Type": "application/json", "Authorization": "Bearer " + (token or self.relay.token)})
        r = conn.getresponse()
        return r.status, r.getheader("Content-Type"), r.read()

    def test_puts_the_key_in(self):
        status, _, data = self.post({"model": "m"})
        self.assertEqual((status, json.loads(data)["content"][0]["text"]), (200, "hi"))
        self.assertEqual(Upstream.seen, [("/api/v1/messages", "Bearer KEY", None)])

    def test_refuses_without_the_token(self):
        status, _, data = self.post({"model": "m"}, token="wrong")
        self.assertEqual((status, json.loads(data)["error"]["type"]), (401, "authentication_error"))
        self.assertEqual(Upstream.seen, [])

    def test_over_limit_answers(self):
        self.assertTrue(genai_relay.over_limit(400, b'{"detail":"Rate limit exceeded. Please try again later."}'))
        self.assertTrue(genai_relay.over_limit(200, b"null"))
        self.assertFalse(genai_relay.over_limit(400, b'{"detail":"bad request"}'))

    def test_sends_again_after_null(self):
        Upstream.nulls = 2
        status, _, data = self.post({"model": "m"})
        self.assertEqual((status, len(Upstream.seen)), (200, 3))
        self.assertIn(b"hi", data)

    def test_streams(self):
        status, kind, data = self.post({"model": "m", "stream": True})
        self.assertEqual((status, kind), (200, "text/event-stream"))
        self.assertTrue(data.startswith(b"event: message_start") and data.endswith(b"message_stop\ndata: {}\n\n"))


if __name__ == "__main__":
    unittest.main()
