"""CPU and memory of the machine serving a tree, for the list page header (owner only).

load() returns the whole machine's CPU busy % and memory in use, plus what this server's process
group uses: html_server.py and everything it starts (assistant runs, list rebuilds), since
dirai_serve runs in its own session. No extra packages: Linux reads /proc, macOS asks
sysctl, vm_stat and ps. Readings are cached for CACHE_S, so several open list pages cost one.
"""
import os
import platform
import subprocess
import threading
import time

CACHE_S = 5
_lock = threading.Lock()
_cache = {"time": 0.0, "load": None}
_last_stat = None   # Linux: previous /proc/stat totals, for CPU % since the last reading


def _run(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          universal_newlines=True, timeout=5).stdout


def _proc_stat():
    with open("/proc/stat") as f:
        vals = [int(v) for v in f.readline().split()[1:]]
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)   # idle + iowait
    return sum(vals), idle


def _linux_cpu():
    """Busy % of all CPUs since the previous call (over a short sample on the first)."""
    global _last_stat
    if _last_stat is None:
        _last_stat = _proc_stat()
        time.sleep(0.2)
    total, idle = _proc_stat()
    dt, di = total - _last_stat[0], idle - _last_stat[1]
    _last_stat = (total, idle)
    return 100.0 * (dt - di) / dt if dt > 0 else 0.0


def _linux_mem():
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, v = line.split(":", 1)
            info[k] = int(v.split()[0]) * 1024
    total = info["MemTotal"]
    avail = info.get("MemAvailable", info.get("MemFree", 0) + info.get("Cached", 0))
    return total, total - avail


def _mac_mem():
    """In use the way Activity Monitor counts it: active + wired + compressed pages."""
    total = int(_run(["sysctl", "-n", "hw.memsize"]))
    out = _run(["vm_stat"])
    page = int(out.split("page size of")[1].split()[0]) if "page size of" in out else 4096
    pages = {}
    for line in out.splitlines()[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            pages[k.strip()] = int(v.strip().rstrip("."))
    used = sum(pages.get(k, 0) for k in ("Pages active", "Pages wired down", "Pages occupied by compressor"))
    return total, used * page


def _processes():
    """[(pgid, %cpu, rss bytes)] for every process (ps works the same on Linux and macOS)."""
    rows = []
    for line in _run(["ps", "-A", "-o", "pgid=,%cpu=,rss="]).splitlines():
        parts = line.split()
        if len(parts) == 3:
            try:
                rows.append((int(parts[0]), float(parts[1]), int(parts[2]) * 1024))
            except ValueError:
                pass
    return rows


def _read():
    cpus = os.cpu_count() or 1
    procs = _processes()
    if os.path.exists("/proc/stat"):
        cpu = _linux_cpu()
        mem_total, mem_used = _linux_mem()
    else:   # macOS: ps %cpu is per process (100 = one CPU); summed over all CPUs
        cpu = min(100.0, sum(p[1] for p in procs) / cpus)
        mem_total, mem_used = _mac_mem()
    group = os.getpgrp()
    mine = [p for p in procs if p[0] == group]
    load1 = os.getloadavg()[0] if hasattr(os, "getloadavg") else None
    return {"host": platform.node().split(".")[0], "cpus": cpus, "cpu_percent": round(cpu, 1),
            "load1": round(load1, 2) if load1 is not None else None,
            "mem_total": mem_total, "mem_used": mem_used,
            # ps %cpu: share of one CPU (Linux: averaged over each process's lifetime)
            "dirai": {"procs": len(mine), "cpu_percent": round(sum(p[1] for p in mine), 1),
                      "rss": sum(p[2] for p in mine)},
            "checked": time.time()}


def load():
    with _lock:
        if _cache["load"] is None or time.time() - _cache["time"] >= CACHE_S:
            try:
                _cache["load"] = _read()
            except (OSError, ValueError, IndexError, KeyError, subprocess.SubprocessError) as e:
                _cache["load"] = {"error": str(e)}
            _cache["time"] = time.time()
        return _cache["load"]


if __name__ == "__main__":
    import json
    print(json.dumps(load(), indent=1))
