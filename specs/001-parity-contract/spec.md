# 001 — Parity contract

Status: active
Owner: project owner (constitutional authority)

## Purpose

Hades Agent's product promise is exactness: the same user action in the same
supported environment must produce the same observable result as the Hermes
reference, within a documented normalization boundary. This spec defines what
"exact" means and the evidence chain that makes a parity claim verifiable.

## Requirements

- R1. A behavior may move from unknown to implemented only when all four links
  exist: (a) a provenance-bearing reference observation, (b) an explicit
  normalized contract or trace, (c) a Hades implementation with an executable
  oracle, (d) a verification record naming the exact artifacts used.
- R2. The reference is pinned: commit
  `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`; provenance and sanitized
  artifacts live in `_attic/docs/parity-observations/` (frozen evidence,
  owner-directed quarantine during the SDD migration).
- R3. Raw captured data is never persisted; only normalized shape is stored.
  Credentials are normalized out (e.g. `authorization_present: true` only).
- R4. If a reference behavior cannot be safely captured, the correct state is
  `blocked` or `unknown` — never an approximation presented as parity.
- R5. Reference unknowns stay unknown until observed; keymaps, timings, copy,
  colors, and error handling are never inferred from convention.
- R6. When two source-of-truth planes disagree, executable tests and captured
  reference evidence outrank prose; the disagreement is preserved as an
  explicit task or decision, never silently resolved.
- R7. Reference observations define the compatibility contract, not a mandate
  to reproduce defects; deliberate, evidence-backed deviations are documented
  in the deviation matrix. [inferred from AGENTS.md law]

## Acceptance criteria

- [ ] A1. Given a parity claim, when verified, then the four-link evidence
      chain (observation, contract, oracle, verification record) is named in
      the task evidence.
- [ ] A2. Given a gate run, when any reference probe fails, then the run is
      reported as failed — skips and weakened assertions are not permitted.
- [ ] A3. Given an observation capture, when stored, then no raw secret or
      credential value appears in the persisted artifact.

## Out of scope

- Product behavior itself (see specs 002–007).
- The reference's own bugs (deviation policy, R7).

## Roadmap

Behavior-led stages (from the former docs/ROADMAP.md, now merged here): a
stage is complete only when its evidence is recorded and its gates are
green; elapsed time or code volume is not completion.

- Stage 0 — Evidence substrate: reference build/capture environment,
  sanitized trace/frame formats, unknowns and normalization rules,
  self-validating control plane.
- Stage 1 — Lifecycle parity: terminal ownership/restoration, startup/exit,
  interrupt and resize, deterministic lifecycle probes.
- Stage 2 — Interaction parity: keymap/focus model, navigation and command
  routing, input editing and submission, errors/cancellation/retry.
- Stage 3 — Visual parity: frame geometry and responsive layout,
  typography/colors/borders/cursor, streaming and transient states,
  golden-frame differential reports.
- Stage 4 — Integration parity: persistence and configuration,
  model/provider/tool boundaries, recovery and background work, performance
  budgets.
- Stage 5 — Release readiness: supported environment matrix, reproducible
  packaging, upgrade/rollback, release evidence and owner approval.

## Open questions

- None recorded.

## Appendix — Trace and golden-frame format

Reference traces are sanitized, deterministic JSON documents describing
observable inputs and outputs; they never embed credentials, raw private
transcripts, or model payloads.

```json
{
  "schema_version": 1,
  "observation_id": "OBS-0001",
  "reference": {
    "product": "Hermes TUI",
    "version": "<exact version or unknown>",
    "terminal": {"columns": 120, "rows": 40}
  },
  "steps": [
    {
      "input": {"kind": "key", "value": "<sanitized key>"},
      "output": {"frame": "<fixture path>", "status": "<normalized observable status>"}
    }
  ]
}
```

Golden frames are UTF-8 text files with one normalized terminal row per
line. The capture contract must state whether trailing spaces, ANSI escapes,
cursor position, and timing are retained or normalized. A normalizer is part
of the oracle, not an undocumented cleanup step.

## Links

Code: `crates/hades-dev/src/bin/validate_fixture.rs` · Tests: `tests/fixtures/parity/` ·
ADRs: ADR-0002, ADR-0003
