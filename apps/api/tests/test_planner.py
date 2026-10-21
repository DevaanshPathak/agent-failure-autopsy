import pytest

from app.patch.planner import tinyfish_schema_errors

DOCS_EXAMPLE = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "price": {"type": "number", "minimum": 0},
        "published_at": {"type": "string", "format": "date-time", "nullable": True},
        "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
    },
    "required": ["title", "price"],
    "propertyOrdering": ["title", "price", "published_at", "tags"],
}


def test_docs_example_schema_is_valid():
    assert tinyfish_schema_errors(DOCS_EXAMPLE) == []


def test_list_schema_with_any_of_field_is_valid():
    schema = {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}, "url": {"type": "string"}},
                    "required": ["name", "url"],
                },
            },
            "price": {"anyOf": [{"type": "number"}, {"type": "string", "enum": ["free"]}]},
        },
        "required": ["results"],
    }
    assert tinyfish_schema_errors(schema) == []


@pytest.mark.parametrize(
    ("schema", "needle"),
    [
        ({"type": "object", "additionalProperties": False}, "additionalProperties"),
        ({"type": "object", "properties": {"a": {"oneOf": []}}}, "oneOf"),
        ({"type": "object", "properties": {"a": {"const": "x"}}}, "const"),
        ({"type": "object", "properties": {"a": {"type": ["string", "null"]}}}, "type arrays"),
        ({"type": "object", "properties": {"a": {"type": "number", "enum": ["1"]}}}, "enum"),
        ({"type": "object", "properties": {"a": {"type": "string", "format": "uri"}}}, "format"),
        ({"type": "object", "properties": {"a": {"type": "string", "minItems": 1}}}, "minItems"),
        ({"type": "object", "required": ["missing"], "properties": {}}, "required fields"),
        ({"type": "array", "items": {"type": "string"}}, "top-level"),
        ({"anyOf": [{"type": "object"}]}, "top-level"),
        ({"type": "object", "properties": {"a": True}}, "boolean schema"),
    ],
)
def test_rejected_schemas_name_the_problem(schema, needle):
    errors = tinyfish_schema_errors(schema)
    assert errors, schema
    assert any(needle in e for e in errors), errors


def test_depth_limit():
    node: dict = {"type": "string"}
    for _ in range(11):
        node = {"type": "object", "properties": {"x": node}}
    assert any("depth" in e for e in tinyfish_schema_errors(node))
