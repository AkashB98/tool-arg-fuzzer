"""Tests for the fuzz runner: crash classification and expected rejections."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fuzzer import generate_corpus  # noqa: E402
from runner import _run_once, report_json, run_corpus  # noqa: E402
from schemas import get_schema  # noqa: E402
from targets import (ArgumentError, fragile_create_work_order,  # noqa: E402
                     fragile_place_order, robust_create_work_order)


def _boom(_payload):
    raise RuntimeError("boom")


def _clean(_payload):
    return {"ok": True}


class TestRunner(unittest.TestCase):
    def setUp(self):
        self.corpus = generate_corpus(get_schema("create_work_order"), 7)

    def test_run_once_returns_exception_or_none(self):
        self.assertIsNone(_run_once(_clean, {"a": 1}))
        exc = _run_once(_boom, {"a": 1})
        self.assertIsInstance(exc, RuntimeError)

    def test_target_exception_does_not_escape(self):
        def nasty(_p):
            raise KeyboardInterrupt  # not an Exception subclass
        with self.assertRaises(KeyboardInterrupt):
            _run_once(nasty, {})
        # ...but ordinary exceptions are captured
        report = run_corpus(_boom, [{"index": 0, "mutation": "m",
                                     "path": "$", "payload": {}}],
                            shrink_crashes=False)
        self.assertEqual(report["unexpected_crashes"], 1)
        self.assertEqual(report["crashes"][0]["exc_class"], "RuntimeError")

    def test_fragile_target_crashes_are_classified(self):
        report = run_corpus(fragile_create_work_order, self.corpus,
                            schema_name="create_work_order", seed=7)
        self.assertGreater(report["unexpected_crashes"], 0)
        self.assertEqual(report["expected_rejections"], 0)
        self.assertEqual(report["corpus_size"], len(self.corpus))
        for crash in report["crashes"]:
            self.assertIn("exc_class", crash)
            self.assertIn("minimal_payload", crash)
            self.assertLessEqual(crash["minimal_size"],
                                 crash["original_size"])
            # minimal repro really reproduces the same crash class
            again = _run_once(fragile_create_work_order,
                              crash["minimal_payload"])
            self.assertIsNotNone(again)
            self.assertEqual(type(again).__name__, crash["exc_class"])

    def test_expected_exceptions_are_not_crashes(self):
        report = run_corpus(robust_create_work_order, self.corpus,
                            schema_name="create_work_order", seed=7)
        self.assertEqual(report["unexpected_crashes"], 0)
        self.assertEqual(report["crashes"], [])
        self.assertGreater(report["expected_rejections"], 0)
        self.assertEqual(report["unique_signatures"], [])

    def test_place_order_target(self):
        corpus = generate_corpus(get_schema("place_order"), 7)
        report = run_corpus(fragile_place_order, corpus,
                            schema_name="place_order", seed=7)
        self.assertGreater(report["unexpected_crashes"], 0)
        self.assertIn("ZeroDivisionError", report["unique_signatures"])

    def test_report_is_stable_json(self):
        report = run_corpus(fragile_create_work_order, self.corpus,
                            schema_name="create_work_order", seed=7)
        blob = report_json(report)
        self.assertEqual(json.loads(blob)["unexpected_crashes"],
                         report["unexpected_crashes"])
        # no timestamps anywhere in the report
        self.assertNotIn("2026", blob)

    def test_crashes_sorted_deterministically(self):
        report = run_corpus(fragile_create_work_order, self.corpus,
                            schema_name="create_work_order", seed=7)
        keys = [(c["exc_class"], c["mutation"], c["index"])
                for c in report["crashes"]]
        self.assertEqual(keys, sorted(keys))

    def test_argument_error_is_value_error(self):
        self.assertTrue(issubclass(ArgumentError, ValueError))


if __name__ == "__main__":
    unittest.main()
