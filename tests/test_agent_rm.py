"""agent_rm.sh must work with a BSD-style realpath (no -e), as on macOS."""
import os
import subprocess
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "agent_rm.sh"
BSD_REALPATH = "#!/bin/bash\necho 'realpath: illegal option -- e' >&2\nexit 1\n"


def run(agent, *paths, env_agent=True):
    with tempfile.TemporaryDirectory() as fake:
        rp = Path(fake) / "realpath"
        rp.write_text(BSD_REALPATH)
        rp.chmod(0o755)
        env = {**os.environ, "PATH": f"{fake}:{os.environ['PATH']}"}
        env.pop("DIRAI_AGENT_DIR", None)
        if env_agent:
            env["DIRAI_AGENT_DIR"] = str(agent)
        return subprocess.run(["bash", str(SCRIPT), *map(str, paths)], env=env,
                              capture_output=True, text=True)


def test_deletes_inside_folder_with_bsd_realpath(tmp_path):
    agent = tmp_path / "agent"; agent.mkdir()
    f = agent / "a.txt"; f.write_text("x")
    r = run(agent, f)
    assert r.returncode == 0, r.stderr
    assert not f.exists()


def test_refuses_outside_dotdot_and_agent_folder(tmp_path):
    agent = tmp_path / "agent"; agent.mkdir()
    out = tmp_path / "out.txt"; out.write_text("x")
    assert run(agent, out).returncode == 1 and out.exists()
    assert run(agent, agent / ".." / "out.txt").returncode == 1 and out.exists()
    assert run(agent, agent).returncode == 1 and agent.exists()


def test_symlink_removed_not_target(tmp_path):
    agent = tmp_path / "agent"; agent.mkdir()
    out = tmp_path / "out.txt"; out.write_text("x")
    link = agent / "l"; link.symlink_to(out)
    assert run(agent, link).returncode == 0
    assert not link.is_symlink() and out.exists()


def test_distinct_messages(tmp_path):
    r = run(tmp_path, tmp_path / "x", env_agent=False)
    assert r.returncode == 2 and "not set" in r.stderr
    r = run(tmp_path / "missing", tmp_path / "x")
    assert r.returncode == 2 and "does not exist" in r.stderr
