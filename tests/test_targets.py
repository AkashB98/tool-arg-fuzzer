"""Tests for the demo targets themselves."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fuzzer import generate_corpus  # noqa: E402
from runner import _run_once  # noqa: E402
from schemas import get_schema  # noqa: E402
from targets import (ArgumentError, fragile_create_work_order,  # noqa: E402
                     fragile_place_order, robust_create_work_order)


class TestTargets(unittest.TestCase):
    def test_fragile_accepts_baseline(self):
        baseline = generate_corpus(
            get_schema("create_work_order"), 7)[0]["payload"]
        self.assertIsNone(_run_once(fragile_create_work_order, baseline))

    def test_fragile_place_order_accepts_baseline(self):
        baseline = generate_corpus(get_schema("place_order"), 7)[0]["payload"]
        self.assertIsNone(_run_once(fragile_place_order, baseline))

    def test_robust_accepts_baseline(self):
        baseline = generate_corpus(
            get_schema("create_work_order"), 7)[0]["payload"]
        result = robust_create_work_order(baseline)
        self.assertTrue(result["ok"])

    def test_robust_rejects_with_argument_error_only(self):
        """Every corpus payload is clean or an ArgumentError -- never a crash."""
        corpus = generate_corpus(get_schema("create_work_order"), 7)
        for entry in corpus:
            exc = _run_once(robust_create_work_order, entry["payload"])
            self.assertTrue(
                exc is None or isinstance(exc, ArgumentError),
                f"{entry['mutation']}: unexpected {type(exc).__name__}: {exc}")

    def test_robust_rejects_with_path_in_message(self):
        exc = _run_once(robust_create_work_order, {"priority": "high"})
        self.assertIsInstance(exc, ArgumentError)
        self.assertIn("$.title", str(exc))

    def test_robust_rejects_unknown_property(self):
        baseline = generate_corpus(
            get_schema("create_work_order"), 7)[0]["payload"]
        baseline["nope"] = 1
        exc = _run_once(robust_create_work_order, baseline)
        self.assertIsInstance(exc, ArgumentError)

    def test_robust_handles_empty_tags(self):
        # regression: .get("tags", ["-"])[0] crashed on explicitly-empty tags
        baseline = generate_corpus(
            get_schema("create_work_order"), 7)[0]["payload"]
        baseline["tags"] = []
        result = robust_create_work_order(baseline)
        self.assertTrue(result["ok"])
        self.assertEqual(result["first_tag"], "-")


if __name__ == "__main__":
    unittest.main()
