# OBS-0115 — Hades bounded tool-result follow-up

Date: 2026-08-03

Reference source commit: `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`

Terminal: direct PTY, 120×40

Replay: `scripts/replay_tool_call_deltas.py`

## Scope

Fresh Hades debug process, isolated synthetic HOME/HERMES_HOME, probe-owned
loopback provider. One ordinary prompt. Provider returns a fragmented
`clarify` tool-call stream with `finish_reason: "tool_calls"` and `[DONE]`.
Hades now sends the bounded tool-result follow-up observed in OBS-0114:
assistant tool-call message + `tool` role result message, then renders the
follow-up answer.

## Observed boundary

- Initial request advertises the OBS-0112 31-tool inventory (digest
  `b2cbd3f2…`, `clarify` present).
- Tool-call stream parsed end-to-end (including the content+tool_calls
  chunk), arguments fragmented (45 + 58, joined 103, valid JSON).
- Exactly one follow-up request: message roles `system, user, assistant,
  tool`; assistant message carries `tool_calls` with name `clarify`; tool
  message carries a Hades-owned synthetic result marker.
- Second assistant answer rendered; ready returned; no busy marker, no tool
  overlay, no third request (no loop).
- Ctrl+C clean exit, terminal restored.

## Safe boundary

One hop only. A follow-up response that itself requests tool calls is
recorded and stops — no unbounded loop. The clarify question surface and the
real Hermes tool-result content are unobserved and not reproduced; the result
marker is explicit Hades behavior, not parity.

## Parser fix

The live end-to-end path previously dropped `tool_calls` when a delta chunk
carried both `content` and `tool_calls` (unit tests fed events directly and
missed it). The SSE parser now emits both events from one chunk; regression
test added.

## Evidence

- `tests/fixtures/parity/OBS-0115-hades-tool-result-follow-up.json`
- `.hades/runtime/tool-call-deltas-replay.json`
