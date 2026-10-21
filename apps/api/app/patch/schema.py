"""TinyFish `output_schema` validator (no app imports, so models.py can use it).

The validator mirrors https://docs.tinyfish.ai/key-concepts/structured-output.md: the top level
must be an object, only an allowlist of keywords is accepted, type arrays are rejected
(use `nullable`), and the serialized schema must be <= 64 KB with depth <= 10.
"""

import json
from typing import Any

TINYFISH_SCHEMA_KEYWORDS = frozenset(
    {
        "anyOf",
        "enum",
        "format",
        "items",
        "maxItems",
        "maximum",
        "minItems",
        "minimum",
        "nullable",
        "properties",
        "propertyOrdering",
        "required",
        "type",
    }
)
TINYFISH_FORMATS = frozenset({"date", "date-time", "duration", "time"})
TINYFISH_TYPES = frozenset({"object", "array", "string", "number", "integer", "boolean"})
MAX_SCHEMA_BYTES = 65536
MAX_SCHEMA_DEPTH = 10


def tinyfish_schema_errors(schema: Any) -> list[str]:
    """Return every reason TinyFish would reject `schema`; an empty list means it is valid."""
    if not isinstance(schema, dict):
        return ["#: schema must be a JSON object"]
    errors: list[str] = []
    if "type" in schema and schema["type"] != "object":
        errors.append('#: top-level "type" must be "object"')
    if "anyOf" in schema:
        errors.append('#: top-level "anyOf" is not supported; put composition inside a field')
    try:
        size = len(json.dumps(schema))
    except (TypeError, ValueError):
        return [*errors, "#: schema is not JSON-serializable"]
    if size > MAX_SCHEMA_BYTES:
        errors.append(f"#: schema is {size} bytes; the limit is {MAX_SCHEMA_BYTES}")
    _walk(schema, "#", 1, False, errors)
    return errors


def _walk(node: Any, path: str, depth: int, in_any_of: bool, errors: list[str]) -> None:
    if isinstance(node, bool):
        errors.append(f"{path}: boolean schema nodes are not supported")
        return
    if not isinstance(node, dict):
        errors.append(f"{path}: schema node must be an object")
        return
    if depth > MAX_SCHEMA_DEPTH:
        errors.append(f"{path}: nesting depth exceeds {MAX_SCHEMA_DEPTH}")
        return

    for key in node:
        if key not in TINYFISH_SCHEMA_KEYWORDS:
            errors.append(f'{path}: keyword "{key}" is not supported')

    node_type = node.get("type")
    if isinstance(node_type, list):
        errors.append(f'{path}: type arrays are not supported; use "nullable": true')
        node_type = None
    elif node_type is not None and node_type not in TINYFISH_TYPES:
        errors.append(f'{path}: unknown type "{node_type}"')

    if "enum" in node:
        values = node["enum"]
        if node_type != "string":
            errors.append(f'{path}: "enum" requires "type": "string"')
        elif not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            errors.append(f'{path}: every "enum" value must be a string')
    if "format" in node:
        if node_type != "string":
            errors.append(f'{path}: "format" requires "type": "string"')
        elif node["format"] not in TINYFISH_FORMATS:
            errors.append(f'{path}: format "{node["format"]}" is not supported')
    for key in ("items", "minItems", "maxItems"):
        if key in node and node_type != "array":
            errors.append(f'{path}: "{key}" requires "type": "array"')
    for key in ("minimum", "maximum"):
        if key in node and node_type not in ("number", "integer"):
            errors.append(f'{path}: "{key}" requires "type": "number" or "integer"')

    properties = node.get("properties")
    if properties is not None:
        if not isinstance(properties, dict):
            errors.append(f'{path}: "properties" must be an object')
            properties = None
        else:
            for name, sub in properties.items():
                _walk(sub, f"{path}/properties/{name}", depth + 1, False, errors)

    if "required" in node:
        required = node["required"]
        if not isinstance(required, list) or not all(isinstance(r, str) for r in required):
            errors.append(f'{path}: "required" must be a list of field names')
        elif not in_any_of:
            missing = [r for r in required if r not in (properties or {})]
            if missing:
                errors.append(f'{path}: required fields not in "properties": {missing}')

    if "propertyOrdering" in node:
        ordering = node["propertyOrdering"]
        if properties is None:
            errors.append(f'{path}: "propertyOrdering" requires "properties"')
        elif not isinstance(ordering, list) or len(set(ordering)) != len(ordering):
            errors.append(f'{path}: "propertyOrdering" must be a list of unique names')
        else:
            unknown = [p for p in ordering if p not in properties]
            if unknown:
                errors.append(f'{path}: "propertyOrdering" names unknown fields: {unknown}')

    if "items" in node:
        _walk(node["items"], f"{path}/items", depth + 1, False, errors)
    if "anyOf" in node and path != "#":
        branches = node["anyOf"]
        if not isinstance(branches, list) or not branches:
            errors.append(f'{path}: "anyOf" must be a non-empty list')
        else:
            for i, branch in enumerate(branches):
                _walk(branch, f"{path}/anyOf/{i}", depth + 1, True, errors)
