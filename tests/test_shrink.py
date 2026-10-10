"""Tests for the delta-debugging shrinker."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shrink import _size, shrink  # noqa: E402


def _crashes_if_title_null(payload):
    return (isinstance(payload, dict) and "title" in payload
            and payload["title"] is None)


def _crashes_if_deep(payload):
    def depth(v, d=0):
        if isinstance(v, dict):
            return max([depth(x, d + 1) for x in v.values()] + [d])
        if isinstance(v, list):
            return max([depth(x, d + 1) for x in v] + [d])
        return d
    return depth(payload) > 10


class TestShrink(unittest.TestCase):
    def test_shrinks_dict_to_single_key(self):
        payload = {"title": None, "a": 1, "b": [1, 2, 3],
                   "c": {"d": "x" * 100}}
        out = shrink(payload, _crashes_if_title_null)
        self.assertEqual(out, {"title": None})

    def test_shrinks_giant_string(self):
        payload = {"title": "x" * 65536, "other": "keep-me-out"}
        out = shrink(payload,
                     lambda p: isinstance(p, dict)
                     and isinstance(p.get("title"), str)
                     and len(p["title"]) > 100)
        # halving 65536 bottoms out at 128: the smallest power-of-two
        # split that still crashes -- 64 chars would not.
        self.assertEqual(out, {"title": "x" * 128})
        self.assertLess(_size(out), _size(payload))

    def test_shrinks_deep_nesting(self):
        node = {"leaf": 1}
        for _ in range(20):
            node = {"nest": node}
        payload = {"title": "ok", "deep": node}
        out = shrink(payload, _crashes_if_deep)
        # minimal repro keeps nesting just past the depth-10 crash boundary
        self.assertLess(_size(out), _size(payload))
        self.assertTrue(_crashes_if_deep(out))
        # one nesting level less must NOT crash (true minimality)
        shallower = {"deep": out["deep"]["nest"]}
        self.assertFalse(_crashes_if_deep(shallower))

    def test_shrink_is_deterministic(self):
        payload = {"title": None, "tags": ["a", "b", "c"], "n": 2 ** 40}
        a = shrink(payload, _crashes_if_title_null)
        b = shrink(payload, _crashes_if_title_null)
        self.assertEqual(a, b)

    def test_shrink_never_grows(self):
        payload = {"title": None, "x": list(range(50))}
        out = shrink(payload, _crashes_if_title_null)
        self.assertLessEqual(_size(out), _size(payload))

    def test_minimal_payload_still_crashes(self):
        payload = {"title": None, "extra": {"deep": [1, 2, {"z": 9}]}}
        out = shrink(payload, _crashes_if_title_null)
        self.assertTrue(_crashes_if_title_null(out))

    def test_predicate_exceptions_are_not_crashes(self):
        def flaky(p):
            if not isinstance(p, dict) or "title" not in p:
                return False
            if p.get("boom"):
                raise RuntimeError("predicate blew up")
            return p["title"] is None
        payload = {"title": None, "boom": True}
        out = shrink(payload, flaky)
        # dropping "boom" keeps the crash and avoids the predicate error
        self.assertEqual(out, {"title": None})

    def test_terminates_on_huge_inputs(self):
        payload = {"big": "y" * 100000, "title": None}
        out = shrink(payload, _crashes_if_title_null)
        self.assertEqual(out, {"title": None})


if __name__ == "__main__":
    unittest.main()
