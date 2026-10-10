"""Delta-debugging shrinker: minimize a crashing payload.

Given a payload that crashes a target and a ``still_crashes`` predicate that
replays the *same* crash (same exception class), ``shrink`` greedily applies
the first strictly-smaller candidate that still crashes, restarting the scan
until no candidate crashes. Candidates are generated in a fixed deterministic
order, so the minimal repro is stable across runs.

Candidate strategy per value type (all strictly reduce serialized size):
  dict: drop one key at a time (sorted order), then shrink nested values
  list: take the first half, then drop one element at a time, then shrink items
  str:  take the first half, then "", then the first character
  int/float: 0, 1, -1, then halve toward zero

The loop only accepts candidates that are strictly smaller, which guarantees
termination. A hard iteration cap is the backstop.

Stdlib only. No network.
"""

from __future__ import annotations

import json

MAX_SHRINK_STEPS = 20000


def _size(value) -> int:
    return len(json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, default=str))


def _candidates(value):
    """Yield strictly-smaller candidates in deterministic order."""
    if isinstance(value, dict):
        keys = sorted(value.keys())
        for k in keys:
            yield {kk: vv for kk, vv in value.items() if kk != k}
        for k in keys:
            for cv in _candidates(value[k]):
                d = dict(value)
                d[k] = cv
                yield d
    elif isinstance(value, list):
        n = len(value)
        if n > 1:
            yield value[: n // 2]
        for i in range(n):
            yield value[:i] + value[i + 1:]
        for i, item in enumerate(value):
            for ci in _candidates(item):
                yield value[:i] + [ci] + value[i + 1:]
    elif isinstance(value, str):
        n = len(value)
        if n > 1:
            yield value[: n // 2]
        if n >= 1:
            yield ""
        if n > 1:
            yield value[0]
    elif isinstance(value, bool) or value is None:
        return
    elif isinstance(value, (int, float)):
        for c in (0, 1, -1):
            if c != value:
                yield c
        if isinstance(value, int) and abs(value) > 1:
            yield value // 2
        elif isinstance(value, float) and abs(value) > 1:
            yield value / 2.0


def shrink(payload, still_crashes) -> object:
    """Return the smallest payload (by serialized size) that still crashes."""
    current = payload
    current_size = _size(current)
    steps = 0
    while steps < MAX_SHRINK_STEPS:
        improved = False
        for cand in _candidates(current):
            steps += 1
            if steps >= MAX_SHRINK_STEPS:
                break
            if _size(cand) >= current_size:
                continue
            try:
                crashes = bool(still_crashes(cand))
            except Exception:
                crashes = False
            if crashes:
                current = cand
                current_size = _size(current)
                improved = True
                break  # restart the scan from the new, smaller payload
        if not improved:
            break
    return current
