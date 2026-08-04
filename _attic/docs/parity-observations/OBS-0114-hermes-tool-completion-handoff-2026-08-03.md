# OBS-0114 — Hermes post-completion tool-call handoff (clarify)

Date: 2026-08-03

Reference source commit: `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`

Terminal: direct PTY, 120×40

Probe: `scripts/probe_hermes_tool_completion_handoff.py`

## Scope

Fresh synthetic Hermes TUI, deterministic loopback provider. One ordinary
prompt. Provider returns complete stream: fragmented `clarify` tool call,
`finish_reason: "tool_calls"`, terminal `[DONE]`. Probe observes bounded
post-completion handoff, then stops process.

OBS-0110 withheld `[DONE]` deliberately. This observation completes stream,
observes handoff. `clarify` interactive-only: execution confined to TUI
question surface. No network, credential, OAuth, browser, filesystem, or
installer side effect.

## Observed boundary

- `[DONE]` sent. Clarify question surface rendered: question marker + choice
  marker visible (`clarification`, `synthetic choice one`). Tool name
  visible. `Processing 1 tool call` marker absent.
- Ready marker visible in window.
- Request counts: 3 chat requests total, 1 initial + 2 subsequent.
  One follow-up carries tool response: roles `system, user, assistant, tool`,
  assistant message `tool_calls_present: true`. Tool result sent back to
  model.
- Third request: `auxiliary-nonstream`, `system, user` — same purpose-unknown
  auxiliary request seen in OBS-0108/0109.
- Clean Ctrl+C exit. Terminal restored.
- 8 loopback HTTP requests, all `127.0.0.1` owned by probe. No external
  traffic.

## Safe boundary

Transport + interactive-UI evidence only. Hades must not reproduce any
Hermes defect or turn handoff into execution behavior. Approval policy,
execution semantics, retries, failure behavior: unknown.

## Note: fixture loop termination

First streaming request answered with tool-call stream. Follow-up streaming
requests (tool result in history) answered plainly (`Synthetic completion.`)
so agent loop terminates. Without this, fixture loops forever — clarify
re-invoked each turn.

## Evidence

- `tests/fixtures/parity/OBS-0114-hermes-tool-completion-handoff.json`
- `.hades/runtime/hermes-tool-completion-handoff-probe.json`
