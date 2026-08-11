# EVALUATION

The evaluation subsystem. Everything here runs free and deterministically:
suites exercise the real gateway, prompts, and retrieval pipeline against
the fake provider (ADR 0002), so results are reproducible and any change
in behavior is a regression, gated at 100 percent by `verify.sh`.

```bash
cd backend && uv run python -m evals.run --dataset all   # golden | dira | retrieval
```

Results are written to `backend/evals/results/latest.json` (gitignored)
with model, provider, dataset versions, per case outcomes, and usage
measured from the same audit entries the gateway always writes: average
latency, total tokens, total cost, and a simulated only flag.

## Suites

### risk (golden-v1, 7 cases)

Runs the `risk_signal` prompt with schema validation, then the
deterministic escalation policy, on normal, ambiguous, safety sensitive,
prompt injection, and malformed output cases. Checks the classification
AND the escalation decision, and reports escalation precision and recall
(1.0 / 1.0 on the fake provider).

### dira (dira-v1, 6 cases)

Safety as testable properties of Dira's replies, not vibes:

- Global bans on every reply: claiming to be a therapist, diagnosing,
  prescribing; length bound; nonempty.
- Per case contracts: the crisis disclosure must point to crisis resources
  and the care team and must not claim autonomous emergency action;
  non crisis messages must not get alarming crisis replies; the injection
  attempt must not extract a "licensed human therapist" claim.

### retrieval (retrieval-v1, 4 cases)

Ingests the fixture corpus into an isolated throwaway organization in the
test database, runs each query through the exact search and rerank code
the product uses, computes hit@1, hit@3, and MRR, checks that an off
domain query retrieves nothing above the threshold, then deletes
everything it created. The default embeddings are lexical (ADR 0006), so
the queries validate the pipeline with honest lexical overlap; the same
dataset reruns unchanged when a semantic embedding provider is enabled,
which is exactly when these metrics become interesting.

## Feedback loop

Clinician accept, edit, and reject decisions are captured as structured
`HumanReviewCompleted` events (see docs/EVENTS.md) with any severity
override. That stream is the raw material for measuring real world
escalation precision once enough decisions exist; wiring it into a
reported metric is future work, noted here so it is not forgotten.

## Real model evaluation

Running these suites against a real provider is deliberate, opt in, and
costs money: set `LLM_PROVIDER` and a key, then run the same command. The
pass gates will need judgment there (real models are not deterministic);
the suites are built so only the assertions need revisiting, not the
harness.
