# 011 — Tool execution

Status: active
Owner: project owner

## Purpose

Hades already parses tool-call deltas (HAD-115), advertises the observed
31-tool Hermes inventory (HAD-117), and sends exactly one bounded follow-up
carrying a Hades-owned synthetic tool-result marker (HAD-119). It never
executes a tool. Hermes, by contrast, executes tools after the tool-call
handoff. This spec promotes tool execution from the backlog (previously
"deltas are rendered, not executed") to an active capability whose contract is
captured before any implementation: observe the pinned reference executing
tools against a synthetic sandbox, record new OBS fixtures, implement a
hades-tools executor in Rust, and parity-verify the multi-hop loop.

## Requirements

- R1. Observation first: no tool-execution code lands before the reference
  observation exists. The pinned Hermes reference (commit
  `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`) is observed executing tools
  against a synthetic sandbox: the terminal tool writing to temp dirs, the
  file tools (read/write/list), and the interactive `clarify` question
  surface.
- R2. Synthetic sandbox: the observation confines every tool side effect to
  probe-owned temp directories and a throwaway synthetic home. No credentials,
  network, OAuth, browser, installer, or real filesystem side effect is
  exercised or claimed.
- R3. Sanitized fixtures: each observation produces a sanitized OBS fixture
  (`tests/fixtures/parity/OBS-01xx-*.json`), a provenance-bearing observation
  document (`_attic/docs/parity-observations/`), and a repeatable direct-PTY
  probe. Raw tool arguments, results, and transcripts are never persisted —
  only normalized shape (kinds, lengths, digests, structural markers).
- R4. hades-tools executor: the executor is implemented in Rust at a
  deterministic seam (the typed tool-call boundary already used by the
  provider transport and the app reducer). It dispatches a parsed
  `ToolCallRecord` to a sandboxed tool implementation and returns a typed
  tool result in the observed message shape.
- R5. Multi-hop loop: after a tool result, the follow-up request carries the
  `tool` role message in the observed shape; if the follow-up response itself
  contains tool calls, the loop continues — bounded by the observed
  termination semantics, never an unbounded loop.
- R6. Safety: any Hermes bug, unsafe behavior, or failure case is a defect to
  fix in Hades, never a compatibility requirement. Approval policy, retries,
  and failure behavior remain unknown until observed; Hades must not invent
  them.

## Acceptance criteria

- [ ] A1. Given the promotion, when the ledger is read, then spec 011 exists
      with a capture plan (plan.md), a checklist (tasks.md), and a registered
      control-plane task — and spec 005's out-of-scope line no longer
      misstates tool execution as permanently out of scope.
- [x] A2. Given the pinned reference, when the sandbox probe runs, then the
      observation records the reference executing terminal/file/clarify tools
      against the synthetic sandbox, with provenance, sanitized OBS fixtures,
      and documented unknowns (approval, retries, failure, termination).
      Evidence: `scripts/probe_hermes_tool_execution.py`;
      `tests/fixtures/parity/OBS-0117…0120-hermes-tool-execution-*.json`;
      `_attic/docs/parity-observations/OBS-0117…0120-hermes-tool-execution-*-2026-08-05.md`.
- [ ] A3. Given a parsed tool-call record, when the executor runs, then the
      tool executes against the synthetic sandbox and the typed result feeds
      the follow-up request in the observed message shape.
- [ ] A4. Given a follow-up that itself requests tools, when the loop runs,
      then it continues exactly as observed and terminates per the observed
      semantics; the multi-hop parity replay passes.
- [ ] A5. Given the gate, when `just verify` runs, then it passes with no
      skips and the parity matrix, README, and control plane are updated.

## Out of scope

- Remote/gateway providers, OAuth, and credential storage (spec 005/006).
- Tool execution beyond the synthetic sandbox: browser automation, installer
  side effects, network tools, and real user-environment writes.
- Approval UI/policy, retry, failure, and termination semantics not present
  in the observed slice (explicit unknowns, never guessed).

## Open questions

- The multi-hop loop is observed (OBS-0120): two hops then plain-completion
  termination, each follow-up a streaming `system, user, assistant, tool`
  request with the tool message referencing the assistant's tool-call id.
  Tool-result rendering per hop and any termination bound beyond the
  observed plain-completion stop remain unobserved.
- The purpose of the auxiliary non-stream `system, user` request seen in
  OBS-0108/0109/0114/0116/0117/0118/0119/0120 — remains unknown.

## Links

Code: `crates/hades-provider/src/lib.rs` (tool-call parsing, inventory),
`crates/hades-app/src/lib.rs` (follow-up loop) · Tests: `scripts/replay_tool_call_deltas.py`,
`tests/fixtures/parity/OBS-0110-hermes-tool-call-handoff.json`,
`OBS-0114-hermes-tool-completion-handoff.json`,
`OBS-0116-hermes-clarify-question-surface.json` · ADRs: ADR-0002, ADR-0005
