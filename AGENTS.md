# Hades Agent development contract

## Mission

Hades Agent is a Rust implementation of Hermes TUI. The product acceptance bar
is exact behavioral and visual parity with the reference, not a vaguely similar
terminal application. The repository is also designed to be developed by
bounded autonomous coding agents without turning uncertainty into invented
facts.

This file governs development agents. It is not product behavior and must never
be copied into user-facing prompts, runtime policy, or the TUI.

## Authority and autonomy

The project owner is the constitutional authority. An authorized agent may
autonomously research, plan, implement, test, review, and commit routine work
inside this repository. Routine autonomy is bounded by the control plane in
`.hades/` and the workflow in `.agents/`.

An agent must stop and report before it:

- reads, creates, rotates, or exports credentials or private runtime state;
- sends external messages, spends money, accepts legal terms, or publishes a
  release;
- performs destructive operations, irreversible migrations, or broad cleanup;
- weakens a test, security boundary, evidence requirement, or quality gate;
- changes licensing, ownership, repository visibility, or this authority model.

No agent may claim a feature is complete from source inspection alone. A green
test suite is necessary but is not sufficient for parity: the relevant Hermes
observation, trace, snapshot, or explicit unresolved-unknown record must also
be named in the task evidence.

## Source-of-truth planes

- Product requirements: `docs/PRODUCT_SPEC.md`.
- Current project truth: `CONTEXT.md`.
- Architecture decisions: `docs/decisions/ADR-*.md`.
- Reference observations and parity claims: `docs/parity/` and checked-in
  fixtures under `tests/fixtures/parity/`.
- Autonomous work frontier: `.hades/tasks.json`.
- Development policy and role contracts: `.agents/`.
- Generated run logs and leases: `.hades/runtime/` and `.hades/locks/`; these
  are local-only and must not become product source.

When two planes disagree, executable tests and captured reference evidence
outrank prose. Preserve the disagreement as an explicit task or decision;
never silently rewrite history.

## Autonomous delivery loop

1. Orient: read this contract, `CONTEXT.md`, the owning decision records, and
   the current task from `.hades/tasks.json`.
2. Select the smallest unblocked task with `just agent next` and claim it with
   `just agent claim <id> <agent-name>`.
3. For parity work, observe Hermes first and store provenance, environment,
   inputs, outputs, and confidence in the parity ledger.
4. Implement the smallest coherent change at a deterministic seam. Keep model
   or prompt judgment outside domain code; keep state transitions in Rust.
5. Add or update an executable oracle: unit test, replay trace, golden frame,
   lifecycle probe, or performance budget.
6. Run `just verify`. Never hide failures with skips, weakened assertions, or
   an unrecorded environment exception.
7. Have the verifier/reviewer inspect the diff and evidence. Complete the task
   only with a concise summary and paths to real evidence.
8. If progress is impossible, mark the task `blocked` with the exact missing
   authority, observation, or dependency. A blocked task is a valid terminal
   outcome; fake completion is not.

Every run has exactly one terminal outcome: `complete`, `blocked`, or
`cancelled`. Retries must be attributable and must not overwrite prior evidence.

## Engineering laws

- Prefer typed state transitions over stringly-typed prompt logic.
- Keep the product plane separate from the instruction plane.
- Keep modules small enough for an agent to reason about locally; split before a
  production module becomes difficult to review.
- New behavior requires a regression oracle at the narrowest useful seam.
- Every external or nondeterministic boundary needs a fake, replay seam, or
  explicit test adapter.
- Reference unknowns stay unknown until observed. Do not infer exact keymaps,
  timings, copy, colors, or error handling from convention.
- Frozen evidence: `docs/parity/observations/`, `tests/fixtures/parity/`, and
  the `scripts/probe_hermes_*.py` reference-observation instruments are
  captured provenance, not dead code. Do not delete, refactor, or "clean up"
  them; they are retired one-shot instruments kept for reproducibility.
  Replays awaiting migration live in `scripts/replay_*.py` and stay gate
  citizens until their Rust twin passes differential parity (HAD-147+).
- Reference observations define the intended compatibility contract, not a
  mandate to reproduce defects. Do not intentionally rebuild Hermes bugs,
  unsafe behavior, or failure cases in Hades; fix them and document any
  deliberate, evidence-backed deviation from the reference.
- Do not read `.env`, credentials, captured private data, or ignored runtime
  state as part of repository orientation.

## Required gate

The single complete local gate is:

```bash
just verify
```

It validates the control plane, formatting, compilation, Clippy with warnings
denied, tests, and whitespace. The command is intentionally boring; the agent
should spend its judgment on evidence and product behavior, not on inventing a
different definition of green.
