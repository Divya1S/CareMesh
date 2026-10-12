"""Tool abstraction for the gateway's tool loop (ADR 0007).

Security posture: tools are allow listed per call site, constructed with
their authorization context baked in (actor and organization), and expose
only declared parameters. There is no free form execution surface; the
model can only pick from what the caller handed it, and its arguments are
checked against the declared schema before a handler runs.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.application.ai.types import ToolDef


@dataclass(frozen=True, slots=True)
class ToolResult:
    # What the model reads back.
    content: str
    # One human sentence for the UI ("Dira searched the resource library").
    summary: str
    # Structured extras for the caller (for example citations).
    payload: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Tool:
    definition: ToolDef
    run: Callable[[dict], Awaitable[ToolResult]]
    # True for tools that write (rows, events). A failed mutating tool has
    # likely poisoned the transaction, so the gateway aborts the reply
    # instead of degrading over a broken session.
    mutates: bool = False


_JSON_TYPES: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def validate_arguments(schema: dict, arguments: object) -> str | None:
    """Checks model supplied arguments against the small JSON schema subset
    tools declare here: an object with typed properties and required keys.
    Returns a short problem description, or None when the arguments pass.
    Model output is untrusted input; a handler never sees arguments that
    failed this check."""
    if not isinstance(arguments, dict):
        return "arguments must be a JSON object"
    properties: dict = schema.get("properties", {})
    for key in schema.get("required", []):
        if key not in arguments:
            return f"missing required argument {key!r}"
    for key, value in arguments.items():
        spec = properties.get(key)
        if spec is None:
            return f"unexpected argument {key!r}"
        declared = spec.get("type")
        expected = _JSON_TYPES.get(declared) if declared else None
        if expected is None:
            continue
        # bool is an int subclass in Python; a flag is not an integer.
        if declared in ("integer", "number") and isinstance(value, bool):
            return f"argument {key!r} must be of type {declared}"
        if not isinstance(value, expected):
            return f"argument {key!r} must be of type {declared}"
    return None
