# WORKFLOWS

The workflow engine (ADR 0004) lives in `app/domain/workflows.py` plus the
`workflow_instances` and `workflow_transitions` tables. Every workflow
type declares its states and allowed transitions; an unlisted transition
raises instead of corrupting state. Transitions record actor, reason, and
timestamp, append only, and are inspectable in the ops console.

## Risk escalation

`pending_review -> resolved | failed`

Opened by the risk consumer when deterministic thresholds fire on an AI
risk signal (self harm and crisis always escalate; severity 2 and up
escalates). Resolved only by a therapist's accept, edit, or reject in the
review queue, which writes the `risk_reviews` decision row, an audit
entry, and a `HumanReviewCompleted` event. Failure paths (AI timeout,
malformed output, dead lettering) are tested.

## Referral

`submitted -> accepted | declined`

Opened when school staff submit a referral (consent confirmation
required). Accepting assigns the deciding therapist to the student (a real
consequence) and notifies linked guardians through
`GuardianNotificationRequired`. States are terminal; a second decision is
refused. School staff see exactly these state names in their UI.

## Claim

`submitted -> approved | denied`, `denied -> resubmitted`,
`resubmitted -> approved | denied`

Submission requires a passing eligibility check from the labeled fake
payer adapter and an assignment to the patient. Denials require a reason,
tracked on the claim and in the transition history; resubmission carries a
correction note. Approved is terminal.

## Guarantees shared by all workflows

- State lives in one place and changes only through validated transitions.
- History is append only and actor attributed ("system" for machine
  transitions).
- Every opening and every decision emits a domain event (docs/EVENTS.md).
- Pending counts are exported as Prometheus gauges.
