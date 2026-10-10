"""Demo targets for the fuzzer: one fragile, one validated.

``fragile_create_work_order`` / ``fragile_place_order`` are straight-line
tool implementations that assume perfect input -- the kind of code an agent
team writes on day one. The fuzzer finds their crash paths.

``robust_create_work_order`` validates first with a hand-rolled JSON Schema
subset check and raises ``ArgumentError`` (a ``ValueError``) on bad input.
The runner counts those as clean rejections: the fuzzer proves the validated
target degrades gracefully -- every adversarial payload is either accepted or
rejected with a clear error, never a traceback.

All data is the fictional Helios Home domain. Stdlib only. No network.
"""

from __future__ import annotations

import re

from schemas import get_schema

MAX_TOOL_DEPTH = 10


class ArgumentError(ValueError):
    """Clean rejection of invalid tool arguments (expected, not a crash)."""


# ---------------------------------------------------------------------------
# fragile targets
# ---------------------------------------------------------------------------

def _walk_deep(value, depth: int = 0):
    """Naive recursive walk, like code that assumed 'a few levels'.

    Raises RecursionError past a small budget -- deep fuzz input kills it.
    """
    if depth > MAX_TOOL_DEPTH:
        raise RecursionError("maximum nesting depth exceeded in tool")
    if isinstance(value, dict):
        for item in value.values():
            _walk_deep(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _walk_deep(item, depth + 1)


def fragile_create_work_order(args: dict) -> dict:
    title = args["title"]                                   # KeyError
    slug = title.strip().lower().replace(" ", "-")          # AttributeError
    slug.encode("ascii")                                    # UnicodeEncodeError
    budget = int(args["estimated_cost"])                    # ValueError/TypeError
    per_unit = budget / args.get("split_count", 1)          # ZeroDivisionError
    first_tag = args["tags"][0].upper()                     # IndexError/...
    _walk_deep(args)                                        # RecursionError
    return {"ok": True, "slug": slug, "first_tag": first_tag,
            "per_unit": per_unit}


def fragile_place_order(args: dict) -> dict:
    customer = args["customer"]                             # KeyError
    name = customer["name"].strip()                         # TypeError/...
    name.encode("ascii")                                    # UnicodeEncodeError
    items = args["items"]
    sku_prefix = items[0]["sku"][:3]                        # IndexError/TypeError
    total = sum(i["unit_price"] * i["quantity"] for i in items)  # TypeError
    qty = int(args["quantity"])                             # ValueError/TypeError
    per_item = total / args.get("split_count", 1)           # ZeroDivisionError
    _walk_deep(args)                                        # RecursionError
    return {"ok": True, "customer": name, "sku_prefix": sku_prefix,
            "total": total, "per_item": per_item, "qty": qty}


# ---------------------------------------------------------------------------
# robust (validated) target
# ---------------------------------------------------------------------------

def _check(sub: dict, value, path: str) -> None:
    """Hand-rolled JSON Schema subset validation; raises ArgumentError."""
    t = sub.get("type", "string")
    types = [t] if isinstance(t, str) else list(t)
    ok = False
    for one in types:
        if one == "null" and value is None:
            ok = True
        elif one == "string" and isinstance(value, str):
            ok = True
        elif one == "integer" and isinstance(value, int) \
                and not isinstance(value, bool):
            ok = True
        elif one == "number" and isinstance(value, (int, float)) \
                and not isinstance(value, bool):
            ok = True
        elif one == "boolean" and isinstance(value, bool):
            ok = True
        elif one == "array" and isinstance(value, list):
            ok = True
        elif one == "object" and isinstance(value, dict):
            ok = True
    if not ok:
        raise ArgumentError(f"{path}: expected {t}, got {type(value).__name__}")

    if "enum" in sub and value not in sub["enum"]:
        raise ArgumentError(f"{path}: {value!r} not in enum {sub['enum']}")
    if isinstance(value, str):
        if "minLength" in sub and len(value) < sub["minLength"]:
            raise ArgumentError(f"{path}: shorter than minLength")
        if "maxLength" in sub and len(value) > sub["maxLength"]:
            raise ArgumentError(f"{path}: longer than maxLength")
        if "pattern" in sub and not re.search(sub["pattern"], value):
            raise ArgumentError(f"{path}: does not match pattern")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in sub and value < sub["minimum"]:
            raise ArgumentError(f"{path}: below minimum")
        if "maximum" in sub and value > sub["maximum"]:
            raise ArgumentError(f"{path}: above maximum")
    if isinstance(value, list):
        if "minItems" in sub and len(value) < sub["minItems"]:
            raise ArgumentError(f"{path}: fewer than minItems")
        if "maxItems" in sub and len(value) > sub["maxItems"]:
            raise ArgumentError(f"{path}: more than maxItems")
        items = sub.get("items")
        if items:
            for i, item in enumerate(value):
                _check(items, item, f"{path}[{i}]")
    if isinstance(value, dict):
        for name in sub.get("required", []):
            if name not in value:
                raise ArgumentError(f"{path}.{name}: missing required field")
        props = sub.get("properties", {})
        for name, item in value.items():
            if name in props:
                _check(props[name], item, f"{path}.{name}")
            elif sub.get("additionalProperties") is False:
                raise ArgumentError(f"{path}.{name}: unknown property")


def robust_create_work_order(args: dict) -> dict:
    _check(get_schema("create_work_order"), args, "$")
    title = args["title"]
    slug = title.strip().lower().replace(" ", "-")
    # .get() default only covers a MISSING key; an explicitly empty list
    # still needs the fallback (caught by the fuzzer's empty_array case).
    first_tag = (args.get("tags") or ["-"])[0]
    return {"ok": True, "slug": slug, "first_tag": first_tag}


robust_create_work_order.expected_exceptions = (ArgumentError,)
