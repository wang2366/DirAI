#!/usr/bin/env python3
"""Stand-in for ssh in the remotes tests (DIRAI_SSH): every host is this machine.

  -M -S CTL ... HOST          the master: creates CTL, waits until killed, then removes it
  -S CTL -O check HOST        0 while CTL exists
  -S CTL -O forward -L 127.0.0.1:L:127.0.0.1:R HOST   starts a relay L -> R (ends with the master)
  -S CTL -O cancel -L ...     stops that relay
  -S CTL ... HOST COMMAND     runs COMMAND with bash, in the environment of $FAKE_SSH_HOSTS/HOST.json
"""
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time


def relay(lport, rport, ctl):
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", lport))
    srv.listen(16)
    srv.settimeout(1)

    def pipe(a, b):
        try:
            while True:
                d = a.recv(65536)
                if not d:
                    break
                b.sendall(d)
        except OSError:
            pass
        finally:
            try:
                b.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    while os.path.exists(ctl):
        try:
            c, _ = srv.accept()
        except socket.timeout:
            continue
        try:
            u = socket.create_connection(("127.0.0.1", rport))
        except OSError:
            c.close()
            continue
        threading.Thread(target=pipe, args=(c, u), daemon=True).start()
        threading.Thread(target=pipe, args=(u, c), daemon=True).start()


def main(argv):
    if argv[:1] == ["--relay"]:
        return relay(int(argv[1]), int(argv[2]), argv[3])
    ctl = op = fwd = None
    master = False
    rest = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-S", "-O", "-L", "-o", "-W"):
            v = argv[i + 1]
            ctl = v if a == "-S" else ctl
            op = v if a == "-O" else op
            fwd = v if a == "-L" else fwd
            i += 2
        elif a == "-M":
            master, i = True, i + 1
        elif a.startswith("-"):
            i += 1
        else:
            rest = argv[i:]
            break
    host, command = rest[0], " ".join(rest[1:])
    if master:
        open(ctl, "w").close()
        signal.signal(signal.SIGTERM, lambda *a: (os.remove(ctl), sys.exit(0)))
        while True:
            time.sleep(1)
    if op == "check":
        return 0 if os.path.exists(ctl) else 255
    if op in ("forward", "cancel"):
        _, lport, _, rport = fwd.split(":")
        pidfile = "%s.%s" % (ctl, lport)
        if op == "forward":
            p = subprocess.Popen([sys.executable, __file__, "--relay", lport, rport, ctl], start_new_session=True,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with open(pidfile, "w") as f:
                f.write(str(p.pid))
            for _ in range(50):       # until it listens
                with socket.socket() as s:
                    if s.connect_ex(("127.0.0.1", int(lport))) == 0:
                        return 0
                time.sleep(0.1)
            return 1
        try:
            with open(pidfile) as f:
                os.kill(int(f.read()), signal.SIGTERM)
        except (OSError, ValueError):
            pass
        return 0
    with open(os.path.join(os.environ["FAKE_SSH_HOSTS"], host + ".json")) as f:
        env = dict(os.environ, **json.load(f))
    return subprocess.run(["bash", "-c", command], env=env).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
