# ADR 0005: Dira replies synchronously in the request during S5

Status: accepted (default chosen during S5, 2026-08-10); updated
2026-10-12: the streaming endpoint is now the primary path, the patient
message commits before any model call on both paths, and the request's
database connection is released before the provider is called, so the
"does not belong inside a request transaction" concern below no longer
applies. The reply is still generated in the request, not by a consumer.

## Context

Dira's reply could be generated synchronously inside the POST message
request, or asynchronously by a consumer reacting to PatientMessageCreated.
The fake provider answers in about 10 ms, so both work today. A real
provider would take seconds, which does not belong inside a request
transaction.

## Decision

Generate the reply synchronously in `ConversationService.post_message` for
S5. The reply and its `AIResponseGenerated` outbox event commit together
with the patient's message. Gateway failures are swallowed after being
audited in `ai_requests`, so Dira being unavailable never blocks the
patient's message.

## Alternatives considered

- Consumer driven reply off `PatientMessageCreated`: the right shape once
  latency is real, but it needs client side live updates (polling or SSE)
  to show the reply, which S5 does not have yet.

## Consequences

- The chat UI shows the reply immediately with a plain refetch after send.
- When risk analysis lands in S6 and consumers do real work, reply
  generation moves behind the event flow and the UI gains live updates.
  This ADR is superseded at that point.
