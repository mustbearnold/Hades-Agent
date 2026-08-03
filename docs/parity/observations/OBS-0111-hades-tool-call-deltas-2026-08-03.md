# OBS-0111 — Hades safe tool-call delta boundary

Date: 2026-08-03

Reference source commit: `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`

Terminal: direct PTY, 120×40

Replay: `scripts/replay_tool_call_deltas.py`

## Scope

A fresh Hades debug process was launched in an isolated synthetic
HOME/HERMES_HOME with `HADES_PROVIDER_BASE_URL` pointed at a probe-owned
loopback OpenAI-compatible server. One ordinary prompt was submitted. The
server returned a streaming response with assistant text, a fragmented
`clarify` tool call, and `finish_reason: "tool_calls"`, followed by `[DONE]`.

This is the Hades implementation side of the OBS-0110 transport boundary:
the provider transport now parses `delta.tool_calls` into typed events, the
core/app seam accumulates argument fragments per call index, and the completed
turn records the tool call (name, argument length, stable digest) without
executing, approving, or forwarding anything.

## Observed boundary

- One streaming chat request reached `/v1/chat/completions` with
  `authorization_present: false`, the expected body keys, and
  `tools_present: false` (Hades does not yet advertise a tool inventory).
- The response streamed five SSE chunks; the two tool-call deltas carried the
  call identifier, function name, and two argument fragments (lengths 45 and
  58; only digests are persisted).
- The joined arguments are valid JSON (`valid_json: true`, length 103).
- The assistant text rendered; the process returned to ready with no
  busy marker and no invented tool-processing overlay.
- No follow-up chat request and no tool-response request followed completion.
- Ctrl+C exited cleanly with the alternate screen and termios restored.

## Safe boundary

Hades never executes, approves, or forwards tool calls in this slice. The
recorded digest is a stable FNV-1a boundary marker, not a security
credential. Tool registration/advertising, approval policy, execution,
results, retries, malformed argument handling, and multiple calls per turn
remain unimplemented and are explicit unknowns, matching the OBS-0110
transport evidence.

## Evidence

- `tests/fixtures/parity/OBS-0111-hades-tool-call-deltas.json`
- `.hades/runtime/tool-call-deltas-replay.json`
