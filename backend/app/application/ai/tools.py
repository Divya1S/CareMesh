"""Tool abstraction for the gateway's tool loop (ADR 0007).

Security posture: tools are allow listed per call site, constructed with
their authorization context baked in (actor and organization), and expose
only declared parameters. There is no free form execution surface; the
model can only pick from what the caller handed it.
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
