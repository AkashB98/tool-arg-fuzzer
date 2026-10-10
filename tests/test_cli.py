"""Tests for the CLI: exit codes 0/1/2 and command wiring."""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cli import (EXIT_CRASHES, EXIT_ERROR, EXIT_OK, build_parser,  # noqa: E402
                 main)


def _run_cli(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(argv)
    return code, buf.getvalue()


class TestCli(unittest.TestCase):
    def test_fuzz_exit_ok(self):
        code, out = _run_cli(["fuzz", "--schema", "create_work_order",
                              "--seed", "7"])
        self.assertEqual(code, EXIT_OK)
        self.assertIn("payloads=", out)
        self.assertIn("md5=", out)

    def test_fuzz_is_deterministic(self):
        _, a = _run_cli(["fuzz", "--schema", "create_work_order",
                         "--seed", "7"])
        _, b = _run_cli(["fuzz", "--schema", "create_work_order",
                         "--seed", "7"])
        self.assertEqual(a, b)

    def test_run_fragile_exit_1(self):
        code, out = _run_cli(["run", "--schema", "create_work_order",
                              "--target", "fragile_create_work_order",
                              "--seed", "7"])
        self.assertEqual(code, EXIT_CRASHES)
        self.assertIn("unexpected_crashes=", out)

    def test_run_robust_exit_0(self):
        code, out = _run_cli(["run", "--schema", "create_work_order",
                              "--target", "robust_create_work_order",
                              "--seed", "7"])
        self.assertEqual(code, EXIT_OK)
        self.assertIn("unexpected_crashes=0", out)

    def test_run_place_order_exit_1(self):
        code, _ = _run_cli(["run", "--schema", "place_order",
                            "--target", "fragile_place_order",
                            "--seed", "7"])
        self.assertEqual(code, EXIT_CRASHES)

    def test_unknown_schema_exit_2(self):
        code, _ = _run_cli(["run", "--schema", "nope",
                            "--target", "fragile_create_work_order"])
        self.assertEqual(code, EXIT_ERROR)

    def test_unknown_target_exit_2(self):
        code, _ = _run_cli(["run", "--schema", "create_work_order",
                            "--target", "nope"])
        self.assertEqual(code, EXIT_ERROR)

    def test_report_out_writes_json(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "report.json")
            code, _ = _run_cli(["run", "--schema", "create_work_order",
                                "--target", "fragile_create_work_order",
                                "--seed", "7", "--report-out", path])
            self.assertEqual(code, EXIT_CRASHES)
            with open(path, encoding="utf-8") as fh:
                report = json.load(fh)
            self.assertGreater(report["unexpected_crashes"], 0)

    def test_corpus_out_writes_jsonl(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "corpus.jsonl")
            code, _ = _run_cli(["fuzz", "--schema", "create_work_order",
                                "--seed", "7", "--corpus-out", path])
            self.assertEqual(code, EXIT_OK)
            with open(path, encoding="utf-8") as fh:
                lines = fh.readlines()
            self.assertGreater(len(lines), 40)
            first = json.loads(lines[0])
            # validator-ready: each line carries the arguments payload
            self.assertIn("payload", first)
            self.assertIn("title", first["payload"])

    def test_demo_command(self):
        code, out = _run_cli(["demo"])
        self.assertEqual(code, EXIT_OK)
        self.assertIn("demo OK", out)

    def test_parser_has_serve(self):
        parser = build_parser()
        args = parser.parse_args(["serve", "--port", "9999"])
        self.assertEqual(args.port, 9999)


if __name__ == "__main__":
    unittest.main()
