import unittest

from mbl.checks import safety_errors


class SafetyErrorsTest(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(safety_errors(60000, 58000, []), [])

    def test_required_failed(self):
        errors = safety_errors(60000, 58000, ["spamhaus-drop"])
        self.assertEqual(len(errors), 1)
        self.assertIn("spamhaus-drop", errors[0])

    def test_below_min(self):
        self.assertEqual(len(safety_errors(4999, None, [])), 1)

    def test_above_max(self):
        self.assertEqual(len(safety_errors(150001, None, [])), 1)

    def test_big_drop(self):
        self.assertEqual(len(safety_errors(20000, 60000, [])), 1)

    def test_first_run_no_previous(self):
        self.assertEqual(safety_errors(60000, None, []), [])


if __name__ == "__main__":
    unittest.main()
