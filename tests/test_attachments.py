"""attachments: files dropped on the chat panel, saved in the agent's pasted/."""
import base64
import os
import unittest

from tests import util

import attachments


def b64(raw):
    return base64.b64encode(raw).decode()


class AttachmentsTest(unittest.TestCase):
    def setUp(self):
        self.dir = util.new_tree("attach-" + self.id().rsplit(".", 1)[1])

    def test_names(self):
        self.assertEqual(attachments.clean_name("../../etc/pass wd"), "pass_wd")
        self.assertEqual(attachments.clean_name("C:\\Users\\me\\a b.pdf"), "a_b.pdf")
        self.assertEqual(attachments.clean_name(".bashrc"), "bashrc")
        self.assertEqual(attachments.clean_name(""), "file")
        self.assertEqual(attachments.clean_name("index.html"), "index.html.txt")
        self.assertEqual(attachments.clean_name("Page.HTM"), "Page.HTM.txt")
        self.assertEqual(len(attachments.clean_name("x" * 300 + ".png")), attachments.NAME_MAX)
        self.assertTrue(attachments.clean_name("x" * 300 + ".png").endswith(".png"))

    def test_save_and_collisions(self):
        a = attachments.save(self.dir, "image.png", b64(b"\x89PNG\r\n\x1a\n1"))
        b = attachments.save(self.dir, "image.png", b64(b"\x89PNG\r\n\x1a\n2"))
        self.assertTrue(a.startswith("pasted/") and a.endswith("_image.png"))
        self.assertNotEqual(a, b)
        with open(os.path.join(self.dir, a), "rb") as f:
            self.assertEqual(f.read(), b"\x89PNG\r\n\x1a\n1")
        self.assertTrue(attachments.save(self.dir, "notes.csv", b64(b"a,b\n")).endswith("_notes.csv"))
        self.assertTrue(attachments.save(self.dir, "p.pdf", b64(b"%PDF-1.7 ...")).endswith("_p.pdf"))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "pasted", "index.html")))

    def test_refused(self):
        for name, data in (("a.png", b64(b"not a png")), ("a.pdf", b64(b"<html>")), ("a.txt", ""),
                           ("a.txt", "not base64!"), ("a.txt", None)):
            with self.assertRaises(ValueError, msg=name):
                attachments.save(self.dir, name, data)
        with self.assertRaises(ValueError):
            attachments.save(self.dir, "big.bin", b64(b"0" * (attachments.FILE_MAX + 1)))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "pasted")) and os.listdir(os.path.join(self.dir, "pasted")))


if __name__ == "__main__":
    unittest.main()
