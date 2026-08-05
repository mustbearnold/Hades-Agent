# OBS-0117 — Hermes terminal tool execution against a synthetic sandbox

Date: 2026-08-05

Reference source commit: `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`

Terminal: direct PTY, 120×40

Probe: `scripts/probe_hermes_tool_execution.py` (scenario `s1-terminal`)

## Scope

Fresh synthetic Hermes TUI, deterministic loopback provider. One ordinary
prompt. The provider returns a complete streaming `terminal` tool-call stream
(`finish_reason: "tool_calls"`, terminal `[DONE]`) whose only side effect is a
probe-owned sandbox write:

    mkdir -p <sandbox>/out && echo synthetic > <sandbox>/out/out.txt

The probe records the executed command's structural markers, waits for the
follow-up request carrying the real tool-result message, answers it with a
plain completion, observes the bounded post-completion window, and exits
cleanly.

## Observed boundary

- The command executed without an approval prompt: `out.txt` exists in the
  probe-owned sandbox with exactly `synthetic\n` (10 bytes,
  `18c4f85a…`). The command matches no dangerous-command pattern, so the
  CLI approval layer auto-approved it.
- The follow-up streaming request carries the tool result in the observed
  message shape: roles `system, user, assistant, tool`, assistant has
  `tool_calls_present: true`, tool message is a string referencing the
  synthetic call id (`tool_call_id_marker: synthetic-call-id`).
- The real terminal tool-result content is a 45-byte JSON string with
  top-level keys `error, exit_code, output`; the output field is empty
  (the command's stdout was redirected to the sandbox file). Only the
  normalized shape is recorded; the content is never persisted.
- The result digest `708054e2…` was identical across three fresh runs with
  different sandbox paths — the result is path-independent for this
  command.
- Request counts: 3 chat requests (1 initial stream, 1 tool-result
  follow-up stream, 1 purpose-unknown auxiliary non-stream `system, user`
  request — the same auxiliary seen in OBS-0108/0109/0114/0116/0119).
  13 loopback HTTP requests, all `127.0.0.1` owned by the probe.
- The tool name and assistant marker were visible in the rendered frame; a
  processing marker (`Processing`) was visible in the canonical run but
  absent in an earlier run — timing-dependent, recorded not asserted.
- Clean Ctrl+C exit. Terminal restored.

## Safe boundary

Transport + sandbox side-effect evidence only. Hades must not reproduce any
Hermes defect or turn the observed execution into approval, retry, or
forwarding behavior. Approval UI, retries, failure paths, timing, and the
`error` field's value remain unknown.

## Evidence

- `tests/fixtures/parity/OBS-0117-hermes-tool-execution-terminal.json`
- `.hades/runtime/hermes-tool-execution-s1-terminal-probe.json`
- `scripts/probe_hermes_tool_execution.py`
