# 011 — Tool execution capture plan

Design document for promoting tool execution from backlog to implemented
capability. The chain is observation → fixtures → implementation →
parity verification, in that order (constitution: no code without a spec; a
behavior moves from unknown to implemented only with the four-link parity
chain).

## Stage 1 — Observe the reference executing tools in a synthetic sandbox

Goal: capture how the pinned Hermes reference executes tools end to end when
the loopback provider asks it to call tools whose side effects are confined to
probe-owned temp directories.

Probe family: one new direct-PTY probe
(`scripts/probe_hermes_tool_execution.py`) modeled on
`probe_hermes_tool_call_handoff.py` / `probe_hermes_tool_completion_handoff.py`
and `probe_hermes_clarify_question_surface.py` — fresh synthetic Hermes TUI,
deterministic loopback OpenAI-compatible provider, 120×40 PTY, bounded
observation windows, SIGTERM cleanup, loopback-only HTTP.

Scenarios (each its own bounded run):

- S1 terminal tool: provider tool-call stream asks Hermes to run a terminal
  command whose only side effect is writing a file into a probe-owned temp
  dir (e.g. `mkdir -p <tmp> && echo synthetic > <tmp>/out.txt`). Observe the
  executed command bytes, the follow-up request's `tool` message shape, and
  the next assistant turn.
- S2 file tools: provider tool-call stream invokes a file read/write/list
  against the probe-owned temp dir. Observe result content shape and the
  follow-up loop.
- S3 clarify: reuse the observed interactive question surface (OBS-0116)
  boundary — arrow navigation, Enter selection, 158-byte JSON tool result
  (`question`, `choices_offered`, `user_response`).
- S4 multi-hop: provider answers the first tool result with a second tool
  call, then a plain completion, so the loop is observed across two hops and
  terminates. Record request count and termination condition.

Boundaries: record exact request counts, per-request roles
(`system, user, assistant, tool`), tool-call names/arguments (digests only),
result shape (normalized), and loop termination. No credentials, no external
network, no real filesystem outside the sandbox, no installer/browser side
effects. Preserve unknowns (approval UI, retries, failure paths, timing).

## Stage 2 — New OBS fixtures

For each scenario: a sanitized fixture
(`tests/fixtures/parity/OBS-01xx-hermes-tool-execution-*.json`) following the
fixture policy in spec 001 (provenance, normalization rules, no raw payloads),
an observation document in `_attic/docs/parity-observations/`, and the probe
registered in `justfile` + `scripts/verify.sh` so it becomes a gate citizen.

## Stage 3 — Implement the hades-tools executor in Rust

New crate `crates/hades-tools/` at the deterministic typed seam already used
by the provider transport and app reducer:

- `ToolCallRecord` (typed name + bounded argument fragments) in, typed tool
  result out.
- A sandboxed execution boundary: every tool runs against an explicit
  `Sandbox` (probe/temp-dir root), never the real user environment.
- Implemented tools, bounded to the observed slice: `terminal` (write into
  sandbox dirs only), file read/write/list, and `clarify` rendered as the
  observed question surface.
- The app reducer feeds the result back through the follow-up request
  (existing one-hop path extended to the observed multi-hop loop with the
  observed termination).
- Unit tests at the typed seam plus a direct-PTY replay proving the loop.

## Stage 4 — Parity verification

- Fresh 120×40 direct-PTY replay of each scenario against the Hades binary,
  same loopback script as the reference probe.
- Differential check (normalized reports) against the reference observations;
  the multi-hop request sequence and tool-result shape must match.
- Update the parity matrix, README, and control-plane task evidence.
- Complete gate: `just verify` green, no skips.
