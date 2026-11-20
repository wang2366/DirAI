"""agent_list.TEMPLATE: the page opens sorted by Modified, newest first, and keeps the owner's sort."""
import unittest

from tests import util  # noqa: F401  (puts lib/ on the path)

import agent_list


class DefaultSortTest(unittest.TestCase):
    def setUp(self):
        self.page = agent_list.TEMPLATE.format(title="t", count=0, generated="g", rows="")

    def test_modified_is_the_default_column(self):
        self.assertIn("let sortCol = 1, sortDir = -1;", self.page)
        self.assertIn("resort();\n</script>", self.page)

    def test_sort_is_kept(self):
        self.assertIn('localStorage.setItem("dirai-agent-sort"', self.page)
        self.assertIn('localStorage.getItem("dirai-agent-sort")', self.page)

    def test_pinned_rows_stay_on_top(self):
        self.assertIn("r.dataset.pin", self.page)


if __name__ == "__main__":
    unittest.main()
