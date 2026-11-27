#!/usr/bin/env python3
"""Run a long command in the background as a job the DirAI server tracks, on a machine without SLURM
(or for work that must stay local). The agent stays "working" while it runs and is messaged with its
exit code and the end of its log when it ends (lib/jobs.py).

  python3 dirai_job.py run [--name NAME] [--log FILE] [--mem CAP] -- CMD [ARG...]
      starts CMD detached (own session; survives the end of the agent's run) in the current folder,
      output to FILE (default .dirai_jobs/<id>.log), and prints "Submitted local job L<n>".
      CAP limits the memory of CMD and all its children together (cgroup MemoryMax, no swap, via
      systemd-run --user): "80%" of RAM by default ($DIRAI_JOB_MEM), or "2G", "512M", "none". Over it,
      the job is killed, not the machine.
  python3 dirai_job.py list            this agent's jobs, one JSON line each: queued SLURM jobs, then
                                       the local jobs and Modal calls recorded here (running or ended)
  python3 dirai_job.py cancel L<n>     stop one (SIGTERM to its process group)

The record goes in $DIRAI_AGENT_DIR/.dirai_jobs/ (the agent's folder; the current folder when that
isn't set). Don't wait for the job or poll it: end your reply; the server messages you when it ends.
"""
import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "lib"))
import jobs  # noqa: E402


def folder():
    return os.path.realpath(os.environ.get("DIRAI_AGENT_DIR") or os.getcwd())


def mem_total():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return None


def mem_limit(spec):
    """Bytes for a --mem value: "none", "80%" (of the machine's RAM), or "2G" / "512M" / bytes."""
    spec = (spec or "").strip().upper()
    if spec in ("", "NONE", "0"):
        return None
    if spec.endswith("%"):
        total = mem_total()
        return int(total * float(spec[:-1]) / 100) if total else None
    mult = {"K": 1 << 10, "M": 1 << 20, "G": 1 << 30, "T": 1 << 40}.get(spec[-1:])
    return int(float(spec[:-1]) * mult) if mult else int(spec)


def mem_wrap(cmd, spec):
    """Run CMD in its own cgroup with MemoryMax (and no swap), so it and all its children together are
    killed when they go over the cap, instead of the machine running out of memory. Needs systemd's
    user manager (systemd-run --user); without it the job runs uncapped and the log says so."""
    limit = mem_limit(spec)
    if not limit:
        return cmd, None
    probe = subprocess.run(["systemd-run", "--user", "--scope", "--quiet", "true"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) if _which("systemd-run") else None
    if not probe or probe.returncode:
        print("dirai_job: no systemd-run --user here, so the memory cap (%s) is not applied" % spec, flush=True)
        return cmd, None
    cap = "%dM" % (limit >> 20)
    return ["systemd-run", "--user", "--scope", "--quiet", "-p", "MemoryMax=" + cap, "-p", "MemorySwapMax=0", "--"] + cmd, cap


def _which(name):
    return any(os.access(os.path.join(p, name), os.X_OK) for p in os.environ.get("PATH", "").split(os.pathsep) if p)


def run(args):
    if not args.cmd:
        sys.exit("dirai_job: no command (put it after --)")
    home = folder()
    jid = jobs.new_local_id(home)
    d = jobs.records_dir(home)
    log = os.path.abspath(args.log) if args.log else os.path.join(d, jid + ".log")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    cwd = os.getcwd()
    rec_path = os.path.join(d, jid + ".json")
    r, w = os.pipe()
    if os.fork():                                   # the caller: wait for the supervisor's pid, then report
        os.close(w)
        data = b""
        while True:
            chunk = os.read(r, 64)
            if not chunk:
                break
            data += chunk
        os.close(r)
        if not data.strip():
            sys.exit("dirai_job: the job did not start")
        print("Submitted local job %s (pid %s): %s\nlog: %s" % (jid, data.decode().strip(),
                                                                shlex.join(args.cmd), log))
        return
    os.close(r)
    os.setsid()                                      # its own session: not killed with the agent's run
    if os.fork():
        os._exit(0)
    pid = os.getpid()
    jobs._write(rec_path, {"id": jid, "kind": "local", "name": args.name or os.path.basename(args.cmd[0]),
                           "cmd": shlex.join(args.cmd), "workdir": cwd, "log": log, "mem": args.mem, "pid": pid, "sid": pid,
                           "start": jobs.proc_start(pid), "started": time.time()})
    os.write(w, str(pid).encode())
    os.close(w)
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    with open(log, "ab") as out:
        os.dup2(out.fileno(), 1)
        os.dup2(out.fileno(), 2)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    cmd, cap = mem_wrap(args.cmd, args.mem)
    print("dirai_job: memory cap %s" % (cap or "none"), flush=True)
    try:
        code = subprocess.call(cmd, cwd=cwd)
    except OSError as e:
        print("dirai_job: cannot start %s: %s" % (args.cmd[0], e), flush=True)
        code = 127
    if cap and code in (-9, 137):
        print("dirai_job: killed by SIGKILL; most likely it went over the memory cap (%s)" % cap, flush=True)
    with open(os.path.join(d, jid + ".exit.tmp"), "w") as f:
        f.write("%d %.3f\n" % (code, time.time()))
    os.replace(os.path.join(d, jid + ".exit.tmp"), os.path.join(d, jid + ".exit"))
    os._exit(0)


def listing(_args):
    """The agent's jobs: its queued SLURM jobs (from sacct, if this machine has it), then every local
    job and Modal call recorded in its folder, running or ended."""
    home = folder()
    for j in jobs.agent_jobs(home, poll=False, slurm_jobs=jobs.slurm_active() or []):
        if j["kind"] == "slurm":
            print(json.dumps({"id": j["id"], "kind": "slurm", "name": j["name"], "state": j["state"],
                              "time": j["time"], "where": j["where"], "workdir": j["workdir"]}))
    for rec in jobs.records(home):
        if rec.get("kind") == "modal":
            state = (rec.get("state") or "running").upper()
        else:
            state = jobs.local_state(home, rec)
        print(json.dumps({"id": rec["id"], "kind": rec.get("kind"), "name": rec.get("name"), "state": state,
                          "cmd": rec.get("cmd"), "log": rec.get("log")}))


def cancel(args):
    print(jobs.cancel(args.id, folder()))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="what", required=True)
    p = sub.add_parser("run")
    p.add_argument("--name")
    p.add_argument("--log")
    p.add_argument("--mem", default=os.environ.get("DIRAI_JOB_MEM", "80%"),
                   help="memory cap for the job and its children: 80%% of RAM (default), 2G, 512M, or none")
    p.add_argument("cmd", nargs=argparse.REMAINDER)
    sub.add_parser("list")
    c = sub.add_parser("cancel")
    c.add_argument("id")
    a = ap.parse_args()
    if a.what == "run":
        if a.cmd and a.cmd[0] == "--":
            a.cmd = a.cmd[1:]
        run(a)
    elif a.what == "list":
        listing(a)
    else:
        cancel(a)


if __name__ == "__main__":
    main()
