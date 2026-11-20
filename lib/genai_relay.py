"""A relay on this node's loopback between claude and Purdue RCAC's GenAI Studio, for the agents on
GenAI Studio models (agents.GENAI_MODELS).

GenAI Studio allows RPM requests a minute per user. claude sends requests as fast as its tool loop
goes, so every request goes through here, and one that would go over the limit waits until the
oldest of the last RPM is a minute old. The count is kept in SENT_FILE, shared by every DirAI server
of the user (one per tree, on any node: it is on the NFS home) under a lock. Over the limit, GenAI
Studio answers with a JSON `null`, 429, or 400 "Rate limit exceeded": such a request is sent again
after a minute, up to RETRIES times.

claim() is the other half: one agent of the user's at a time on GenAI Studio, across all trees.

The relay also puts the API key in, so claude (and the agent's commands) never see it: claude gets
the relay's URL and a token made for this server run, and anything without the token gets 401.
The key file is read per request, so a new key works without a restart.
"""
import fcntl
import http.client
import http.server
import json
import os
import secrets
import socketserver
import threading
import time
from urllib.parse import urlsplit

import dirai_config

SENT_FILE = os.path.join(dirai_config.CONFIG_DIR, "genai_sent.json")
RUN_LOCK = os.path.join(dirai_config.CONFIG_DIR, "genai_run.lock")
RPM = int(os.environ.get("DIRAI_GENAI_RPM", "20"))
WINDOW_S = 60
RETRIES = 3
TIMEOUT_S = 600
# not passed on: hop-by-hop, the credentials (replaced), compression (relayed as it comes), and the
# headers this server sends itself
DROP = {"connection", "keep-alive", "proxy-connection", "te", "upgrade", "transfer-encoding",
        "content-length", "host", "authorization", "x-api-key", "accept-encoding", "date", "server"}


class Limiter:
    """At most rpm requests in any WINDOW_S seconds, counted in path (every process using it)."""

    def __init__(self, rpm, path=SENT_FILE, clock=time.time, sleep=time.sleep):
        self.rpm, self.path, self.clock, self.sleep = rpm, path, clock, sleep
        self.lock = threading.Lock()

    def wait(self):
        """Block until one more request fits, and count it: the seconds waited."""
        waited = 0
        with self.lock:     # one waiter at a time here, so requests go out in the order they came
            while True:
                pause = self._take()
                if not pause:
                    return waited
                self.sleep(pause)
                waited += pause

    def _take(self):
        """Count a request now if it fits (0), else the seconds until one might."""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "a+") as f:
            fcntl.lockf(f, fcntl.LOCK_EX)    # released on close
            f.seek(0)
            try:
                sent = json.loads(f.read() or "[]")
            except ValueError:
                sent = []
            now = self.clock()
            sent = sorted(t for t in sent if isinstance(t, (int, float)) and now - WINDOW_S < t <= now + 1)
            if len(sent) >= self.rpm:
                return max(sent[-self.rpm] + WINDOW_S - now, 0.1)
            f.seek(0)
            f.truncate()
            f.write(json.dumps(sent + [now]))
            return 0

    def recent(self):
        """Requests counted in the last WINDOW_S seconds (by every process)."""
        try:
            with open(self.path) as f:
                return sum(1 for t in json.loads(f.read() or "[]") if t > self.clock() - WINDOW_S)
        except (OSError, ValueError):
            return 0


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


class Relay:
    def __init__(self, upstream, key, rpm=RPM, sent_file=SENT_FILE):
        """upstream: GenAI Studio's API base URL; key(): the API key."""
        self.upstream, self.key = urlsplit(upstream), key
        self.token = secrets.token_hex(16)
        self.limiter = Limiter(rpm, sent_file)
        self.retry_wait_s = WINDOW_S
        relay = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                relay.forward(self)

            def do_POST(self):
                relay.forward(self)

            def log_message(self, *args):
                pass

        self.httpd = Server(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def authorized(self, headers):
        given = headers.get("x-api-key") or (headers.get("Authorization") or "").replace("Bearer ", "", 1)
        return secrets.compare_digest(given.encode(), self.token.encode())

    def forward(self, req):
        if not self.authorized(req.headers):
            return self.error(req, 401, "authentication_error", "not this relay's token")
        body = req.rfile.read(int(req.headers.get("Content-Length") or 0))
        headers = {k: v for k, v in req.headers.items() if k.lower() not in DROP}
        path = self.upstream.path.rstrip("/") + req.path
        for attempt in range(RETRIES + 1):
            try:
                headers["Authorization"] = "Bearer " + self.key()
                self.limiter.wait()
                conn = (http.client.HTTPSConnection if self.upstream.scheme == "https" else
                        http.client.HTTPConnection)(self.upstream.hostname, self.upstream.port, timeout=TIMEOUT_S)
                conn.request(req.command, path, body, headers)
                resp = conn.getresponse()
            except (OSError, http.client.HTTPException) as e:
                return self.error(req, 502, "api_error", "GenAI Studio relay: %s" % e)
            try:
                if "text/event-stream" in (resp.getheader("Content-Type") or ""):
                    return self.stream(req, resp)
                data = resp.read()
            except (OSError, http.client.HTTPException) as e:
                return self.error(req, 502, "api_error", "GenAI Studio relay: %s" % e)
            finally:
                conn.close()
            if over_limit(resp.status, data) and attempt < RETRIES:
                time.sleep(self.retry_wait_s)   # over the limit (someone else's use counts too)
                continue
            return self.send(req, resp, data)

    @staticmethod
    def send(req, resp, data):
        req.send_response(resp.status)
        for k, v in resp.getheaders():
            if k.lower() not in DROP:
                req.send_header(k, v)
        req.send_header("Content-Length", str(len(data)))
        req.end_headers()
        req.wfile.write(data)

    @staticmethod
    def stream(req, resp):
        """Pass server-sent events on as they come; the end of the stream closes the connection."""
        req.send_response(resp.status)
        for k, v in resp.getheaders():
            if k.lower() not in DROP:
                req.send_header(k, v)
        req.end_headers()
        try:
            while True:
                chunk = resp.read1(65536)
                if not chunk:
                    break
                req.wfile.write(chunk)
                req.wfile.flush()
        except (OSError, http.client.HTTPException):
            pass    # claude went away (Cancel), or the stream broke off: claude retries that

    @staticmethod
    def error(req, status, kind, message):
        data = json.dumps({"type": "error", "error": {"type": kind, "message": message}}).encode()
        req.send_response(status)
        req.send_header("Content-Type", "application/json")
        req.send_header("Content-Length", str(len(data)))
        req.end_headers()
        req.wfile.write(data)


def over_limit(status, data):
    return status == 429 or data.strip() == b"null" or (status == 400 and b"Rate limit exceeded" in data)


def claim(path=RUN_LOCK):
    """Become the one agent running on GenAI Studio: an open file holding the lock (close it when
    the run ends; the lock also goes when the process does), or None if another process has it."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    f = open(path, "a")
    try:
        fcntl.lockf(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except OSError:
        f.close()
        return None


_relay = None
_lock = threading.Lock()


def shared(upstream, key):
    """The relay of this server process, started on first use."""
    global _relay
    with _lock:
        if _relay is None:
            _relay = Relay(upstream, key)
        return _relay
