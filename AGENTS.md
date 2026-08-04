# AGENTS.md — entry point

**Read `specs/constitution.md` first — it is the highest authority in this
repository. Then read `specs/conventions.md` (formatting and style law).**

This file is a thin entry point. It exists so tooling and humans have a
stable first stop; it deliberately contains no policy of its own. Policy
lives in the constitution, the capability specs, and the ADRs.

## Before any work

1. Read `specs/constitution.md` and `specs/conventions.md`.
2. Read `docs/decisions/ADR-*.md` relevant to the capability you touch.
3. Read the current task from `.hades/tasks.json` (control plane).
4. Follow the SDD loop defined in the constitution: spec → plan → tasks →
   implement → verify. No code without a spec.

## The delivery loop

1. Select the smallest unblocked task (`just agent next`) and claim it
   (`just agent claim <id> <agent-name>`).
2. For parity work, observe the reference first; store provenance,
   environment, inputs, outputs, and confidence in the parity ledger.
3. Implement at a deterministic seam; add an executable oracle (unit test,
   replay trace, golden frame, lifecycle probe, or performance budget).
4. Run the single complete local gate: `just verify`. Never hide failures
   with skips, weakened assertions, or an unrecorded environment exception.
5. Complete the task only with a concise summary and paths to real evidence.
   Terminal outcomes: `complete`, `blocked` (exact missing
   authority/observation/dependency), or `cancelled`.

## Authority boundary

The project owner is the constitutional authority. Stop and report before:
touching credentials or private runtime state; external side effects;
destructive operations or broad cleanup; weakening a test, security
boundary, evidence requirement, or quality gate; changing licensing,
ownership, repository visibility, or the authority model.
