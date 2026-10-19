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

    def test_exact_min_and_max_pass(self):
        self.assertEqual(safety_errors(5000, None, []), [])
        self.assertEqual(safety_errors(150000, None, []), [])

    def test_exact_50_percent_drop_passes(self):
        self.assertEqual(safety_errors(30000, 60000, []), [])

    def test_previous_total_zero_skips_drop_check(self):
        self.assertEqual(safety_errors(60000, 0, []), [])

    def test_exact_double_growth_passes(self):
        self.assertEqual(safety_errors(60000, 30000, []), [])

    def test_growth_above_double_fails(self):
        errors = safety_errors(60001, 30000, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("grew", errors[0])

    def test_growth_check_skipped_without_previous(self):
        self.assertEqual(safety_errors(140000, None, []), [])
        self.assertEqual(safety_errors(140000, 0, []), [])

    def test_custom_max_growth(self):
        self.assertEqual(len(safety_errors(45001, 30000, [], max_growth=1.5)), 1)

    def test_allow_growth_skips_only_growth_check(self):
        self.assertEqual(safety_errors(60001, 30000, [], allow_growth=True), [])
        self.assertEqual(len(safety_errors(150001, 30000, [], allow_growth=True)), 1)
        self.assertEqual(len(safety_errors(10000, 30000, [], allow_growth=True)), 1)
        self.assertEqual(len(safety_errors(60001, 30000, ["x"], allow_growth=True)), 1)

    def test_multiple_problems_multiple_errors(self):
        errors = safety_errors(1000, 60000, ["spamhaus-drop"])
        self.assertEqual(len(errors), 3)


if __name__ == "__main__":
    unittest.main()
