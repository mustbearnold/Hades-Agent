# 009 — Rust migration of development tooling

Status: active
Owner: project owner

## Purpose

ADR-0008: the entire ~31k-LOC Python development harness (reference probes,
replays, control plane, verify orchestration) migrates to Rust in phases into
`crates/hades-dev`, keeping `just verify` green and matching Python report
shapes. Each port lands as a Rust twin that must pass differential parity
before it can replace its Python original in the gate.

## Requirements

- R1. Migration order: foundation (screen emulator + PTY) → fixture
  validator → control plane → replays → reference probes → verify
  orchestration.
- R2. A Python replay may be retired from the gate only after its Rust twin
  passes the differential parity check (`scripts/check_replay_parity.py`,
  identical normalized reports) and the Rust binary becomes the gate replay.
- R3. Ports reproduce the Python semantics with the same report JSON shape;
  the parity checker normalizes only timing diagnostics (`pre_delay_ms`,
  `observed_transition_ms`, `response_elapsed_ms`, `response_write_ms`,
  `query_offset`, `da1_query_offset`) and byte diagnostics (`raw_delta`,
  `screen_tail`).
- R4. Post-animation waits use rendered-screen predicates
  (`wait_for_rendered`); startup-marker waits stay raw (contiguous first
  frame).
- R5. Frozen evidence (observations, fixtures, probe instruments) is never
  deleted or refactored; retired instruments stay in git history and
  `.hades/runtime/` keeps run logs.
- R6. The final phase replaces `scripts/verify.sh` orchestration with a Rust
  equivalent; `verify_fast.sh` stays fixture-only.

## Acceptance criteria

- [ ] A1. Given a replay script, when ported, then
      `python3 scripts/check_replay_parity.py <name> <name>` prints
      `RESULT: PASS (N cases identical)`.
- [ ] A2. Given the gate, when all replays are ported, then no
      `scripts/replay_*.py` remains a gate citizen.
- [ ] A3. Given the full migration, when `just verify` runs, then it passes
      with the Rust orchestration only.

## Out of scope

- Product parity (specs 001–007).

## Open questions

- The verify orchestration design (HAD-178) is not started; the retirement
  mechanics of `verify.sh` and the exact Rust replacement shape are open.

## Links

Code: `crates/hades-dev/` · Tests: `scripts/check_*_parity.py`,
`.hades/tasks.json` (HAD-123..HAD-178) · ADRs: ADR-0008
