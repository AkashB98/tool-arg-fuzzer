"""Tests for the golden eval harness itself."""

import hashlib
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_HERE = os.path.join(os.path.dirname(__file__), "..", "evals")


class TestEvals(unittest.TestCase):
    def test_eval_report_exists_and_passes(self):
        import subprocess
        proc = subprocess.run(
            [sys.executable, os.path.join(_HERE, "run_evals.py")],
            capture_output=True, text=True, cwd=os.path.dirname(_HERE))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("5/5 golden cases passed", proc.stdout)

    def test_eval_report_md5_stable(self):
        import subprocess
        md5s = []
        for _ in range(2):
            subprocess.run(
                [sys.executable, os.path.join(_HERE, "run_evals.py")],
                capture_output=True, cwd=os.path.dirname(_HERE), check=True)
            with open(os.path.join(_HERE, "eval_report.json"), "rb") as fh:
                md5s.append(hashlib.md5(fh.read()).hexdigest())
        self.assertEqual(md5s[0], md5s[1])


if __name__ == "__main__":
    unittest.main()
