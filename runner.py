"""Fuzz runner: feed a corpus into a target function, classify crashes.

A *crash* is any exception the target raises on a payload. Targets may declare
``expected_exceptions`` (e.g. a validating target's ``ValueError``) -- those
are counted as clean rejections, not crashes. Everything else is an
*unexpected crash* and lands in the report with its exception class, message,
the corpus mutation that produced it, and a shrinker-minimized repro payload.

``run_corpus(target, corpus)`` returns a JSON-serializable report with stable
bytes (sorted keys, no timestamps): the same (schema, seed, target) always
produces the identical report.

Stdlib only. No network.
"""

from __future__ import annotations

import copy
import hashlib
import json

from shrink import shrink


def _run_once(target, payload):
    """The exception the target raises on payload, or None when it is clean."""
    try:
        target(copy.deepcopy(payload))
    except Exception as exc:  # noqa: BLE001 - the runner must survive anything
        return exc
    return None


def _payload_sha(payload) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _payload_len(payload) -> int:
    return len(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, default=str))


def run_corpus(target, corpus: list[dict], schema_name: str = "",
               seed: int = 0, shrink_crashes: bool = True) -> dict:
    expected = getattr(target, "expected_exceptions", ())
    target_name = getattr(target, "__name__", str(target))

    crashes = []
    expected_rejections = 0
    for entry in corpus:
        exc = _run_once(target, entry["payload"])
        if exc is None:
            continue
        if expected and isinstance(exc, expected):
            expected_rejections += 1
            continue
        crashes.append({
            "index": entry["index"],
            "mutation": entry["mutation"],
            "path": entry["path"],
            "exc_class": type(exc).__name__,
            "message": str(exc),
            "original_sha256": _payload_sha(entry["payload"]),
            "original_size": _payload_len(entry["payload"]),
        })

    if shrink_crashes:
        for crash in crashes:
            entry = corpus[crash["index"]]
            want = crash["exc_class"]

            def still_crashes(p, _t=target, _want=want):
                r = _run_once(_t, p)
                return r is not None and type(r).__name__ == _want

            minimal = shrink(entry["payload"], still_crashes)
            crash["minimal_payload"] = minimal
            crash["minimal_sha256"] = _payload_sha(minimal)
            crash["minimal_size"] = _payload_len(minimal)

    crashes.sort(key=lambda c: (c["exc_class"], c["mutation"], c["index"]))
    signatures = sorted({c["exc_class"] for c in crashes})

    return {
        "schema": schema_name,
        "seed": seed,
        "target": target_name,
        "corpus_size": len(corpus),
        "unexpected_crashes": len(crashes),
        "expected_rejections": expected_rejections,
        "unique_signatures": signatures,
        "crashes": crashes,
    }


def report_json(report: dict) -> str:
    return json.dumps(report, sort_keys=True, indent=2) + "\n"
