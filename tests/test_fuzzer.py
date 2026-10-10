"""Tests for the seeded corpus generator."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fuzzer import corpus_md5, generate_corpus  # noqa: E402
from schemas import TOOL_SCHEMAS, get_schema  # noqa: E402


class TestCorpus(unittest.TestCase):
    def setUp(self):
        self.schema = get_schema("create_work_order")

    def test_baseline_is_first_and_valid(self):
        corpus = generate_corpus(self.schema, 7)
        first = corpus[0]
        self.assertEqual(first["index"], 0)
        self.assertEqual(first["mutation"], "valid_baseline")
        self.assertEqual(first["path"], "$")
        payload = first["payload"]
        self.assertIn("title", payload)
        self.assertIn("priority", payload)
        self.assertGreaterEqual(len(payload["title"]), 3)

    def test_deterministic_same_seed(self):
        a = generate_corpus(self.schema, 7)
        b = generate_corpus(self.schema, 7)
        self.assertEqual(corpus_md5(a), corpus_md5(b))
        self.assertEqual(
            json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_different_seed_differs(self):
        a = generate_corpus(self.schema, 7)
        b = generate_corpus(self.schema, 8)
        self.assertNotEqual(corpus_md5(a), corpus_md5(b))

    def test_corpus_is_json_serializable(self):
        corpus = generate_corpus(self.schema, 7)
        blob = json.dumps(corpus, sort_keys=True)
        self.assertTrue(blob)

    def test_mutation_catalog_coverage(self):
        # union across both seed schemas: create_work_order has no integer
        # or object properties, place_order exercises those branches
        labels = set()
        for name in TOOL_SCHEMAS:
            corpus = generate_corpus(get_schema(name), 7)
            labels |= {e["mutation"] for e in corpus}
        required = {
            "valid_baseline",
            "missing_required", "null_required",
            "empty_string", "giant_string", "whitespace_only",
            "unicode_invisible", "unicode_rtl_override", "control_chars",
            "below_min_length", "above_max_length",
            "below_minimum", "above_maximum",
            "huge_integer", "float_for_integer", "bool_for_integer",
            "numeric_string_for_number", "nan_string_for_number", "huge_float",
            "string_for_boolean", "int_for_boolean",
            "enum_outside_value", "enum_case_flipped", "enum_empty_string",
            "empty_array", "above_max_items", "huge_array", "wrong_item_types",
            "deep_nesting_array", "deep_nesting_object",
            "extra_nested_property", "extra_property_string",
            "extra_property_object", "deep_nesting_extra_property",
            "empty_object", "top_level_list", "top_level_string",
            "top_level_number", "top_level_null", "deep_nesting_top",
            "unicode_bomb",
        }
        missing = required - labels
        self.assertFalse(missing, f"missing mutations: {missing}")
        # wrong-type swaps present for every declared type
        swaps = {m for m in labels if m.startswith("type_swap_")}
        self.assertTrue(swaps)

    def test_missing_required_actually_drops_key(self):
        corpus = generate_corpus(self.schema, 7)
        dropped = [e for e in corpus if e["mutation"] == "missing_required"]
        self.assertTrue(dropped)
        for e in dropped:
            key = e["path"][2:]
            self.assertNotIn(key, e["payload"])

    def test_paths_are_flat_json_paths(self):
        corpus = generate_corpus(self.schema, 7)
        for e in corpus:
            self.assertTrue(e["path"] == "$" or e["path"].startswith("$."),
                            e["path"])
            self.assertNotIn(".", e["path"][2:])

    def test_indexes_are_sequential(self):
        corpus = generate_corpus(self.schema, 7)
        self.assertEqual([e["index"] for e in corpus],
                         list(range(len(corpus))))

    def test_both_seed_schemas_generate(self):
        for name in TOOL_SCHEMAS:
            corpus = generate_corpus(get_schema(name), 7)
            self.assertGreater(len(corpus), 40, name)

    def test_minimal_schema_does_not_crash_generator(self):
        corpus = generate_corpus({"type": "object"}, 7)
        self.assertTrue(corpus)
        corpus = generate_corpus(
            {"type": "object",
             "properties": {"x": {"type": "string"}}}, 7)
        self.assertTrue(any(e["mutation"] == "empty_string" for e in corpus))


if __name__ == "__main__":
    unittest.main()
