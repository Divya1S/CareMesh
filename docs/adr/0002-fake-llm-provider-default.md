# ADR 0002: Fake LLM provider as the dev default

Status: accepted (approved with Phase 0, 2026-08-10)

## Context

The LLM API budget is limited and local dev must be free. The project honesty
rules forbid presenting simulated AI as real. All LLM traffic goes through the
AI Gateway behind an `LLMProvider` abstraction.

## Decision

`LLM_PROVIDER=fake` is the default. The fake provider returns deterministic,
scenario driven fixture responses, honors the same schemas and tool calling
contract as real providers, supports injectable failure modes, and marks every
response `simulated: true`. That flag flows through logs, the API, and every UI
as a visible SIMULATED label. Real providers (anthropic, openai, gemini) are
enabled only by env var with keys in `.env`.

## Alternatives considered

- Real provider by default with a small budget: burns money on every test run
  and makes tests nondeterministic.
- Recorded cassettes of real responses: still needs paid calls to record, and
  drifts as prompts change.

## Consequences

- Tests, evals, and demos run free and reproducibly.
- Prompts are not validated against real models until a real provider is
  switched on. Mitigation: the eval harness runs the same golden sets against a
  real provider later, as an optional, budget flagged step.
