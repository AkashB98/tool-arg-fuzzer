"""Determinism: the full fuzz report is byte-identical across runs."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fuzzer import generate_corpus  # noqa: E402
from runner import report_json, run_corpus  # noqa: E402
from schemas import TOOL_SCHEMAS, get_schema  # noqa: E402
from targets import (fragile_create_work_order, fragile_place_order,  # noqa: E402
                     robust_create_work_order)


def _report(schema_name, target, seed):
    corpus = generate_corpus(get_schema(schema_name), seed)
    return report_json(run_corpus(target, corpus, schema_name=schema_name,
                                  seed=seed))


class TestDeterminism(unittest.TestCase):
    def test_report_byte_identical(self):
        a = _report("create_work_order", fragile_create_work_order, 7)
        b = _report("create_work_order", fragile_create_work_order, 7)
        self.assertEqual(a, b)

    def test_report_byte_identical_place_order(self):
        a = _report("place_order", fragile_place_order, 7)
        b = _report("place_order", fragile_place_order, 7)
        self.assertEqual(a, b)

    def test_report_byte_identical_robust(self):
        a = _report("create_work_order", robust_create_work_order, 7)
        b = _report("create_work_order", robust_create_work_order, 7)
        self.assertEqual(a, b)

    def test_different_seed_different_report(self):
        a = _report("create_work_order", fragile_create_work_order, 7)
        b = _report("create_work_order", fragile_create_work_order, 8)
        self.assertNotEqual(a, b)

    def test_all_schemas_deterministic(self):
        for name in TOOL_SCHEMAS:
            a = _report(name, fragile_create_work_order, 7)
            b = _report(name, fragile_create_work_order, 7)
            self.assertEqual(a, b, name)


if __name__ == "__main__":
    unittest.main()
