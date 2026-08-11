# ADR 0007: Tool calling design for Dira

Status: accepted (2026-08-11)

## Context

Dira should act, not just talk: search the resource library and raise
appointment requests. Tool use is also where LLM systems grow their most
dangerous attack surface, so the design must be safe by construction.

## Decision

The gateway owns a bounded tool loop (at most three rounds): the provider
may return tool calls, the gateway executes them and feeds results back,
and every executed call is recorded in the ai_requests audit row.

Security properties, deliberate:

- **Allow listed per call site.** A tool exists for the model only if the
  calling use case handed it over. There is no global registry the model
  can enumerate and no free form execution of any kind.
- **Authorization is baked into the handler.** Tools are constructed with
  the conversation's organization and patient already bound; the model
  chooses a tool and arguments, never a target. search_resources can only
  search the caller's tenant; request_appointment can only file for the
  conversation's own patient.
- **Tools are humble.** request_appointment notifies the care team through
  a real workflow (requested to acknowledged); it never books anything.
  Unknown tool names are refused and reported back to the model; tool
  failures degrade into an honest reply instead of crashing it.
- **Crisis precedence.** A crisis disclosure never detours into tool use;
  the direct crisis reply wins. This is enforced by the provider scenario
  logic and regression tested in the dira eval suite.

Streaming uses the same path: tool rounds resolve first, then the final
text streams to the client as SSE events (tool, delta, message), and the
audit entry is written when the stream ends.

## Alternatives considered

- A framework (LangChain tools, LangGraph): solves orchestration but hides
  exactly the loop, bounds, and audit points this project exists to show.
- Letting tools mutate freely (book appointments outright): rejected;
  human in the loop is the platform's core safety rule.

## Consequences

- Real adapters must map their native tool calling into ToolCall and read
  tool role messages; the interface is provider neutral.
- The tool result content flows back through the model, so handlers must
  never place secrets or other patients' data into results. Handlers are
  tenant scoped to make that structural.
