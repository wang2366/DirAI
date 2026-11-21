#!/usr/bin/env python3
"""Downstream machines: the DirAI servers on hosts from this machine's ~/.ssh/config, listed on this
tree's agent list and opened through it (design: improvement/remote-machines/index.html).

  remotes.py --list     what `DirAI list --json` prints: this machine's trees and owner key, for the
                        server upstream that reaches it over ssh

This tree's choices are in www/machines.json: {"hosts": {"nas": {"enabled": true}}, "hidden": [tree ids]}.
Nothing is contacted until a host is enabled (Connect on the agent list). Then, every POLL_S:
- one ssh ControlMaster per enabled host runs `DirAI list --json` there: its trees and its owner key;
- each running tree gets a tunnel, 127.0.0.1:<tport> here to the tree server's own 127.0.0.1 (through
  the tree's node with -W when ssh lands on another node), so that server sees 127.0.0.1;
- each tree gets a forwarder, 127.0.0.1:<fport> here, which the browser opens (one origin per tree,
  as with a plain tunnel). It passes on only requests carrying this machine's owner cookie, with the
  cookie swapped for the next machine's key; anything else gets 404.
- the tree's agent rows (its www/index.html and /_review/all) and its own downstream trees
  (/_review/remotes) are read through the tunnel. For a tree further down the chain (Mac -> NAS ->
  cluster) the tunnel ends on the NAS server's forwarder for it, which checks the NAS key and swaps
  it for the cluster's: each hop adds the next key only to owner requests.
"""
import hashlib
import html as htmllib
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http import cookies

import dirai_config

SSH = os.environ.get("DIRAI_SSH", "ssh")    # tests: tests/fake_ssh.py
SSH_CONFIG = os.path.expanduser(os.environ.get("DIRAI_SSH_CONFIG", "~/.ssh/config"))
CTL_DIR = os.path.join(dirai_config.CONFIG_DIR, "ssh")    # ControlMaster sockets (paths must stay short)
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "LogLevel=ERROR", "-o", "ConnectTimeout=10"]
# the remote shell may not have ~/.local/bin (install.sh's link) on its PATH
LIST_CMD = 'PATH="$HOME/.local/bin:$PATH" DirAI list --json'
# what op "call" may ask of a remote tree's server (/_review/<path>), and how
# dirs/new: New agent in another tree (proposal 68); that tree's own server still checks the folder (clean_rel)
CALLS = {"favorite": "POST", "usage_stop": "POST", "usage_history": "GET", "card": "GET",
         "dirs": "GET", "new": "POST", "engine": "POST",
         "share": "POST"}     # proposal 72 (D8): connect, fetch or disconnect a shared repo on that tree
POLL_S = 30
# while this server's report was asked for lately (an open agent list, or the server upstream polling it,
# which is itself watched), poll every POLL_WATCHED_S: down a chain each hop adds up to one poll of delay
POLL_WATCHED_S, WATCHED_S = 10, 60
HTTP_TIMEOUT = 5
HOME = b"X-DirAI-Home"   # "<port> <machine>" of the server the browser came from (set by its forwarder)
VIA = "X-DirAI-Via"    # the machines a /_review/remotes request has passed through (stops cycles)
ALIAS_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.@-]*$")
ROW_RE = re.compile(r'<tr><td data-v="[^"]*"><a href="\.\./([^"]*?)index\.html">[^<]*</a>'
                    r'(?:<div class="sub">(.*?)</div>)?</td><td class="num" data-v="(\d+(?:\.\d+)?)">')
TR_RE = re.compile(r"<tr><td data-v=.*?</tr>")
# a whole row exactly as agent_list.py writes it (escaped text, plain attributes, number cells): the
# top server's list shows such a row as is, so a tree's agents there have the same columns as at home
ROW_FULL_RE = re.compile(r'<tr><td data-v="[^"<>]*"><a href="[^"<>]*">[^<>]*</a>(?:<div class="sub">[^<>]*</div>)?</td>'
                         r'(?:<td class="num" data-v="-?\d+(?:\.\d+)?"(?: title="[^"<>]*")?>[^<>]*</td>)+</tr>')
# what the list shows of an agent's chat (agents.all_status)
STATUS_KEYS = ("status", "asking", "denied", "inbox", "requests", "schedule", "schedules", "card", "context")


# DirAI on every downstream machine lives in one fixed place, INSTALL_DIR, never a git checkout: the
# upstream server copies its own DirAI files there over the ssh link (a tar stream, like scp), so no
# machine needs GitHub access. The files are SHIP under this server's DirAI folder; BUILD in the
# copy names them (a hash of their contents, plus the upstream's git commit for people).
INSTALL_DIR = "~/.local/share/dirai"
# Not README.md: nothing reads it there (the README is docs/README.md; a link to it at the top would
# ship as a broken link, left out of the remote's build id, so the ids would never match).
SHIP = ("bin", "lib", "web", "scripts", "install.sh", "AGENT_RULE.md", "LICENSE")
BUILD_FILE = "BUILD"
# Unpacks the tar on stdin into INSTALL_DIR.new, then swaps it in (the previous copy is kept as
# INSTALL_DIR.old, for a roll back) and links ~/.local/bin/DirAI and the agent rules to it.
# Restart one tree's server (@ROOT@: its quoted root) with the DirAI in INSTALL_DIR. Which DirAI serves it
# is read on its own node (it may be a compute node: ssh there, as DirAI does): the dirai_serve path in its
# wrapper's command line (ps, as macOS has no /proc). From INSTALL_DIR already (or no copy there): DirAI restart, a reload in place.
# From another checkout: stopped and started from the copy on the same node; inside the job it ran in,
# unless that was its own sbatch job (dirai-*, which stop cancels): then as a new one (start --job).
RESTART_SH = r"""
export PATH="$HOME/.local/bin:$PATH"; R=@ROOT@
read -r node job _ _ pid _ _ < "$R/www/server_host.txt" 2>/dev/null || { DirAI -C "$R" start; exit; }
copy=$(cd "$HOME/.local/share/dirai" 2>/dev/null && pwd -P)
get="ps -o args= -p $pid"
if [ "$node" = "$(hostname -s)" ]; then cmd=$(eval "$get" 2>/dev/null)
else cmd=$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$node" "$get" 2>/dev/null); fi
serve=$(printf '%s\n' $cmd | grep '/bin/dirai_serve$' | head -1)
from=$(cd "$(dirname "$serve")/.." 2>/dev/null && pwd -P)
if [ -z "$copy" ] || [ -z "$serve" ] || [ "$from" = "$copy" ]; then exec DirAI -C "$R" restart; fi
echo "moving from $from to $copy" >&2
if [ "$job" != nojob ] && squeue -h -j "$job" -o %j 2>/dev/null | grep -q '^dirai-'; then
    DirAI -C "$R" stop && DirAI -C "$R" start --job
else
    DirAI -C "$R" stop && DirAI -C "$R" start "$node"
fi
"""
INSTALL_SCRIPT = r"""
set -eu
D="$HOME/.local/share/dirai"; N="$D.new"
rm -rf "$N"; mkdir -p "$N"
tar xzf - -C "$N"
[ -x "$N/bin/DirAI" ] || { echo "the copy in $N has no bin/DirAI" >&2; exit 1; }
if [ -e "$D" ]; then rm -rf "$D.old"; mv "$D" "$D.old"; fi
mv "$N" "$D"
mkdir -p "$HOME/.local/bin" "$HOME/.config/dirai"
ln -sfn "$D/bin/DirAI" "$HOME/.local/bin/DirAI"
ln -sfn "$D/AGENT_RULE.md" "$HOME/.config/dirai/AGENT_RULE.md"
echo "DirAI copied to $D"
"""


def ship_files(tool=dirai_config.TOOL_DIR):
    """(relative path, full path) of the DirAI files a downstream machine gets, sorted."""
    out = []
    for top in SHIP:
        full = os.path.join(tool, top)
        if os.path.isfile(full):
            out.append((top, full))
        for dirpath, dirnames, filenames in os.walk(full):
            dirnames[:] = sorted(d for d in dirnames if d != "__pycache__" and not d.startswith("."))
            for n in sorted(filenames):
                if not n.endswith((".pyc", ".tmp")) and not n.startswith("."):
                    p = os.path.join(dirpath, n)
                    out.append((os.path.relpath(p, tool), p))
    return out


def build_id(tool=dirai_config.TOOL_DIR):
    """A hash of the shipped files' names, modes and contents: equal on two machines = same DirAI."""
    h = hashlib.sha256()
    for rel, full in ship_files(tool):
        try:
            with open(full, "rb") as f:
                data = f.read()
        except OSError:
            continue
        h.update(("%s %o %d\n" % (rel, os.stat(full).st_mode & 0o111, len(data))).encode())
        h.update(data)
    return h.hexdigest()[:12]


def build_label(tool=dirai_config.TOOL_DIR):
    """For people: the git commit DirAI came from (a copy remembers its upstream's), '+' if modified."""
    info = dirai_config.load_json(os.path.join(tool, BUILD_FILE), None)
    if isinstance(info, dict):
        return info.get("label", "")
    if not shutil.which("git"):
        return ""
    git = lambda *a: subprocess.run(["git", "-C", tool] + list(a), stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, universal_newlines=True).stdout.strip()
    commit = git("rev-parse", "--short", "HEAD")
    if commit and git("status", "--porcelain", "--untracked-files=no", "--", *SHIP):
        commit += "+"
    return commit


def ship_tar():
    """The tar.gz of this server's DirAI files plus a BUILD file, as bytes."""
    import io
    import tarfile
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel, full in ship_files():
            tar.add(full, arcname=rel, recursive=False)
        info = json.dumps({"build": build_id(), "label": build_label(), "from": machine_name(),
                           "time": time.strftime("%Y-%m-%d %H:%M")}).encode()
        ti = tarfile.TarInfo(BUILD_FILE)
        ti.size, ti.mtime, ti.mode = len(info), int(time.time()), 0o644
        tar.addfile(ti, io.BytesIO(info))
    return buf.getvalue()


def machine_name():
    """This machine as `hostname -s` names it (tests: DIRAI_MACHINE_NAME)."""
    return os.environ.get("DIRAI_MACHINE_NAME") or socket.gethostname().split(".")[0]


# --- what this machine reports (DirAI list --json) -----------------------------------------
def serving_checkout(pid):
    """The DirAI checkout a running dirai_serve (pid) was started from, or None."""
    try:
        with open("/proc/%s/cmdline" % pid, "rb") as f:
            args = f.read().decode(errors="replace").split("\0")
    except OSError:
        args = subprocess.run(["ps", "-o", "args=", "-p", str(pid)], stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, universal_newlines=True).stdout.split()
    exe = next((a for a in args if a.endswith("/bin/dirai_serve")), None)
    return os.path.dirname(os.path.dirname(os.path.realpath(exe))) if exe else None


def tree_id(key, root):
    """A tree's id whatever route or node reports it: a hash of this user's DirAI key (the same on every
    node sharing $HOME) and the tree's real root. Only the hash leaves the machine. "" without a key."""
    if not key:
        return ""
    return hashlib.sha256((key + "\0" + os.path.realpath(root)).encode()).hexdigest()[:16]


# SLURM job states in which a server's job may still be running (anything else: it ended)
LIVE_JOB_STATES = ("RUNNING", "PENDING", "REQUEUED", "CONFIGURING", "COMPLETING", "SUSPENDED", "RESIZING",
                   "STAGE_OUT", "SIGNALING")


def job_states(ids):
    """{job id: State} from one sacct call; {} without sacct or when it fails (then nothing counts as ended)."""
    if not ids or not shutil.which("sacct"):
        return {}
    try:
        r = subprocess.run(["sacct", "-X", "-n", "-P", "-j", ",".join(sorted(ids)), "-o", "JobID,State"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    out = {}
    for line in r.stdout.splitlines():
        parts = line.split("|")
        if len(parts) == 2 and parts[0] in ids:
            out[parts[0]] = parts[1].strip()
    return out


def server_gone(fields, states):
    """Why the server a server_host.txt names (fields) is known to be gone, or None (alive, or can't tell):
    its job ended (sacct), or, for a server without a job on this very node, its pid no longer exists."""
    node, job, pid = fields[0], fields[1], fields[4]
    if job != "nojob":
        st = states.get(job)
        return "job %s ended (%s)" % (job, st.split()[0]) if st and not st.startswith(LIVE_JOB_STATES) else None
    if node == socket.gethostname().split(".")[0] and pid.isdigit():
        try:
            os.kill(int(pid), 0)
        except ProcessLookupError:
            return "pid %s is gone" % pid
        except OSError:
            pass         # alive, another user's (a reused pid): can't tell
    return None


def machine_report():
    """This machine's trees as `DirAI list --json` prints them. A server_host.txt whose server is known to
    be gone (it died without DirAI stop: its job hit the time limit, the node crashed) is removed, and
    the tree reported down with why ("last")."""
    trees = []
    try:
        with open(dirai_config.TREES_FILE) as f:
            roots = [l.strip() for l in f if l.strip()]
    except OSError:
        roots = []
    try:
        with open(dirai_config.KEY_FILE) as f:
            key = f.read().strip()
    except OSError:
        key = ""    # made by the first server started here
    hosts = {}
    for root in roots:
        try:
            with open(os.path.join(root, "www", "server_host.txt")) as f:
                hosts[root] = f.read()
        except OSError:
            pass
    states = job_states({h.split()[1] for h in hosts.values() if len(h.split()) > 4 and h.split()[1] != "nojob"})
    for root in roots:
        if not os.path.isdir(root):
            continue
        t = {"root": root, "port": dirai_config.tree_config(root).get("port"), "running": False,
             "tree_id": tree_id(key, root)}
        try:
            text = hosts.get(root)
            if text is None:
                raise OSError
            fields = text.split()
            gone = server_gone(fields, states) if len(fields) > 4 else None
            if gone:
                t["last"] = "%s: %s" % (fields[0], gone)
                hf = os.path.join(root, "www", "server_host.txt")
                with open(hf) as f:       # unless a new server wrote it meanwhile
                    if f.read() == text:
                        os.remove(hf)
                trees.append(t)
                continue
            # node job date time pid reload-capable port
            t.update(running=True, node=fields[0], job=fields[1], started=" ".join(fields[2:4]))
            if len(fields) > 6 and fields[6].isdigit():
                t["port"] = int(fields[6])
            if fields[0] == machine_name():
                t["tool"] = serving_checkout(fields[4])
        except (OSError, IndexError):
            pass
        trees.append(t)
    return {"machine": machine_name(), "user": os.environ.get("USER", ""), "key": key,
            "tool": os.path.realpath(dirai_config.TOOL_DIR), "build": build_id(), "commit": build_label(),
            "trees": trees}


# --- the ssh config --------------------------------------------------------------------------
def ssh_hosts(path=SSH_CONFIG, seen=None):
    """Host aliases in the ssh config, following Include; patterns (* ? !) skipped."""
    seen = set() if seen is None else seen
    hosts = []
    if path in seen:
        return hosts
    seen.add(path)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return hosts
    base = os.path.dirname(path)
    for line in lines:
        words = line.split("#", 1)[0].replace("=", " ").split()
        if len(words) < 2:
            continue
        kw = words[0].lower()
        if kw == "host":
            hosts += [h for h in words[1:] if not set(h) & set("*?!") and ALIAS_RE.match(h)]
        elif kw == "include":
            import glob
            for pat in words[1:]:
                pat = os.path.expanduser(pat)
                for p in sorted(glob.glob(pat if os.path.isabs(pat) else os.path.join(base, pat))):
                    hosts += ssh_hosts(p, seen)
    out = []
    for h in hosts:
        if h not in out:
            out.append(h)
    return out


def free_port(prefer=None):
    """A port free on 127.0.0.1, prefer if it is."""
    for p in ([prefer] if prefer else []) + [0]:
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", p))
            return s.getsockname()[1]
        except OSError:
            continue
        finally:
            s.close()


# --- one ssh link per enabled host ---------------------------------------------------------
class Link:
    def __init__(self, alias):
        self.alias = alias
        os.makedirs(CTL_DIR, mode=0o700, exist_ok=True)
        self.ctl = os.path.join(CTL_DIR, hashlib.sha256(alias.encode()).hexdigest()[:12])
        self.master = None
        self.node_tunnels = {}     # (user@node, lport, rport) -> Popen, for trees on another node
        self.forwards = set()      # (lport, rport) through the master

    def ssh(self, *args, timeout=30, data=None):
        """ssh through the master; data (bytes) goes to the remote command's stdin."""
        r = subprocess.run([SSH, "-S", self.ctl] + SSH_OPTS + list(args), input=data if data is not None else b"",
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        r.stdout, r.stderr = r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")
        return r

    def up(self):
        if self.master is None or self.master.poll() is not None:
            return False
        try:
            return self.ssh("-O", "check", self.alias, timeout=10).returncode == 0
        except subprocess.TimeoutExpired:
            return False

    def connect(self):
        """Start the ControlMaster if it isn't running; returns an error message or None."""
        if self.up():
            return None
        self.close()
        try:
            os.remove(self.ctl)
        except OSError:
            pass
        err = os.path.join(CTL_DIR, os.path.basename(self.ctl) + ".err")
        with open(err, "w") as ef:
            self.master = subprocess.Popen(
                [SSH, "-M", "-S", self.ctl, "-N"] + SSH_OPTS +
                ["-o", "ControlPersist=no", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3",
                 "-o", "ExitOnForwardFailure=yes", self.alias],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=ef)
        end = time.time() + 20
        while time.time() < end:
            if self.master.poll() is not None:
                break
            if os.path.exists(self.ctl) and self.up():
                return None
            time.sleep(0.3)
        try:
            with open(err, errors="replace") as f:
                msg = f.read()
        except OSError:
            msg = ""
        self.close()
        return (msg.strip().splitlines() or ["ssh to %s did not connect within 20 s" % self.alias])[-1]

    def run(self, command, timeout=60, data=None):
        return self.ssh(self.alias, command, timeout=timeout, data=data)

    def tunnel(self, lport, rport, node=None, user=None):
        """127.0.0.1:lport here -> 127.0.0.1:rport where ssh lands, or on node through it."""
        if node is None:
            if (lport, rport) in self.forwards:
                return True
            ok = self.ssh("-O", "forward", "-L", "127.0.0.1:%d:127.0.0.1:%d" % (lport, rport),
                          self.alias, timeout=15).returncode == 0
            if ok:
                self.forwards.add((lport, rport))
            return ok
        dest = "%s@%s" % (user, node) if user else node
        k = (dest, lport, rport)
        p = self.node_tunnels.get(k)
        if p and p.poll() is None:
            return True
        proxy = "%s -S %s %s -W %%h:%%p %s" % (shlex.quote(SSH), shlex.quote(self.ctl),
                                              " ".join(SSH_OPTS), shlex.quote(self.alias))
        # accept-new: the hop reaches another node of the same cluster through the already trusted
        # master; a node not seen before (ssh landed on another login node) is trusted, a changed key isn't
        with open(self.tunnel_err_file(lport), "w") as ef:
            p = self.node_tunnels[k] = subprocess.Popen(
                [SSH, "-N"] + SSH_OPTS + ["-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=15",
                                          "-o", "StrictHostKeyChecking=accept-new",
                                          "-o", "ProxyCommand=" + proxy, "-L", "127.0.0.1:%d:localhost:%d" % (lport, rport), dest],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=ef)
        end = time.time() + 15     # until its local end accepts
        while time.time() < end and p.poll() is None:
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", lport)) == 0:
                    return True
            time.sleep(0.3)
        return p.poll() is None

    def tunnel_err_file(self, lport):
        return "%s-%d.err" % (self.ctl, lport)

    def tunnel_error(self, lport):
        """Why the node tunnel on lport isn't running ("tunnel to login03: Host key verification
        failed."), or "" when it runs or there is none."""
        for (dest, lp, _), p in self.node_tunnels.items():
            if lp != lport or p.poll() is None:
                continue
            try:
                with open(self.tunnel_err_file(lport), errors="replace") as f:
                    lines = f.read().strip().splitlines()
            except OSError:
                lines = []
            return "tunnel to %s: %s" % (dest, lines[-1] if lines else "ssh exited with %d" % p.returncode)
        return ""

    def drop_tunnel(self, lport, rport, node=None, user=None):
        if node is None:
            if (lport, rport) in self.forwards:
                self.forwards.discard((lport, rport))
                try:
                    self.ssh("-O", "cancel", "-L", "127.0.0.1:%d:127.0.0.1:%d" % (lport, rport), self.alias, timeout=10)
                except subprocess.TimeoutExpired:
                    pass
            return
        p = self.node_tunnels.pop(("%s@%s" % (user, node) if user else node, lport, rport), None)
        if p:
            p.terminate()
            try:
                os.remove(self.tunnel_err_file(lport))
            except OSError:
                pass

    def close(self):
        for p in self.node_tunnels.values():
            p.terminate()
        self.node_tunnels = {}
        self.forwards = set()
        if self.master is not None and self.master.poll() is None:
            self.master.terminate()
            try:
                self.master.wait(5)
            except subprocess.TimeoutExpired:
                self.master.kill()
        self.master = None


# --- the forwarder: what the browser opens for a remote tree -------------------------------
def owner_cookie(header, key, names):
    try:
        c = cookies.SimpleCookie(header or "")
    except cookies.CookieError:
        return False
    return bool(key) and any(n in c and c[n].value == key for n in names)


def read_head(sock, limit=65536):
    """(head bytes without the blank line, bytes after it) or (None, b'')."""
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(8192)
        if not chunk:
            return None, b""
        buf += chunk
        if len(buf) > limit:
            return None, b""
    head, rest = buf.split(b"\r\n\r\n", 1)
    return head, rest


def pipe(src, dst):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


class Forwarder:
    """127.0.0.1:port -> 127.0.0.1:target (a tunnel), for owner requests only, with the cookie
    replaced by review_key=<next key> (the name every DirAI version accepts) and Set-Cookie dropped."""

    def __init__(self, key, cookie_names, prefer=None, home=None):
        self.key, self.names = key, cookie_names
        self.home = home       # () -> b"<server port> <machine>": where Home leads, added when a request has none
        self.target, self.next_key = None, ""
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.sock.bind(("127.0.0.1", prefer or 0))
        except OSError:
            self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.sock.listen(32)
        self.closed = False
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while not self.closed:
            try:
                conn, addr = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self.handle, args=(conn, addr), daemon=True).start()

    @staticmethod
    def refuse(conn, code=404, why="Not Found"):
        body = ("<h1>%d %s</h1>" % (code, htmllib.escape(why))).encode()
        conn.sendall(b"HTTP/1.0 %d %s\r\nContent-Type: text/html\r\nContent-Length: %d\r\nConnection: close\r\n\r\n%s"
                     % (code, b"Not Found" if code == 404 else b"Bad Gateway", len(body), body))

    def handle(self, conn, addr):
        up = None
        try:
            conn.settimeout(60)
            head, rest = read_head(conn)
            if head is None:
                return
            lines = head.split(b"\r\n")
            headers = [l for l in lines[1:] if l]
            cookie = b"; ".join(l.split(b":", 1)[1].strip() for l in headers if l.lower().startswith(b"cookie:"))
            if addr[0] != "127.0.0.1" or not owner_cookie(cookie.decode("latin-1"), self.key, self.names):
                return self.refuse(conn)
            if not self.target:
                return self.refuse(conn, 502, "This tree's link is down; see the Machines section.")
            drop = (b"cookie:", b"connection:", b"keep-alive:", b"proxy-")
            headers = [l for l in headers if not l.lower().startswith(drop)]
            headers += [b"Cookie: review_key=" + self.next_key.encode(), b"Connection: close"]
            h = self.home() if self.home else None
            if h and not any(l.lower().startswith(HOME.lower() + b":") for l in headers):   # the first hop wins
                headers.append(HOME + b": " + h)
            up = socket.create_connection(("127.0.0.1", self.target), timeout=60)
            up.sendall(b"\r\n".join([lines[0]] + headers) + b"\r\n\r\n" + rest)
            threading.Thread(target=pipe, args=(conn, up), daemon=True).start()
            rhead, rrest = read_head(up)
            if rhead is None:
                return self.refuse(conn, 502, "No answer from the remote server.")
            rl = rhead.split(b"\r\n")
            rl = [rl[0]] + [l for l in rl[1:] if not l.lower().startswith(b"set-cookie:")]
            conn.sendall(b"\r\n".join(rl) + b"\r\n\r\n" + rrest)
            pipe(up, conn)
        except OSError:
            pass
        finally:
            for s in (up, conn):
                try:
                    s and s.close()
                except OSError:
                    pass

    def close(self):
        self.closed = True
        try:
            self.sock.close()
        except OSError:
            pass


# --- the trees this server reaches ---------------------------------------------------------
def http_get(port, path, key, via=None, data=None, timeout=HTTP_TIMEOUT):
    """GET (or POST data) http://127.0.0.1:port/path as the owner of the server behind it; (code, body)."""
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=data)
    req.add_header("Cookie", "review_key=" + key)
    if via is not None:
        req.add_header(VIA, ",".join(via))
    if data is not None:
        req.add_header("X-Review", "1")
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def agent_rows(index_html, status, favs=()):
    """The agent rows of a built www/index.html, with their /_review/all status and whether that
    server's list has them starred (its www/favorites.json). "row": the row's own HTML, when it is
    exactly what agent_list.py writes (ROW_FULL_RE)."""
    rows = []
    for tr in TR_RE.findall(index_html):
        m = ROW_RE.match(tr)
        if not m:
            continue
        d, title, mtime = m.groups()
        d = urllib.request.unquote(htmllib.unescape(d)).rstrip("/")
        s = status.get(d, {})
        r = {k: s.get(k) for k in STATUS_KEYS}
        r.update(dir=d, title=htmllib.unescape(title or ""), mtime=float(mtime), asking=bool(s.get("asking")),
                 denied=int(s.get("denied") or 0), fav=d in favs)
        if ROW_FULL_RE.fullmatch(tr):
            r["row"] = tr
        rows.append(r)
    return rows


def relayed_rows(agents):
    """Agent rows a server further down reports: a row's HTML is kept only if it passes here too."""
    out = []
    for a in agents or []:
        if isinstance(a, dict):
            a = dict(a)
            if not (isinstance(a.get("row"), str) and ROW_FULL_RE.fullmatch(a["row"])):
                a.pop("row", None)
            out.append(a)
    return out


def parse_home(value):
    """(port, machine) from an X-DirAI-Home value, or None if it is not "<digits> <plain name>"."""
    m = re.fullmatch(r"(\d{1,5}) ([A-Za-z0-9_.-]{1,64})", value or "")
    return (int(m.group(1)), m.group(2)) if m and 0 < int(m.group(1)) < 65536 else None


class Remotes:
    def home_value(self):
        v = "%s %s" % (self.port, self.me)
        return v.encode() if self.port and parse_home(v) else None

    def __init__(self, root, key, cookie_names):
        self.root, self.key, self.names = root, key, cookie_names
        self.me = machine_name()
        self.port = None       # this server's port, set by server.py
        self.file = os.path.join(root, "www", "machines.json")
        self.ports_file = os.path.join(root, "www", "remote_ports.json")
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.links = {}        # alias -> Link
        self.hosts = {}        # alias -> {"state", "error", "checked", "machine", "commit"}
        self.trees = {}        # id -> record (see poll_host / poll_tree)
        self.fwd = {}          # id -> Forwarder
        self.tports = {}       # id -> (link alias, lport, rport, node, user)
        self.busy = {}         # id -> what is being done ("starting")
        self.tried = {}        # alias -> commit an automatic install was last tried at
        self.notes = {}        # alias -> last update's outcome
        self.restart_wanted = set()   # tree ids to restart once their agents are idle (after an update)
        self.closed = False
        self.watched = 0       # when report() was last asked for (see POLL_WATCHED_S)

    # choices ------------------------------------------------------------------------------
    def choices(self):
        c = dirai_config.load_json(self.file, {})
        return {"hosts": c.get("hosts") if isinstance(c.get("hosts"), dict) else {},
                "hidden": [h for h in c.get("hidden", []) if isinstance(h, str)]}

    def save_choices(self, c):
        dirai_config.save_json(self.file, c, indent=1)

    def enabled(self):
        return [a for a, h in self.choices()["hosts"].items() if h.get("enabled") and ALIAS_RE.match(a)]

    # the loop -----------------------------------------------------------------------------
    def run(self):
        while not self.closed:
            try:
                self.poll()
            except Exception as e:     # keep the loop alive whatever one pass hits
                print("remotes: poll failed: %s" % e, flush=True)
            self.wake.wait(POLL_WATCHED_S if time.time() - self.watched < WATCHED_S else POLL_S)
            self.wake.clear()

    def poll(self):
        on = self.enabled()
        for alias in list(self.links):
            if alias not in on:
                self.links.pop(alias).close()
                with self.lock:
                    self.hosts.pop(alias, None)
                    for tid in [t for t, r in self.trees.items() if r["host"] == alias]:
                        self.forget(tid)
        threads = [threading.Thread(target=self.poll_host, args=(a,), daemon=True) for a in on]
        for t in threads:
            t.start()
        for t in threads:
            t.join(120)

    def poll_host(self, alias):
        link = self.links.setdefault(alias, Link(alias))
        h = {"state": "down", "error": "", "checked": time.time()}
        err = link.connect()
        info = None
        if err is None:
            info, err, outdated = self.list_host(link)
            # DirAI missing there, too old for list --json, or not in INSTALL_DIR: copy this server's
            # DirAI there (once per build of ours; Update does it again), then ask again
            elsewhere = info is not None and not info.get("tool", "").endswith("/.local/share/dirai")
            if (outdated or elsewhere) and self.tried.get(alias) != build_id():
                self.tried[alias] = build_id()
                with self.lock:
                    self.hosts[alias] = dict(h, state="updating", error="copying DirAI there…")
                err = self.update_host(alias, link)
                if err is None:
                    info, err, outdated = self.list_host(link)
            elif outdated:
                err += " (copying DirAI there failed: see below)"
        if info is None:
            h.update(error=err, can_update=err is not None and link.up(), note=self.notes.get(alias, ""))
            with self.lock:
                self.hosts[alias] = h
                for r in self.trees.values():
                    if r["host"] == alias:
                        r["stale"] = True
            return
        h.update(state="up", machine=info.get("machine", ""), commit=info.get("commit", ""), tool=info.get("tool", ""),
                 build=info.get("build", ""), behind=info.get("build") != build_id(), note=self.notes.get(alias, ""))
        with self.lock:
            self.hosts[alias] = h
        seen = set()
        for t in info.get("trees", []):
            tid = "%s:%s" % (alias, t["root"])
            seen.add(tid)
            rec = {"id": tid, "host": alias, "machine": alias, "ident": info.get("machine", ""), "via": [alias],
                   "root": t["root"], "port": t.get("port"), "node": t.get("node"), "job": t.get("job"),
                   "running": t.get("running"), "key": info.get("key", ""), "user": info.get("user"),
                   "tool": t.get("tool"), "reporter": None, "stale": False, "tree_id": t.get("tree_id", ""),
                   "last": t.get("last", "")}
            here = t.get("node") in (None, info.get("machine"))
            if t.get("running") and t.get("port"):
                self.ensure_tunnel(tid, link, t["port"], None if here else t["node"], info.get("user"))
                downstream = self.poll_tree(rec)
                for d in downstream:
                    seen.add(d["id"])
            else:
                self.drop(tid)
                rec.update(state="down", agents=[])
            with self.lock:
                old = self.trees.get(tid, {})
                if self.busy.get(tid) and (rec.get("state") != "alive" or self.busy[tid] in ("stopping", "forgetting")):
                    rec["state"] = self.busy[tid]
                elif rec.get("state") == "alive" and self.busy.get(tid) == "starting":
                    self.busy.pop(tid, None)
                rec.setdefault("agents", old.get("agents", []))
                self.trees[tid] = rec
        with self.lock:
            for tid in [t for t, r in self.trees.items() if r["host"] == alias and t not in seen]:
                self.forget(tid)
        self.restart_idle(alias, link)

    @staticmethod
    def list_host(link):
        """(report, None, False) from `DirAI list --json` there, else (None, error, outdated): outdated
        when ssh worked but DirAI is missing or prints no JSON (too old)."""
        try:
            r = link.run(LIST_CMD, timeout=60)
        except subprocess.TimeoutExpired:
            return None, "DirAI list --json took over a minute", False
        line = next((l for l in reversed(r.stdout.splitlines()) if l.startswith("{")), "")
        try:
            return json.loads(line), None, False
        except ValueError:
            pass
        if r.returncode == 255:      # ssh itself failed
            return None, (r.stderr.strip().splitlines() or ["ssh failed"])[-1], False
        missing = r.returncode == 127 or "not found" in r.stderr
        return None, "DirAI there is %s" % ("not installed" if missing else "too old for list --json"), True

    def update_host(self, alias, link):
        """Copy this server's DirAI to INSTALL_DIR on alias; its running trees restart once idle. Error or None."""
        try:
            r = link.run("bash -c %s" % shlex.quote(INSTALL_SCRIPT), timeout=300, data=ship_tar())
        except subprocess.TimeoutExpired:
            self.notes[alias] = "copying DirAI took over 5 min"
            return self.notes[alias]
        if r.returncode != 0:
            lines = (r.stderr.strip() or r.stdout.strip()).splitlines()
            self.notes[alias] = "copying DirAI failed: " + (lines[-1] if lines else "exit %d" % r.returncode)
            return self.notes[alias]
        self.notes[alias] = "%s (%s, %s)" % ((r.stdout.strip().splitlines() or ["copied"])[-1], build_label() or build_id(),
                                             time.strftime("%H:%M"))
        with self.lock:
            self.restart_wanted |= {t for t, rec in self.trees.items() if rec["host"] == alias and not rec.get("reporter")}
            self.restart_wanted.add("host:" + alias)    # trees not seen yet: those listed by the next poll
        return None

    def restart_idle(self, alias, link):
        """After an update: restart each of alias's running trees whose agents are idle (a restart stops
        agent runs). A tree served from another checkout than the updated one is stopped and started."""
        with self.lock:
            if "host:" + alias in self.restart_wanted:
                self.restart_wanted.discard("host:" + alias)
                self.restart_wanted |= {t for t, r in self.trees.items() if r["host"] == alias and not r.get("reporter")}
            todo = [self.trees[t] for t in self.restart_wanted if t in self.trees and self.trees[t]["host"] == alias]
        for rec in todo:
            if not rec.get("running"):
                self.restart_wanted.discard(rec["id"])
                continue
            busy = [a for a in rec.get("agents", []) if a.get("status") in ("working", "queued") or a.get("asking")]
            if rec.get("state") != "alive" or busy:
                self.notes[rec["id"]] = ("restart after update waits: %d agent%s working" % (len(busy), "" if len(busy) == 1 else "s")
                                         if busy else "restart after update waits for the server to answer")
                continue
            self.restart_wanted.discard(rec["id"])
            threading.Thread(target=self.restart_tree, args=(rec,), daemon=True).start()

    def restart_tree(self, rec):
        """Restart rec's server there with the DirAI installed in INSTALL_DIR (RESTART_SH): a reload in
        place when it already runs from there, else stopped and started from there on the same node."""
        tid, link = rec["id"], self.links.get(rec["host"])
        if not link:
            return
        self.busy[tid] = rec["state"] = "restarting"
        try:
            r = link.run("bash -c %s" % shlex.quote(RESTART_SH.replace("@ROOT@", shlex.quote(rec["root"]))), timeout=240)
            moved = [l for l in r.stderr.splitlines() if l.startswith("moving from ")]
            lines = (r.stderr.strip() or r.stdout.strip()).splitlines()
            self.notes[tid] = ("restarted" + (", now from ~/.local/share/dirai (was %s)" % moved[0].split()[2] if moved else "")
                               if r.returncode == 0 else "restart failed: " + (lines[-1] if lines else ""))
        except subprocess.TimeoutExpired:
            self.notes[tid] = "restart took over 4 min"
        self.busy.pop(tid, None)
        self.wake.set()

    def poll_tree(self, rec):
        """Read a running direct tree through its tunnel: its agents and its downstream trees
        (added to self.trees). Returns those downstream records."""
        tid, key = rec["id"], rec["key"]
        lport = self.tports[tid][1]
        self.forwarder(tid, lport, key)
        try:
            code, page = http_get(lport, "/www/index.html", key)
            code2, st = http_get(lport, "/_review/all", key)
            status = json.loads(st) if code2 == 200 else {}
            if code != 200:
                raise OSError("HTTP %d" % code)
            try:       # its Favorites (servers from before favorites answer 404: none)
                code3, fv = http_get(lport, "/_review/favorites", key)
                favs = set(f for f in json.loads(fv) if isinstance(f, str)) if code3 == 200 else set()
            except (OSError, ValueError, TypeError):
                favs = set()
            # that machine's Claude plan usage and pause levels (its own login; cached 60 s there), and the
            # CPU and memory of the node serving the tree, and the shared repos connected there (proposal 72)
            for name in ("usage", "load", "shares"):
                try:
                    c, body = http_get(lport, "/_review/" + name, key)
                    rec[name] = json.loads(body) if c == 200 else None
                except (OSError, ValueError):
                    rec[name] = None
            rec.update(state="alive", agents=agent_rows(page.decode("utf-8", "replace"), status, favs),
                       checked=time.time(), owner=code2 == 200)
        except (OSError, ValueError) as e:
            link = self.links.get(rec["host"])     # a failed hop to the node says why, not "Connection refused"
            rec.update(state="not answering", error=(link and link.tunnel_error(lport)) or str(e), stale=True)
            with self.lock:
                rec["agents"] = self.trees.get(tid, {}).get("agents", [])
            return [d for d in self.trees.values() if d.get("reporter") == tid]
        # its own downstream trees (servers without /_review/remotes answer 404: none)
        out = []
        try:
            code, body = http_get(lport, "/_review/remotes", key, via=[self.me])
            report = json.loads(body) if code == 200 else {}
        except (OSError, ValueError):
            report = None
        if report is None:     # keep what we had
            return [d for d in self.trees.values() if d.get("reporter") == tid]
        rec["hosts"] = report.get("hosts", [])
        for d in report.get("trees", []):
            if d.get("ident") == self.me or self.me in d.get("idents", []) or not d.get("fport"):
                continue     # this machine again (a cycle) or not reachable there
            did = "%s/%s" % (rec["host"], d["id"])
            # on the reporter's machine, its forwarder for that tree listens on 127.0.0.1
            node = rec["node"] if rec["node"] not in (None, rec["ident"]) else None
            self.ensure_tunnel(did, self.links[rec["host"]], d["fport"], node, rec.get("user"))
            drec = {"id": did, "host": rec["host"], "machine": d["machine"], "ident": d.get("ident", ""),
                    "idents": [rec["ident"]] + d.get("idents", []), "via": [rec["host"]] + d.get("via", []),
                    "root": d["root"], "port": d.get("port"), "node": d.get("node"), "job": d.get("job"),
                    "running": d.get("running"), "state": d.get("state"), "agents": relayed_rows(d.get("agents")),
                    "hosts": d.get("hosts", []), "key": key, "reporter": tid, "remote_id": d["id"],
                    "stale": bool(d.get("stale")), "checked": d.get("checked"), "note": d.get("note", ""),
                    "usage": d.get("usage"), "load": d.get("load"), "shares": d.get("shares"),
                    "tree_id": d.get("tree_id", ""),
                    "error": d.get("error", "")}
            self.forwarder(did, self.tports[did][1], key)
            with self.lock:
                if self.busy.get(did) and drec["state"] != "alive":
                    drec["state"] = self.busy[did]
                elif drec["state"] == "alive":
                    self.busy.pop(did, None)
                self.trees[did] = drec
            out.append(drec)
        with self.lock:
            for gone in [t for t, r in self.trees.items() if r.get("reporter") == tid and r not in out]:
                self.forget(gone)
        return out

    def ensure_tunnel(self, tid, link, rport, node, user):
        have = self.tports.get(tid)
        if have and have[0] == link.alias and have[2] == rport and have[3] == node and link.up():
            link.tunnel(have[1], rport, node, user)    # re-opens a node tunnel that died
            return
        if have:
            self.drop(tid)
        lport = free_port()
        link.tunnel(lport, rport, node, user)
        self.tports[tid] = (link.alias, lport, rport, node, user)

    def forwarder(self, tid, target, next_key):
        with self.lock:
            f = self.fwd.get(tid)
            if f is None:
                ports = dirai_config.load_json(self.ports_file, {})
                f = self.fwd[tid] = Forwarder(self.key, self.names, prefer=ports.get(tid), home=self.home_value)
                if ports.get(tid) != f.port:
                    ports[tid] = f.port
                    dirai_config.save_json(self.ports_file, ports, indent=1)
            f.target, f.next_key = target, next_key

    def drop(self, tid):
        t = self.tports.pop(tid, None)
        if t and t[0] in self.links:
            self.links[t[0]].drop_tunnel(t[1], t[2], t[3], t[4])
        f = self.fwd.get(tid)
        if f:
            f.target = None

    def forget(self, tid):
        self.drop(tid)
        f = self.fwd.pop(tid, None)
        if f:
            f.close()
        self.trees.pop(tid, None)

    def close(self):
        self.closed = True
        self.wake.set()
        for f in list(self.fwd.values()):
            f.close()
        for link in list(self.links.values()):
            link.close()

    # what the agent list shows ----------------------------------------------------------
    def report(self, via=()):
        """/_review/remotes: this server's hosts and every tree it reaches (owner only)."""
        if self.me in via:
            return {"machine": self.me, "hosts": [], "trees": [], "cycle": True}
        self.watched = time.time()
        c = self.choices()
        hosts = []
        with self.lock:
            for alias in ssh_hosts():
                h = dict(self.hosts.get(alias, {}))
                h.update(alias=alias, enabled=bool(c["hosts"].get(alias, {}).get("enabled")))
                if not h["enabled"]:
                    h["state"] = "off"
                hosts.append(h)
            trees = []
            for tid, r in self.trees.items():
                f = self.fwd.get(tid)
                t = {k: r.get(k) for k in ("id", "machine", "ident", "via", "root", "port", "node", "job",
                                           "running", "state", "agents", "hosts", "stale", "checked", "usage", "load",
                                           "shares", "tree_id", "last")}
                t.update(idents=r.get("idents", [r.get("ident")]), hidden=tid in c["hidden"],
                         fport=f.port if f and f.target else None, error=r.get("error", ""),
                         note=self.notes.get(tid, r.get("note", "")) if not r.get("reporter") else r.get("note", ""))
                trees.append(t)
        try:
            import claude_usage      # this machine's Claude plan usage, for its own box
            import codex_engine      # with its engine (Claude Code or Codex) and Codex usage
            mine = codex_engine.annotate(claude_usage.usage())
        except Exception:
            mine = None
        return {"machine": self.me, "root": self.root, "tree_id": tree_id(self.key, self.root), "hosts": hosts, "trees": trees, "usage": mine,
                "hidden": "" in c["hidden"], "build": build_id(), "commit": build_label()}

    # owner actions ----------------------------------------------------------------------
    def act(self, body):
        """POST /_review/remotes (owner only).
        {"op": "enable"|"disable", "host": alias, "at": tree id}: at "" (or none) is this server and
            this machine's ssh config; a tree id passes it to that tree's server (Add downstream of nas).
        {"op": "start", "tree": id}: start that tree's server (on its machine, by whoever links it).
        {"op": "new", "host": alias, "at": tree id, "path": "~/x", "node": ""|NODE|"--job"}: DirAI init and
            start for a new folder on that machine (relayed like enable).
        {"op": "update", "host": alias, "at": tree id}: copy this server's DirAI there (to INSTALL_DIR),
            then restart its trees once their agents are idle. Relayed down, "build" is the build the
            click came from: a server holding another build refuses (update it first, top down).
        {"op": "restart", "tree": id}: DirAI restart for that tree (stops its agents' runs).
        {"op": "stop", "tree": id}: DirAI stop for that tree (stops its agents' runs); not this server's own.
        {"op": "forget", "tree": id}: DirAI forget for that tree (stopped if running, then off its machine's
            trees list; the folder is kept); not this server's own.
        {"op": "hide"|"show", "tree": id}: this list's view only (tree "" is this server's own agents).
        {"op": "call", "tree": id, "path": one of CALLS, "data": {...}}: that request on the tree's own
            server, as its owner: a star in its list (favorite), its machine's pause levels (usage_stop),
            its usage history for the chart (usage_history).
        {"op": "refresh"}: poll now."""
        op, at = body.get("op"), body.get("at") or ""
        build = body.get("build") or build_id()
        if at:
            with self.lock:
                rec = self.trees.get(at)
            if not rec:
                return {"error": "unknown tree %s" % at}
            out = self.relay(rec, {"op": op, "host": body.get("host", ""), "build": build,
                                   "path": body.get("path", ""), "node": body.get("node", "")})
            self.wake.set()      # read that server again now, not at the next 30 s poll,
            threading.Timer(8, self.wake.set).start()    # and once more when it has had time to act
            return out
        if op == "new":
            alias, path, node = body.get("host", ""), str(body.get("path") or "").strip(), str(body.get("node") or "").strip()
            link = self.links.get(alias)
            if alias not in self.enabled() or not link or not link.up():
                return {"error": "%s is not connected" % alias}
            if not (path.startswith("/") or path.startswith("~/")) or ".." in path.split("/") or \
                    any(ch in path for ch in "\n\r\0"):
                return {"error": "give a full path (/… or ~/…), without .."}
            if node and not (node == "--job" or re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", node)):
                return {"error": "node: a host name, --job, or empty for where ssh lands"}
            self.notes[alias] = "new tree %s: init and start…" % path
            threading.Thread(target=self.new_tree, args=(alias, link, path, node), daemon=True).start()
            return {"ok": True}
        if op == "update":
            alias = body.get("host", "")
            link = self.links.get(alias)
            if alias not in self.enabled() or not link:
                return {"error": "%s is not connected" % alias}
            if build != build_id():
                return {"error": "%s has another DirAI than the one asking (%s): update %s first" % (self.me, build_id(), self.me)}
            self.hosts.setdefault(alias, {})["state"] = "updating"

            def go():
                self.update_host(alias, link)
                self.wake.set()
            threading.Thread(target=go, daemon=True).start()
            return {"ok": True}
        if op == "restart" and not body.get("tree"):
            # this server: what DirAI restart does, USR1 to its dirai_serve wrapper (its parent),
            # which reloads it with the current code. Half a second later, so this answer gets out first.
            try:
                with open(os.path.join(self.root, "www", "server_host.txt")) as f:
                    fields = f.read().split()
                pid = int(fields[4])
            except (OSError, IndexError, ValueError):
                return {"error": "no www/server_host.txt: this server wasn't started with DirAI start"}
            if pid != os.getppid() or fields[5:6] != ["reload"]:
                return {"error": "this server can't reload itself (started another way): run DirAI restart"}
            threading.Timer(0.5, os.kill, (pid, signal.SIGUSR1)).start()
            return {"ok": True}
        if op == "restart":
            tid = body.get("tree", "")
            with self.lock:
                rec = self.trees.get(tid)
            if not rec:
                return {"error": "unknown tree %s" % tid}
            if rec.get("reporter"):
                with self.lock:
                    rep = self.trees.get(rec["reporter"])
                return self.relay(rep, {"op": "restart", "tree": rec["remote_id"]}) if rep else \
                    {"error": "no link to %s" % rec["reporter"]}
            threading.Thread(target=self.restart_tree, args=(rec,), daemon=True).start()
            return {"ok": True}
        if op in ("enable", "disable"):
            alias = body.get("host", "")
            if alias not in ssh_hosts():
                return {"error": "%s is not a Host in %s" % (alias, SSH_CONFIG)}
            c = self.choices()
            c["hosts"].setdefault(alias, {})["enabled"] = op == "enable"
            self.save_choices(c)
            self.wake.set()
            return {"ok": True}
        if op == "call":
            tid, path, data = body.get("tree", ""), body.get("path", ""), body.get("data")
            if path not in CALLS:
                return {"error": "not callable through Machines: %s" % path}
            with self.lock:
                rec = self.trees.get(tid)
            if not rec:
                return {"error": "unknown tree %s" % tid}
            out = self.call_tree(rec, path, data if isinstance(data, dict) else {})
            if path == "favorite" and out.get("ok"):      # show it now, not at the next poll
                with self.lock:
                    for a in rec.get("agents") or []:
                        if a.get("dir") == data.get("agent"):
                            a["fav"] = bool(data.get("on"))
            if path == "usage_stop" and out.get("ok") and isinstance(rec.get("usage"), dict):
                if str(data.get("name") or "").startswith("w"):      # a Codex window's level
                    if isinstance(rec["usage"].get("codex"), dict):
                        rec["usage"]["codex"]["stop"] = out.get("stop", rec["usage"]["codex"].get("stop"))
                else:
                    rec["usage"]["stop"] = out.get("stop", rec["usage"].get("stop"))
            if path == "engine" and out.get("ok") and isinstance(rec.get("usage"), dict):
                rec["usage"]["engine"] = out.get("engine")
            return out
        if op in ("hide", "show"):
            tid = body.get("tree", "")     # "" is this server's own agents
            c = self.choices()
            c["hidden"] = [h for h in c["hidden"] if h != tid] + ([tid] if op == "hide" else [])
            self.save_choices(c)
            return {"ok": True}
        if op == "start":
            tid = body.get("tree", "")
            with self.lock:
                rec = self.trees.get(tid)
            if not rec:
                return {"error": "unknown tree %s" % tid}
            if rec.get("reporter"):
                with self.lock:
                    rep = self.trees.get(rec["reporter"])
                if not rep:
                    return {"error": "no link to %s" % rec["reporter"]}
                out = self.relay(rep, {"op": "start", "tree": rec["remote_id"]})
                if out.get("ok"):
                    self.busy[tid] = rec["state"] = "starting"
                return out
            self.busy[tid] = "starting"
            rec["state"] = "starting"
            threading.Thread(target=self.start_tree, args=(rec,), daemon=True).start()
            return {"ok": True}
        if op in ("stop", "forget"):
            # stop: DirAI stop for that tree; forget: DirAI forget (stop if running, then off the trees list)
            tid = body.get("tree", "")
            with self.lock:
                rec = self.trees.get(tid)
            if not rec:
                return {"error": "unknown tree %s" % tid}
            if rec.get("tree_id") and rec["tree_id"] == tree_id(self.key, self.root):
                return {"error": "that is the server showing this list: %s it with DirAI %s in a terminal" % (op, op)}
            ing = "stopping" if op == "stop" else "forgetting"
            if rec.get("reporter"):
                with self.lock:
                    rep = self.trees.get(rec["reporter"])
                if not rep:
                    return {"error": "no link to %s" % rec["reporter"]}
                out = self.relay(rep, {"op": op, "tree": rec["remote_id"]})
                if out.get("ok"):
                    rec["state"] = ing
                return out
            self.busy[tid] = rec["state"] = ing
            self.restart_wanted.discard(tid)   # a stop replaces a restart still waiting after an Update (whose
            self.notes.pop(tid, None)          # "waits" note would hide the stop's outcome at every poll)
            threading.Thread(target=self.stop_tree, args=(rec, op), daemon=True).start()
            return {"ok": True}
        if op == "refresh":
            self.wake.set()
            return {"ok": True}
        return {"error": "unknown action"}

    def relay(self, rec, body):
        """Have tree rec's server do body: POST it to rec when this server links rec itself, else to
        the tree that reported rec, naming rec as "at" (that server relays it on the same way)."""
        if rec.get("reporter"):
            if body.get("op") in ("enable", "disable", "update", "new"):
                body = dict(body, at=rec["remote_id"])
            with self.lock:
                rec = self.trees.get(rec["reporter"], {})
        t = self.tports.get(rec.get("id"))
        if not t:
            return {"error": "no link to %s" % rec.get("id")}
        try:
            code, out = http_get(t[1], "/_review/remotes", rec["key"], data=json.dumps(body).encode(), timeout=30)
            out = json.loads(out) if code == 200 else {"error": "HTTP %d from %s" % (code, rec["id"])}
            if isinstance(out, dict) and out.get("error") == "unknown action":   # that server's DirAI predates this op
                out["error"] = ("unknown action at %s's server: its DirAI is older than this one (no op %s). "
                                "Use Update in the box of the machine that server runs on, then try again" % (rec["id"], body.get("op")))
            return out
        except (OSError, ValueError) as e:
            return {"error": str(e)}

    def call_tree(self, rec, path, data):
        """Owner request /_review/<path> (one of CALLS) on tree rec's own server: through its tunnel when
        this server links it, else relayed as op "call" to the tree that reported it. Its JSON answer."""
        if rec.get("reporter"):
            with self.lock:
                rep = self.trees.get(rec["reporter"])
            if not rep:
                return {"error": "no link to %s" % rec["reporter"]}
            return self.relay(rep, {"op": "call", "tree": rec["remote_id"], "path": path, "data": data})
        t = self.tports.get(rec["id"])
        if not t:
            return {"error": "no link to %s" % rec["id"]}
        try:
            post = CALLS[path] == "POST"
            query = "?" + urllib.parse.urlencode(data) if data and not post else ""
            code, res = http_get(t[1], "/_review/" + path + query, rec["key"],
                                 data=json.dumps(data).encode() if post else None, timeout=30)
            return json.loads(res) if code == 200 else {"error": "HTTP %d from %s" % (code, rec["id"])}
        except (OSError, ValueError) as e:
            return {"error": str(e)}

    def new_tree(self, alias, link, path, node):
        """DirAI init + start for a new folder on that machine (made if missing). Refused when the
        folder lies inside another tree or a git repo: DirAI init would set up that one instead."""
        p = '"$HOME"/' + shlex.quote(path[2:]) if path.startswith("~/") else shlex.quote(path)
        cmd = ('export PATH="$HOME/.local/bin:$PATH"; P=%s; mkdir -p "$P" && cd "$P" && P=$(pwd -P) || exit 1; '
               'd=$(dirname "$P"); while [ "$d" != / ]; do [ -s "$d/www/dirai.json" ] && '
               '{ echo "$P is inside the DirAI tree $d" >&2; exit 3; }; d=$(dirname "$d"); done; '
               'top=$(git rev-parse --show-toplevel 2>/dev/null); '
               'if [ -n "$top" ] && [ "$top" != "$P" ] && [ ! -s "$P/www/dirai.json" ]; then '
               'echo "$P is inside the git repo $top (init would serve all of $top)" >&2; exit 3; fi; '
               'DirAI init </dev/null && DirAI start %s' % (p, shlex.quote(node) if node else ""))
        try:
            r = link.run(cmd, timeout=180)
            lines = (r.stderr.strip() or r.stdout.strip()).splitlines()
            self.notes[alias] = ("new tree %s: started" % path) if r.returncode == 0 else \
                "new tree %s failed: %s" % (path, lines[-1] if lines else "exit %d" % r.returncode)
        except subprocess.TimeoutExpired:
            self.notes[alias] = "new tree %s: DirAI start took over 3 min" % path
        self.wake.set()

    def start_tree(self, rec):
        link = self.links.get(rec["host"])
        if not link:
            self.busy.pop(rec["id"], None)
            return
        try:
            r = link.run('PATH="$HOME/.local/bin:$PATH" DirAI -C %s start' % shlex.quote(rec["root"]), timeout=180)
            if r.returncode != 0:
                lines = (r.stderr.strip() or r.stdout.strip()).splitlines()
                rec["error"] = lines[-1] if lines else "DirAI start failed"
        except subprocess.TimeoutExpired:
            rec["error"] = "DirAI start took over 3 min"
        self.busy.pop(rec["id"], None)
        self.wake.set()

    def stop_tree(self, rec, op="stop"):
        """DirAI stop (or forget) for rec's tree on its machine, over the link (the mirror of start_tree).
        The outcome, with DirAI's own last line, goes in a note that stays until the next action: the
        tree's for a stop (rec["error"] would be gone at the next poll); the machine's for a forget, since
        the tree itself leaves the list at the next poll."""
        link, at = self.links.get(rec["host"]), op + " " + time.strftime("%H:%M") + ": "
        key = rec["id"] if op == "stop" else rec["host"]
        cmd = ('DirAI -C %s stop' if op == "stop" else 'DirAI forget %s') % shlex.quote(rec["root"])
        if link:
            try:
                r = link.run('PATH="$HOME/.local/bin:$PATH" ' + cmd, timeout=120)
                lines = (r.stdout.strip() + "\n" + r.stderr.strip()).strip().splitlines()
                if r.returncode != 0:
                    self.notes[key] = at + "failed (exit %d): %s" % (r.returncode, lines[-1] if lines else "no output")
                else:
                    self.notes[key] = at + (lines[-1] if lines else "done")
            except subprocess.TimeoutExpired:
                self.notes[key] = at + "failed: DirAI %s took over 2 min" % op
        else:
            self.notes[key] = at + "failed: no ssh link to %s (Connect it again, then try again)" % rec["host"]
        self.busy.pop(rec["id"], None)
        self.wake.set()


if __name__ == "__main__":
    if sys.argv[1:] == ["--list"]:
        print(json.dumps(machine_report()))
    else:
        sys.exit(__doc__)
