"""Fictional Helios Home tool-call JSON Schemas (sample data only -- zero personal data).

``create_work_order`` is deliberately the same schema the
``structured-output-validator`` repo ships, so fuzzer output composes with it:
every fuzzed payload is a candidate ``arguments`` object for that validator.
``place_order`` adds integer bounds, nested objects, and a nullable field so
the corpus exercises more of the mutation catalog.

Stdlib only. No network.
"""

from __future__ import annotations

TOOL_SCHEMAS: dict[str, dict] = {
    "create_work_order": {
        "type": "object",
        "required": ["title", "priority"],
        "additionalProperties": False,
        "properties": {
            "title": {"type": "string", "minLength": 3, "maxLength": 120},
            "priority": {"type": "string",
                         "enum": ["low", "medium", "high", "urgent"]},
            "estimated_cost": {"type": "number", "minimum": 0, "maximum": 100000},
            "tags": {"type": "array", "items": {"type": "string"},
                     "maxItems": 8, "uniqueItems": True},
            "notify_customer": {"type": "boolean"},
        },
    },
    "place_order": {
        "type": "object",
        "required": ["customer", "items", "quantity"],
        "additionalProperties": False,
        "properties": {
            "customer": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string", "minLength": 1, "maxLength": 80},
                    "id": {"type": "string", "pattern": r"^C-\d{3}$"},
                },
            },
            "items": {
                "type": "array",
                "minItems": 1,
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "required": ["sku"],
                    "properties": {
                        "sku": {"type": "string", "minLength": 1},
                        "unit_price": {"type": "number", "minimum": 0},
                        "quantity": {"type": "integer", "minimum": 1,
                                     "maximum": 999},
                    },
                },
            },
            "quantity": {"type": "integer", "minimum": 1, "maximum": 999},
            "delivery_speed": {"type": "string",
                               "enum": ["standard", "expedited", "overnight"]},
            "notes": {"type": ["string", "null"], "maxLength": 500},
            "split_count": {"type": "integer", "minimum": 1, "maximum": 12},
        },
    },
}


def get_schema(name: str) -> dict:
    try:
        return TOOL_SCHEMAS[name]
    except KeyError:
        raise KeyError(
            f"unknown schema {name!r}; available: {sorted(TOOL_SCHEMAS)}"
        ) from None
