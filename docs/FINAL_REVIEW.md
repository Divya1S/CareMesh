# FINAL REVIEW (P17)

The spec's closing gate: a Staff Engineer style review from six
perspectives (Staff SWE, AI Engineer, Security Engineer, SRE, Product
Engineer, Healthcare Platform Architect), hunting for shallow
implementations, fake AI, race conditions, missing idempotency and
authorization, weak observability, prompt injection exposure, untested
failure modes, and misleading docs. Run 2026-08-11 as three parallel
review passes over the whole repository. Per the spec, problems were
fixed and re validated, not just reported: after the fixes below, the
full gate (118 backend tests, 13 frontend tests, 23 eval cases) is
green.

## High severity findings, all fixed

1. **Crisis precedence over tools lived only in the fake provider.**
   The claim "crisis disclosures bypass tools" was implemented by the
   fake provider's scenario matching; a real provider had no such
   guarantee. Fixed structurally: `domain/risk.py` gained a
   deterministic crisis phrase list, and the application layer now
   offers Dira zero tools on any turn whose latest patient message
   contains crisis language, for every provider. The dira eval suite
   now offers the full tool set on every case and asserts zero tool
   use on crisis and injection cases.

2. **No deterministic backstop under the risk classifier.** A message
   that steered a real model into category none, severity 0 would have
   silently skipped clinician review. Fixed: the same crisis phrase
   floor now forces escalation regardless of the model's output, and
   the risk prompt explicitly frames the message as data, never
   instructions. The model can add escalations on top of the floor,
   never remove them.

3. **The SSE endpoint reported "saved" before the commit.** A client
   disconnect mid stream rolled back the patient's message and its
   outbox event after the UI said it was saved, which for this system
   means a crisis message could vanish unscanned. Fixed: the streaming
   route commits the message in its own transaction before the first
   event is sent.

4. **Both workers died permanently on the first transient error.** A
   Postgres restart or broker rebalance killed the process; nothing
   restarted it while the API kept accepting messages. Fixed: both
   worker loops catch, log, back off, and continue; the relay bounds
   each broker send with a timeout so it cannot hold row locks
   indefinitely; the containerized services declare a restart policy.

5. **The gateway's audit write could destroy what it audits.** The
   `finally` block's log insert could raise, replacing the real error
   and rolling back the patient's message. Fixed: audit writes log
   their own failure and never raise.

6. **Unbounded tool fan out.** The tool loop executed every requested
   call per round with no idempotency, so one message could create many
   appointment workflows. Fixed: one executed call per round (three
   rounds max), request_appointment is idempotent per conversation, a
   failed mutating tool aborts the reply instead of streaming over a
   poisoned transaction, tool failures are logged, and token usage is
   accumulated across all rounds instead of only the last call.

## Medium severity findings, fixed

- **Streaming provenance was asserted, not derived.** The live chat
  bubble hardcoded the SIMULATED badge, and an unknown provider
  defaulted to simulated=false. The stream now begins with a start
  event carrying provenance, the UI renders the badge from it, and
  unknown defaults to simulated=true (mislabeling real output as
  simulated is the safe direction).
- **An empty stream persisted as a successful reply.** A safety blocked
  real model stream would have shown a student a blank bubble audited
  as ok. The gateway now fails the reply when a stream produces no
  text, surfacing the existing "Dira is unavailable" path.
- **The login rate limit's composite key enforced neither documented
  dimension.** Now two independent buckets, per address and per
  account.
- **Client supplied X-Request-ID was stored unvalidated** into
  String(64) columns (a 65 character header caused a 500 that rolled
  back the message). Now validated and replaced with a generated id.
- **Redis had no socket timeouts and a non atomic INCR/EXPIRE.** Now
  bounded 2 second timeouts and a single pipeline with EXPIRE NX, so a
  dropped connection can never leave a counter without a TTL.
- **Ops reads of AI request transcripts were unaudited** even though
  they can contain verbatim conversation content. Reading a transcript
  detail is now an audited act like review and claim decisions.
- **The evals' simulated_only flag was computed but never enforced**,
  and tool behavior was only asserted on tool cases. Both gates are now
  enforced.
- **Documentation drift**: dira suite case count, the "23/23 gated"
  claim (3 retrieval cases are informational under the default lexical
  embeddings), the live check's audit wording, the e2e role count, a
  Quickstart block that could not be pasted as written, and a wrong
  loadtest path. All corrected.

## Accepted as known limitations (documented, not fixed)

These are recorded here and in SECURITY.md or THREAT_MODEL.md rather
than fixed, with reasons:

- **Evals run on the fake provider only.** They pin the prompt and the
  structural guards; a real model's judgment is not evaluated. A judged
  real model eval is the first thing a budget would buy
  (docs/EVALUATION.md states this).
- **Tool result injection is mitigated, not eval gated.** Retrieved
  library text re enters the prompt as tool results; the prompt frames
  tool output as reference material and ingestion is ops admin only,
  but an eval case would only prove the fake provider echoes text, so
  none was added.
- **No X-Forwarded-For handling** on the login limiter's address
  bucket: behind a reverse proxy all clients share one address bucket.
  Local dev has no proxy; DEPLOYMENT.md's change list covers it.
- **No explicit Redis fail open or fail closed policy**: a Redis outage
  now fails fast as a 500 on rate limited routes instead of hanging,
  but the availability versus protection decision for a real
  deployment is left recorded rather than made.
- **The ops DLQ viewer talks to the broker from the route handler**
  with the client library's default timeouts, and worker processes
  still expose no /metrics (OBSERVABILITY.md lists this).
- **Streaming token counts for the final round are estimated** because
  streamed chunks carry no usage metadata; tool rounds are accounted
  exactly and the estimate is commented at the source.

## Verdict

The exit criteria in the build spec hold: coherent architecture, real
end to end workflows, genuinely integrated AI with explicit boundaries
and provenance, real RAG, event driven recovery, enforced idempotency
and authorization, observability and gated evals, tested critical
workflows, implemented security controls, docs that describe reality,
and reproducible local dev. The honesty rules survived the review:
nothing simulated is presented as real, and the one place the
distinction was asserted rather than derived (the streaming badge) is
now data driven.
