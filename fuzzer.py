"""Seeded adversarial argument generator from JSON Schemas.

``generate_corpus(schema, seed)`` returns a deterministic list of payloads:
one valid baseline plus a fixed catalog of adversarial mutations applied to
each property, then global mutations. The same (schema, seed) always yields
the byte-identical corpus -- replay is exact, so a crashing payload can be
re-generated on any machine and fed to the shrinker.

Mutation catalog (applied per property, in sorted property order):
  missing_required / null_required / wrong_type swaps
  strings: empty, giant (64k), whitespace-only, unicode/invisible chars,
           control chars, minLength-1 / maxLength+1 boundaries
  integers: minimum-1, maximum+1, huge (2**63), float-for-int, bool-for-int
  numbers: below-minimum, above-maximum, numeric-string, "NaN", huge float
  booleans: string-for-bool, int-for-bool
  enums: outside value, case-flipped, empty string
  arrays: empty, over-maxItems, huge (5000), wrong item types, deep nesting
  objects: deep nesting (20), extra property
Global mutations (fixed order): extra properties, empty object,
top-level non-object payloads, deep nesting at top level, unicode bomb.

Stdlib only. No network.
"""

from __future__ import annotations

import copy
import hashlib
import json
import random

GIANT_STRING_LEN = 65536
HUGE_ARRAY_LEN = 5000
DEEP_NESTING_DEPTH = 20
TOP_NESTING_DEPTH = 25

_UNICODE_TRICKS = [
    "café \u200b\u200c ☕",          # zero-width chars (invisible)
    "order\u202eDESREVER",          # right-to-left override (invisible)
    "\U0001F3E0\U0001F4A1" * 4,     # emoji
    "ﬁsh ﬂow",                     # ligatures
]

_WRONG_TYPE_VALUES: dict[str, list] = {
    "string": [123, 4.5, True, None, [], {}],
    "integer": ["abc", 4.5, True, None, [], {}],
    "number": ["abc", True, None, [], {}],
    "boolean": ["yes", 1, 0, None, [], {}],
    "array": ["not-an-array", 5, True, None, {}],
    "object": ["not-an-object", 5, True, None, []],
    "null": ["not-null", 0, ""],
}


def _primary_type(sub: dict) -> str:
    """First non-null type in the schema's ``type`` (handles ["string","null"])."""
    t = sub.get("type", "string")
    if isinstance(t, list):
        for x in t:
            if x != "null":
                return x
        return "null"
    return t


def _allows_null(sub: dict) -> bool:
    t = sub.get("type")
    return t == "null" or (isinstance(t, list) and "null" in t)


def _baseline(sub: dict, rng: random.Random, depth: int = 0) -> object:
    """A plausible valid value for the subschema (the corpus control case).

    Uses the seeded RNG for in-bounds variation so different seeds explore
    different valid neighborhoods; the same seed always replays identically.
    """
    t = _primary_type(sub)
    if "enum" in sub and sub["enum"]:
        return rng.choice(sorted(str(e) for e in sub["enum"]))
    if t == "string":
        lo = sub.get("minLength", 1)
        hi = sub.get("maxLength", max(lo, 12))
        n = rng.randint(lo, min(hi, max(lo, 24)))
        alphabet = "abcXYZ019"
        return "".join(rng.choice(alphabet) for _ in range(max(n, 1)))
    if t == "integer":
        lo = int(sub.get("minimum", 1))
        hi = int(sub.get("maximum", lo + 50))
        lo, hi = (lo, hi) if hi >= lo else (lo, lo)
        return rng.randint(lo, hi)
    if t == "number":
        lo = float(sub.get("minimum", 0.0))
        hi = float(sub.get("maximum", lo + 50.0))
        lo, hi = (lo, hi) if hi >= lo else (lo, lo)
        return round(rng.uniform(lo, hi), 2)
    if t == "boolean":
        return rng.choice([True, False])
    if t == "null":
        return None
    if t == "array":
        items = sub.get("items", {"type": "string"})
        n = max(int(sub.get("minItems", 1)), 1)
        return [_baseline(items, rng, depth + 1) for _ in range(min(n, 3))]
    if t == "object":
        props = sub.get("properties", {})
        out = {}
        for name in sorted(props):
            out[name] = _baseline(props[name], rng, depth + 1)
        return out
    return "a"


def _baseline_payload(schema: dict, rng: random.Random) -> dict:
    payload = _baseline(schema, rng)
    if not isinstance(payload, dict):
        payload = {}
    # make sure required keys exist even if not declared in properties
    for name in schema.get("required", []):
        if name not in payload:
            sub = schema.get("properties", {}).get(name, {"type": "string"})
            payload[name] = _baseline(sub, rng)
    return payload


def _deep() -> dict:
    node: dict = {"leaf": 1}
    for _ in range(DEEP_NESTING_DEPTH):
        node = {"nest": node}
    return node


def _top_deep() -> dict:
    node: dict = {"leaf": 1}
    for _ in range(TOP_NESTING_DEPTH):
        node = {"nest": node}
    return node


def _string_mutations(name: str, sub: dict, base: dict):
    p = f"$.{name}"
    val = base[name]
    yield "empty_string", p, ""
    yield "giant_string", p, "x" * GIANT_STRING_LEN
    yield "whitespace_only", p, "   \t  "
    yield "unicode_invisible", p, _UNICODE_TRICKS[0]
    yield "unicode_rtl_override", p, _UNICODE_TRICKS[1]
    yield "control_chars", p, "ab\x00\x01\n\tcd"
    if isinstance(sub.get("minLength"), int) and sub["minLength"] > 0:
        yield "below_min_length", p, "a" * (sub["minLength"] - 1)
    if isinstance(sub.get("maxLength"), int):
        yield "above_max_length", p, "a" * (sub["maxLength"] + 1)
    if isinstance(sub.get("pattern"), str):
        yield "pattern_violation", p, "!!no-match!!"


def _integer_mutations(name: str, sub: dict, base: dict):
    p = f"$.{name}"
    if isinstance(sub.get("minimum"), (int, float)):
        yield "below_minimum", p, int(sub["minimum"]) - 1
    if isinstance(sub.get("maximum"), (int, float)):
        yield "above_maximum", p, int(sub["maximum"]) + 1
    yield "huge_integer", p, 2 ** 63
    yield "float_for_integer", p, 4.5
    yield "bool_for_integer", p, True
    yield "nan_string_for_integer", p, "NaN"


def _number_mutations(name: str, sub: dict, base: dict):
    p = f"$.{name}"
    if isinstance(sub.get("minimum"), (int, float)):
        yield "below_minimum", p, float(sub["minimum"]) - 0.5
    if isinstance(sub.get("maximum"), (int, float)):
        yield "above_maximum", p, float(sub["maximum"]) + 0.5
    yield "numeric_string_for_number", p, "42.5"
    yield "nan_string_for_number", p, "NaN"
    yield "huge_float", p, 1e308


def _boolean_mutations(name: str, sub: dict, base: dict):
    p = f"$.{name}"
    yield "string_for_boolean", p, "yes"
    yield "int_for_boolean", p, 1
    yield "null_for_boolean", p, None


def _enum_mutations(name: str, sub: dict, base: dict):
    p = f"$.{name}"
    vals = [str(e) for e in sub["enum"]]
    yield "enum_outside_value", p, "__NOT_A_VALUE__"
    yield "enum_case_flipped", p, vals[0].upper() if vals[0] == vals[0].lower() else vals[0].lower()
    yield "enum_empty_string", p, ""
    yield "enum_null", p, None


def _array_mutations(name: str, sub: dict, base: dict, rng: random.Random):
    p = f"$.{name}"
    items = sub.get("items", {"type": "string"})
    item_type = _primary_type(items)
    wrong = _WRONG_TYPE_VALUES.get(item_type, ["??"])[0]
    yield "empty_array", p, []
    if isinstance(sub.get("maxItems"), int):
        yield "above_max_items", p, [
            _baseline(items, rng) for _ in range(sub["maxItems"] + 3)]
    yield "huge_array", p, [0] * HUGE_ARRAY_LEN
    yield "wrong_item_types", p, [wrong, wrong]
    nested: list = []
    for _ in range(DEEP_NESTING_DEPTH):
        nested = [nested]
    yield "deep_nesting_array", p, nested
    if isinstance(sub.get("minItems"), int) and sub["minItems"] > 0:
        yield "below_min_items", p, []


def _object_mutations(name: str, sub: dict, base: dict):
    p = f"$.{name}"
    yield "deep_nesting_object", p, _deep()
    extra = copy.deepcopy(base[name]) if isinstance(base.get(name), dict) else {}
    extra["__fuzz_extra"] = {"nested": [1, 2, 3]}
    yield "extra_nested_property", p, extra


def _mutate_property(name: str, sub: dict, base: dict, required: set,
                     rng: random.Random):
    """Yield (mutation_label, json_path, new_value) for one property."""
    t = _primary_type(sub)
    if name in required:
        missing = {k: v for k, v in base.items() if k != name}
        yield "missing_required", f"$.{name}", ("__DELETE__", missing)
        if not _allows_null(sub):
            yield "null_required", f"$.{name}", None
    if "enum" in sub and sub["enum"]:
        yield from _enum_mutations(name, sub, base)
    elif t == "string":
        yield from _string_mutations(name, sub, base)
    elif t == "integer":
        yield from _integer_mutations(name, sub, base)
    elif t == "number":
        yield from _number_mutations(name, sub, base)
    elif t == "boolean":
        yield from _boolean_mutations(name, sub, base)
    elif t == "array":
        yield from _array_mutations(name, sub, base, rng)
    elif t == "object":
        yield from _object_mutations(name, sub, base)
    # wrong-type swaps for every property, after the targeted mutations
    for wrong in _WRONG_TYPE_VALUES.get(t, []):
        if wrong is None and _allows_null(sub):
            continue
        label = f"type_swap_{t}_to_{type(wrong).__name__}"
        yield label, f"$.{name}", wrong


def _global_mutations(base: dict, schema: dict):
    yield "extra_property_string", "$.__fuzz_extra", "__extra__"
    yield "extra_property_object", "$.__fuzz_extra", {"a": [1, {"b": None}]}
    # Deep nesting hidden inside an (unvalidated) extra property: reaches the
    # target's naive recursive walk instead of failing on a missing key first.
    yield "deep_nesting_extra_property", "$.__fuzz_extra", _deep()
    yield "empty_object", "$", {}
    yield "top_level_list", "$", [1, 2, 3]
    yield "top_level_string", "$", "not-an-object"
    yield "top_level_number", "$", 42
    yield "top_level_null", "$", None
    yield "deep_nesting_top", "$", _top_deep()
    # unicode bomb in the first string property of the baseline
    props = schema.get("properties", {})
    str_props = [n for n in sorted(props)
                 if _primary_type(props[n]) == "string"]
    if str_props:
        bombed = copy.deepcopy(base)
        bombed[str_props[0]] = "\U0001F4A5" * 2000
        yield "unicode_bomb", f"$.{str_props[0]}", ("__REPLACE__", bombed)


def generate_corpus(schema: dict, seed: int) -> list[dict]:
    """Generate the deterministic adversarial corpus for a JSON Schema.

    Returns a list of {"index", "mutation", "path", "payload"} dicts.
    The baseline (index 0, mutation "valid_baseline") is the control case.
    """
    rng = random.Random(seed)
    base = _baseline_payload(schema, rng)
    required = set(schema.get("required", []))
    props = schema.get("properties", {})

    corpus = [{
        "index": 0,
        "mutation": "valid_baseline",
        "path": "$",
        "payload": copy.deepcopy(base),
    }]

    def _add(label: str, path: str, new_value):
        # Whole-payload replacement markers carry the finished payload.
        if (isinstance(new_value, tuple) and len(new_value) == 2
                and new_value[0] in ("__DELETE__", "__REPLACE__")):
            payload = new_value[1]
        elif path == "$":
            payload = new_value
        else:
            # All property paths are flat top-level keys: "$.key".
            payload = copy.deepcopy(base)
            payload[path[2:]] = new_value
        corpus.append({
            "index": len(corpus),
            "mutation": label,
            "path": path,
            "payload": payload,
        })

    for name in sorted(props):
        sub = props[name]
        for label, path, new_value in _mutate_property(
                name, sub, base, required, rng):
            _add(label, path, new_value)

    for label, path, new_value in _global_mutations(base, schema):
        _add(label, path, new_value)

    return corpus


def corpus_md5(corpus: list[dict]) -> str:
    """Stable fingerprint of a corpus (sorted keys, compact separators)."""
    blob = json.dumps(corpus, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")
    return hashlib.md5(blob).hexdigest()
