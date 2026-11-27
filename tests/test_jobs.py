"""jobs.py and scripts/dirai_job.py: local jobs (started, adopted), Modal calls (with a stand-in for
the poll helper's Python) and the ids a run's output names."""
import json
import os
import stat
import subprocess
import sys
import time
import unittest
from unittest import mock

from tests import util

import claude_run
import jobs

DIRAI_JOB = os.path.join(util.TOOL, "scripts", "dirai_job.py")
sys.path.insert(0, os.path.dirname(DIRAI_JOB))
import dirai_job  # noqa: E402
FC1, FC2 = "fc-01M802JHKV6EGWE1TXR87GA3JQ", "fc-01M7PHV030SQH3BHPVV2BCYB2S"


def wait_for(cond, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


class JobIds(unittest.TestCase):
    def test_ids_of_every_kind(self):
        text = ("Submitted batch job 123\nSubmitted local job L4 (pid 99): bash x.sh\n"
                '{"video_id": "v", "spawned": "%s"}\nSubmitted batch job 123\n' % FC1)
        self.assertEqual(claude_run.job_ids(text), ["123", "L4", FC1])
        self.assertEqual([jobs.kind(i) for i in ("123", "L4", FC1)], ["slurm", "local", "modal"])
        self.assertEqual(jobs.base_id("12_[3-4]"), "12")


@unittest.skipUnless(os.path.isdir("/proc"), "needs /proc")
class LocalJobs(unittest.TestCase):
    def setUp(self):
        self.agent = os.path.join(util.new_tree("jobs-" + self.id().rsplit(".", 1)[1]), "a")
        os.makedirs(self.agent)
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
                p.wait()

    def test_dirai_job_run_to_failure(self):
        env = dict(os.environ, DIRAI_AGENT_DIR=self.agent)
        out = subprocess.run([sys.executable, DIRAI_JOB, "run", "--name", "fit", "--",
                              "bash", "-c", "echo start; sleep 1; echo BAD FIT; exit 3"],
                             cwd=self.agent, env=env, stdout=subprocess.PIPE, timeout=20).stdout.decode()
        self.assertEqual(claude_run.job_ids(out), ["L1"], out)
        running = jobs.agent_jobs(self.agent, slurm_jobs=[])
        self.assertEqual([(j["id"], j["kind"], j["state"], j["sub"]) for j in running], [("L1", "local", "RUNNING", ".")])
        self.assertTrue(wait_for(lambda: jobs.local_exit(self.agent, "L1")))
        self.assertEqual(jobs.agent_jobs(self.agent, slurm_jobs=[]), [])
        rep = jobs.report(["L1"], self.agent)
        self.assertIn("L1  fit  FAILED", rep)
        self.assertIn("exit 3", rep)
        self.assertIn("BAD FIT", rep)
        # list and a second id
        out = subprocess.run([sys.executable, DIRAI_JOB, "run", "--", "sleep", "30"], cwd=self.agent, env=env,
                             stdout=subprocess.PIPE, timeout=20).stdout.decode()
        self.assertIn("Submitted local job L2", out)
        listed = [json.loads(l) for l in subprocess.run([sys.executable, DIRAI_JOB, "list"], cwd=self.agent, env=env,
                                                        stdout=subprocess.PIPE).stdout.decode().splitlines()]
        self.assertEqual([(x["id"], x["state"]) for x in listed], [("L1", "FAILED"), ("L2", "RUNNING")])
        out = subprocess.run([sys.executable, DIRAI_JOB, "cancel", "L2"], cwd=self.agent, env=env,
                             stdout=subprocess.PIPE).stdout.decode()
        self.assertIn("stopped", out)
        out = subprocess.run([sys.executable, DIRAI_JOB, "run", "--name", "sweep", "--", "sleep", "30"], cwd=self.agent,
                             env=env, stdout=subprocess.PIPE, timeout=20).stdout.decode()
        self.assertIn("L3", out)
        import slurm
        with mock.patch.object(slurm, "active_jobs", lambda: []):
            bar = slurm.status_bar(self.agent)
        self.assertIn("<code>L3</code> sweep &middot; local &middot; RUNNING", bar)
        jobs.cancel("L3", self.agent)
        self.assertTrue(wait_for(lambda: jobs.local_state(self.agent, jobs.find("L2", [self.agent])[1]) != "RUNNING"))

    def test_memory_cap_kills_the_job_not_the_machine(self):
        if subprocess.run(["systemd-run", "--user", "--scope", "--quiet", "true"], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode if os.path.exists("/usr/bin/systemd-run") else 1:
            self.skipTest("no systemd-run --user")
        env = dict(os.environ, DIRAI_AGENT_DIR=self.agent)
        hog = "b = bytearray(300 << 20); print('allocated')"
        for mem, want in (("100M", "FAILED"), ("none", "COMPLETED")):
            out = subprocess.run([sys.executable, DIRAI_JOB, "run", "--mem", mem, "--", sys.executable, "-c", hog],
                                 cwd=self.agent, env=env, stdout=subprocess.PIPE, timeout=20).stdout.decode()
            jid = claude_run.job_ids(out)[0]
            self.assertTrue(wait_for(lambda: jobs.local_exit(self.agent, jid), 30))
            rep = jobs.report([jid], self.agent)
            self.assertIn(want, rep, rep)
        self.assertIn("memory cap (100M)", jobs.report(["L1"], self.agent))
        self.assertEqual(dirai_job.mem_limit("2G"), 2 << 30)
        self.assertIsNone(dirai_job.mem_limit("none"))
        self.assertGreater(dirai_job.mem_limit("50%"), 0)

    def test_adopts_a_detached_process_once(self):
        since = time.time() - 1
        p = subprocess.Popen(["sleep", "30"], cwd=self.agent, start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.append(p)
        other = os.path.join(os.path.dirname(self.agent), "b")
        os.makedirs(other)
        q = subprocess.Popen(["sleep", "30"], cwd=other, start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.append(q)                     # another folder's: not this agent's
        wait_for(lambda: jobs.proc_start(p.pid) is not None)
        self.assertEqual(jobs.adopt_strays(self.agent, since), ["L1"])
        self.assertEqual(jobs.adopt_strays(self.agent, since), [])          # already recorded
        rec = jobs.find("L1", [self.agent])[1]
        self.assertEqual((rec["pid"], rec["adopted"]), (p.pid, True))
        self.assertEqual(jobs.local_state(self.agent, rec), "RUNNING")
        self.assertEqual(jobs.adopt_strays(self.agent, time.time() + 5), [])  # started before the run: no
        p.kill()
        p.wait()
        self.assertEqual(jobs.local_state(self.agent, rec), "ENDED")
        self.assertIn("no exit code (adopted process", jobs.report(["L1"], self.agent))

    def test_reused_pid_is_not_alive(self):
        self.assertFalse(jobs.alive(os.getpid(), "1"))
        self.assertTrue(jobs.alive(os.getpid(), jobs.proc_start(os.getpid())))


class ModalJobs(unittest.TestCase):
    def setUp(self):
        self.agent = os.path.join(util.new_tree("jobs-modal"), "a")
        os.makedirs(self.agent)
        self.states = os.path.join(util.TMP, "modal_states.json")
        fake = os.path.join(util.TMP, "fake_modal_python")
        util.write(fake, "#!%s\nimport json, sys\nst = json.load(open(%r))\nfor i in sys.argv[2:]:\n"
                         "    s = st.get(i, ['unknown', 'not found'])\n"
                         "    print(json.dumps({'id': i, 'state': s[0], 'detail': s[1]}))\n" % (sys.executable, self.states))
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
        self.env = mock.patch.dict(os.environ, {"DIRAI_MODAL_PYTHON": fake})
        self.env.start()
        jobs._modal_cache.clear()

    def tearDown(self):
        self.env.stop()

    def set_states(self, st):
        util.write(self.states, json.dumps(st))

    def test_register_poll_and_report(self):
        self.set_states({FC1: ["running", ""], FC2: ["finished", "{'state': 'done'}"]})
        self.assertEqual(jobs.register_modal(self.agent, [FC1, FC2, FC1]), [FC1])   # FC2 is over already
        self.assertEqual([j["id"] for j in jobs.agent_jobs(self.agent, slurm_jobs=[])], [FC1])
        self.set_states({FC1: ["finished", "{'state': 'failed', 'stage': 'court_fit'}"]})
        self.assertEqual([j["id"] for j in jobs.agent_jobs(self.agent, slurm_jobs=[])], [FC1])  # asked < 240 s ago
        self.assertEqual(jobs.agent_jobs(self.agent, slurm_jobs=[], fresh=True), [])
        rep = jobs.report([FC1], self.agent)
        self.assertIn("Modal call  FINISHED", rep)
        self.assertIn("'stage': 'court_fit'", rep)

    def test_no_python_means_no_watch(self):
        with mock.patch.dict(os.environ, {"DIRAI_MODAL_PYTHON": ""}), mock.patch.object(jobs.shutil, "which", lambda n: None):
            self.assertIsNone(jobs.modal_python(self.agent))
            self.assertEqual(jobs.register_modal(self.agent, [FC1]), [])


if __name__ == "__main__":
    unittest.main()
