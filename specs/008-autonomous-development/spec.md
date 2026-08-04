# 008 — Autonomous development

Status: active
Owner: project owner (constitutional authority)

## Purpose

The repository is designed to be developed by bounded autonomous AI agents
with a human prompter. This spec defines the control plane: the task ledger,
claim/complete protocol, authority boundaries, and the evidence discipline
that makes agent progress verifiable.

## Requirements

- R1. The control plane lives in `.hades/` (tasks.json, protocol schemas,
  runtime logs, locks) and the agent contracts in `docs/runbooks/`;
  generated run logs and leases are
  local-only and never become product source.
- R2. Every run has exactly one terminal outcome: `complete`, `blocked`, or
  `cancelled`; retries are attributable and never overwrite prior evidence.
- R3. An agent must stop and report before: touching credentials or private
  runtime state; sending external messages; destructive operations or broad
  cleanup; weakening a test/security/evidence/quality gate; changing
  licensing, ownership, visibility, or the authority model.
- R4. A green test suite is necessary but not sufficient for parity: the
  relevant observation, trace, snapshot, or unresolved-unknown record must be
  named in task evidence.
- R5. The delivery loop: orient (contract, context, ADRs, current task) →
  claim the smallest unblocked task → observe reference first → implement at
  a deterministic seam → add an executable oracle → run `just verify` →
  review → complete with evidence paths.
- R6. The frontier is encoded in `.hades/tasks.json`; `just agent next`
  returns the highest-priority ready task, and promotion happens on
  mutating commands.

## Acceptance criteria

- [ ] A1. Given an agent session, when it completes a task, then the task is
      marked complete with a summary and real evidence paths.
- [ ] A2. Given an impossible task, when progress stalls, then the task is
      marked blocked with the exact missing authority/observation/dependency
      — never faked complete.
- [ ] A3. Given the ledger, when queried, then `just agent next` returns an
      unblocked ready task or a clear "none" reason.

## Out of scope

- Product behavior (specs 001–007).
- The Rust migration of the dev harness (spec 009).

## Open questions

- None recorded beyond the control-plane behavior documented in
  `.hades/tasks.json` and the parity matrix (specs/001-parity-contract/matrix.md).

## Links

Code: `crates/hades-dev/src/bin/control_plane.rs` · Tests: `.hades/tasks.json` ·
ADRs: ADR-0003, ADR-0008
