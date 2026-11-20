"""The hop from where ssh lands to the node serving a tree (Link.tunnel with a node): it trusts a node
it hasn't seen (StrictHostKeyChecking=accept-new), and when it fails, Link.tunnel_error says why."""
import os
import stat
import unittest

from tests import util

import remotes

FAILING_SSH = """#!/bin/bash
printf '%s\\n' "$@" > "$0.args"
echo "Host key verification failed." >&2
exit 255
"""


class NodeTunnel(unittest.TestCase):
    def setUp(self):
        self.ssh = os.path.join(util.TMP, "hop_fails_ssh")
        util.write(self.ssh, FAILING_SSH)
        os.chmod(self.ssh, os.stat(self.ssh).st_mode | stat.S_IXUSR)
        self.keep, remotes.SSH = remotes.SSH, self.ssh
        self.link = remotes.Link("hop-test")

    def tearDown(self):
        remotes.SSH = self.keep
        self.link.close()

    def test_a_failed_hop_says_why(self):
        lport = remotes.free_port()
        self.assertFalse(self.link.tunnel(lport, 8766, node="login03", user="u"))
        self.assertEqual(self.link.tunnel_error(lport), "tunnel to u@login03: Host key verification failed.")
        self.assertEqual(self.link.tunnel_error(lport + 1), "")      # no tunnel there: nothing to say

    def test_the_hop_accepts_a_new_node_key(self):
        self.link.tunnel(remotes.free_port(), 8766, node="login03", user="u")
        with open(self.ssh + ".args") as f:
            args = f.read().splitlines()
        self.assertIn("StrictHostKeyChecking=accept-new", args)
        self.assertNotIn("StrictHostKeyChecking=no", args)


if __name__ == "__main__":
    unittest.main()
