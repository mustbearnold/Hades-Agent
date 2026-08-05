# OBS-0119 — Hermes clarify tool execution (interactive surface)

Date: 2026-08-05

Reference source commit: `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`

Terminal: direct PTY, 120×40

Probe: `scripts/probe_hermes_tool_execution.py` (scenario `s3-clarify`)

## Scope

Fresh synthetic Hermes TUI, deterministic loopback provider. One ordinary
prompt. The provider returns a complete streaming `clarify` tool-call stream
(`finish_reason: "tool_calls"`, terminal `[DONE]`). Once the question surface
renders, the probe sends bounded non-submitting inputs (ArrowDown, ArrowUp,
then one Enter on the first visible choice) — the OBS-0116 boundary — waits
for the follow-up request carrying the real tool-result message, answers it
with a plain completion, and exits cleanly.

`clarify` is interactive-only: its execution is confined to the TUI question
surface, so this involves no network, credential, OAuth, browser, filesystem,
or installer side effect (the probe-owned sandbox stayed empty).

## Observed boundary

- The question surface rendered with the question marker and both choice
  markers; ArrowDown/ArrowUp kept the surface alive without submitting;
  Enter on the first choice produced the follow-up answer and the tool
  result.
- The real clarify tool-result content is the same 158-byte JSON string
  observed in OBS-0116 with top-level keys `choices_offered, question,
  user_response`; it contains both choice texts and the selected choice.
  The digest `7336fd6d…` is **identical to OBS-0116** — cross-observation
  determinism confirmed (same question, same choices, same selection).
  Only the normalized shape is recorded; the content is never persisted.
- The follow-up streaming request carries the tool result: roles `system,
  user, assistant, tool`, assistant has `tool_calls_present: true`, tool
  message references the synthetic call id.
- Request counts: 3 chat requests (1 initial stream, 1 tool-result
  follow-up stream, 1 purpose-unknown auxiliary non-stream `system, user`
  request), 13 loopback HTTP requests, all `127.0.0.1` owned by the probe.
- The clarify argument digest `45123b50…` matches OBS-0116's joined
  arguments digest exactly.
- Clean Ctrl+C exit. Terminal restored.

## Safe boundary

Interactive-UI evidence only. Hades must not reproduce any Hermes defect or
turn the observed question surface into execution, approval, or forwarding
behavior. Approval policy, execution semantics, retries, failure behavior,
and cursor-row cell-level markers remain unknown.

## Evidence

- `tests/fixtures/parity/OBS-0119-hermes-tool-execution-clarify.json`
- `.hades/runtime/hermes-tool-execution-s3-clarify-probe.json`
- `scripts/probe_hermes_tool_execution.py`
