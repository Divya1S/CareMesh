"""Tool argument validation: model output is untrusted input."""

from app.application.ai.tools import validate_arguments

SCHEMA = {
    "type": "object",
    "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
    "required": ["query"],
}


def test_valid_arguments_pass():
    assert validate_arguments(SCHEMA, {"query": "sleep"}) is None
    assert validate_arguments(SCHEMA, {"query": "sleep", "limit": 3}) is None


def test_missing_required_argument_is_reported():
    assert validate_arguments(SCHEMA, {}) == "missing required argument 'query'"


def test_wrong_types_and_unexpected_keys_are_rejected():
    assert validate_arguments(SCHEMA, {"query": 5}) == "argument 'query' must be of type string"
    assert validate_arguments(SCHEMA, {"query": "x", "limit": "3"}) == (
        "argument 'limit' must be of type integer"
    )
    assert validate_arguments(SCHEMA, {"query": "x", "limit": True}) == (
        "argument 'limit' must be of type integer"
    )
    assert validate_arguments(SCHEMA, {"query": "x", "extra": 1}) == "unexpected argument 'extra'"
    assert validate_arguments(SCHEMA, ["query"]) == "arguments must be a JSON object"
