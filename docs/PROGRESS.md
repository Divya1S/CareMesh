# PROGRESS

> Session memory for CareMesh AI. A fresh session must be able to resume from
> this file alone. Read `CLAUDE.md` first, then this file, before doing anything.

## Current phase

**Phase 0, the repository audit and architecture proposal, is COMPLETE and AWAITING HUMAN APPROVAL.**
Phase 1 (roadmap phase **S1, Foundation**) must not start until the human
explicitly approves `docs/PHASE_0_PROPOSAL.md`.

## Done

- 2026-08-10: `git init` on branch `main`, remote `origin` set to
  https://github.com/Divya1S/CareMesh.git, baseline `.gitignore` added.
- 2026-08-10: Build spec moved from `caremesh-build-spec.md` to `docs/BUILD_SPEC.md`.
- 2026-08-10: Repository audit performed. The repo was empty except `CLAUDE.md`
  and the spec. This was verified, not assumed.
- 2026-08-10: `docs/PHASE_0_PROPOSAL.md` written with all 12 sections, including:
  - Broker decision: **Redpanda**, compatible with the Kafka API and light on
    the laptop, with a comparison table and rationale (proposal section 5).
  - AI Gateway with the **fake provider as the dev default**
    (`LLM_PROVIDER=fake`), real providers switched on by env var only. This is
    the one place the project could ever cost money (proposal section 6).
  - **Vertical slice roadmap S1 to S7** (proposal section 11): student, Dira,
    risk signal, clinician workspace, and ops console working end to end before
    the school, guardian, and payer surfaces.
- 2026-08-10: The human recreated the GitHub repo. History was rebuilt and
  pushed fresh to match the writing rules below.

## In flight

- Nothing. Stopped at the Phase 0 gate by design.

## Known issues

- None. No code exists yet. The repo is docs only and not broken.

## Next steps, blocked on approval

1. The human reviews `docs/PHASE_0_PROPOSAL.md` and approves it or requests changes.
2. On approval: record the approval in `CLAUDE.md` under Current state and
   here, write ADRs 0001 to 0004 (Redpanda, fake provider default, outbox
   pattern, workflow engine in the repo), then begin **S1, Foundation**: the
   compose stack with Postgres, Redis, and Redpanda, the backend clean
   architecture skeleton, Alembic migrations for identity, tenancy, and the
   conversation core, auth plus RBAC, and `scripts/verify.sh`.
3. S1 exit gate: `docker compose up -d` healthy, `./scripts/verify.sh` green,
   and authorized CRUD demonstrable through the API.

## Standing constraints from the human (2026-08-10)

- **Zero budget:** everything must run free and locally. Flag it explicitly
  before any external or paid service is ever needed. Real LLM API calls are
  the only anticipated exception and stay off unless switched on by env var.
- The machine may struggle with heavy services, so Redpanda instead of Kafka,
  compose profiles, and the observability stack off by default.
- **Writing rules:** commits must never carry Claude attribution of any kind,
  so Claude never appears as a contributor on GitHub. All writing uses simple
  language with no em dashes and no dashes as punctuation.
