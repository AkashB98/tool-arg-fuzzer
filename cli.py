#!/usr/bin/env python3
"""CLI for the tool-arg fuzzer.

Commands:
  fuzz    generate the deterministic corpus for a schema (prints summary;
          --corpus-out writes the JSONL corpus for the validator pipeline)
  run     fuzz a target: exit 0 = no unexpected crashes, 1 = crashes found,
          2 = error. --report-out writes the JSON crash report.
  demo    one-command end-to-end (asserts internally)
  serve   tiny JSON API: POST /fuzz {schema, seed, target}, GET /schemas

Exit codes are CI-friendly: run exits 0/1/2 so a pipeline can gate on it.
Stdlib only. No network except `serve` (binds localhost only).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

from fuzzer import corpus_md5, generate_corpus
from runner import report_json, run_corpus
from schemas import TOOL_SCHEMAS, get_schema
from targets import (fragile_create_work_order, fragile_place_order,
                     robust_create_work_order)

EXIT_OK = 0        # no unexpected crashes
EXIT_CRASHES = 1   # crashes found
EXIT_ERROR = 2     # usage / lookup error

TARGETS = {
    "fragile_create_work_order": fragile_create_work_order,
    "fragile_place_order": fragile_place_order,
    "robust_create_work_order": robust_create_work_order,
}


def _target(name: str):
    try:
        return TARGETS[name]
    except KeyError:
        raise KeyError(
            f"unknown target {name!r}; available: {sorted(TARGETS)}") from None


def cmd_fuzz(args: argparse.Namespace) -> int:
    try:
        schema = get_schema(args.schema)
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    corpus = generate_corpus(schema, args.seed)
    md5 = corpus_md5(corpus)
    print(f"schema={args.schema} seed={args.seed} "
          f"payloads={len(corpus)} md5={md5}")
    if args.corpus_out:
        with open(args.corpus_out, "w", encoding="utf-8") as fh:
            for entry in corpus:
                # Each line's "payload" is a validator-ready arguments object.
                fh.write(json.dumps(entry, sort_keys=True) + "\n")
        print(f"corpus written to {args.corpus_out}")
    return EXIT_OK


def cmd_run(args: argparse.Namespace) -> int:
    try:
        schema = get_schema(args.schema)
        target = _target(args.target)
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    corpus = generate_corpus(schema, args.seed)
    report = run_corpus(target, corpus, schema_name=args.schema,
                        seed=args.seed, shrink_crashes=not args.no_shrink)
    print(f"target={report['target']} payloads={report['corpus_size']} "
          f"unexpected_crashes={report['unexpected_crashes']} "
          f"expected_rejections={report['expected_rejections']} "
          f"signatures={report['unique_signatures']}")
    for crash in report["crashes"][:10]:
        print(f"  [{crash['exc_class']}] {crash['mutation']} "
              f"({crash['path']}) -> {crash['minimal_size']}B minimal repro")
    if args.report_out:
        with open(args.report_out, "w", encoding="utf-8") as fh:
            fh.write(report_json(report))
        print(f"report written to {args.report_out}")
    return EXIT_OK if report["unexpected_crashes"] == 0 else EXIT_CRASHES


class _Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload: object) -> None:
        body = json.dumps(payload, sort_keys=True, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/schemas":
            self._send(200, {"schemas": sorted(TOOL_SCHEMAS),
                             "targets": sorted(TARGETS)})
        elif self.path in ("/", "/health"):
            self._send(200, {"ok": True, "service": "tool-arg-fuzzer"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/fuzz":
            self._send(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            schema = get_schema(payload["schema"])
            target = _target(payload.get("target",
                                         "fragile_create_work_order"))
            seed = int(payload.get("seed", 7))
            corpus = generate_corpus(schema, seed)
            report = run_corpus(target, corpus, schema_name=payload["schema"],
                                seed=seed)
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            self._send(400, {"error": str(exc)})
            return
        self._send(200, report)

    def log_message(self, *args: object) -> None:  # quiet
        pass


def cmd_serve(args: argparse.Namespace) -> int:
    server = HTTPServer(("127.0.0.1", args.port), _Handler)
    print(f"serving on http://127.0.0.1:{args.port} (localhost only)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return EXIT_OK


def cmd_demo(_args: argparse.Namespace) -> int:
    import demo
    demo.main()
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cli.py",
        description="Seeded fuzzer for agent tool-call arguments.")
    sub = p.add_subparsers(dest="command", required=True)

    f = sub.add_parser("fuzz", help="generate the deterministic corpus")
    f.add_argument("--schema", required=True,
                   help=f"schema name (one of: {', '.join(sorted(TOOL_SCHEMAS))})")
    f.add_argument("--seed", type=int, default=7)
    f.add_argument("--corpus-out", default=None,
                   help="write corpus JSONL (validator-ready payloads)")
    f.set_defaults(func=cmd_fuzz)

    r = sub.add_parser("run", help="fuzz a target (exit 0 clean, 1 crashes, 2 error)")
    r.add_argument("--schema", required=True,
                   help=f"schema name (one of: {', '.join(sorted(TOOL_SCHEMAS))})")
    r.add_argument("--target", required=True,
                   help=f"target name (one of: {', '.join(sorted(TARGETS))})")
    r.add_argument("--seed", type=int, default=7)
    r.add_argument("--no-shrink", action="store_true",
                   help="skip minimal-repro shrinking")
    r.add_argument("--report-out", default=None,
                   help="write the JSON crash report")
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("serve", help="tiny JSON API (localhost only)")
    s.add_argument("--port", type=int, default=8766)
    s.set_defaults(func=cmd_serve)

    d = sub.add_parser("demo", help="one-command end-to-end demo")
    d.set_defaults(func=cmd_demo)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

__all__ = ["build_parser", "main", "TARGETS",
           "EXIT_OK", "EXIT_CRASHES", "EXIT_ERROR"]
