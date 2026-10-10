"""No-network enforcement: core flows work with sockets stubbed out.

Nothing in fuzzer/runner/shrink/targets/cli/demo may touch the network.
We stub socket.socket and socket.create_connection to raise, then run the
full pipeline in-process. (The `serve` command is the only network surface;
it is smoke-tested manually, not in the suite.)
"""

import io
import os
import socket
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fuzzer import generate_corpus  # noqa: E402
from runner import run_corpus  # noqa: E402
from schemas import get_schema  # noqa: E402
from targets import (fragile_create_work_order,  # noqa: E402
                     robust_create_work_order)


def _raising_socket(*args, **kwargs):
    raise AssertionError("network socket used during hermetic test")


class TestNoNetwork(unittest.TestCase):
    def test_full_pipeline_with_sockets_stubbed(self):
        with mock.patch.object(socket, "socket", _raising_socket), \
             mock.patch.object(socket, "create_connection", _raising_socket):
            corpus = generate_corpus(get_schema("create_work_order"), 7)
            fragile = run_corpus(fragile_create_work_order, corpus,
                                 schema_name="create_work_order", seed=7)
            robust = run_corpus(robust_create_work_order, corpus,
                                schema_name="create_work_order", seed=7)
            self.assertGreater(fragile["unexpected_crashes"], 0)
            self.assertEqual(robust["unexpected_crashes"], 0)

    def test_demo_with_sockets_stubbed(self):
        with mock.patch.object(socket, "socket", _raising_socket), \
             mock.patch.object(socket, "create_connection", _raising_socket):
            import demo
            buf = io.StringIO()
            with redirect_stdout(buf):
                demo.main()
            self.assertIn("demo OK", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
