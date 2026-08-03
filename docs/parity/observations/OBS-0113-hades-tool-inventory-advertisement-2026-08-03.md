# OBS-0113 — Hades advertised tool inventory and safe tool-call boundary

Date: 2026-08-03

Reference source commit: `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`

Terminal: direct PTY, 120×40

Replay: `scripts/replay_tool_call_deltas.py`

## Scope

A fresh Hades debug process with an isolated synthetic HOME/HERMES_HOME and a
probe-owned loopback provider submitted one ordinary prompt. The streaming
chat request now advertises the observed Hermes 31-tool inventory (OBS-0112)
instead of an empty tools array. The server returned assistant text plus a
fragmented `clarify` tool call with `finish_reason: "tool_calls"`, then
`[DONE]`.

## Observed boundary

- One streaming chat request reached `/v1/chat/completions` with
  `authorization_present: false` and `tool_count: 31`.
- The advertised inventory's canonical sort-keys digest is
  `b2cbd3f2bf77de3a91cf9a4844b324f6130aab8c72b2924a159cce533f38a220`,
  byte-identical to the OBS-0112 captured inventory, and `clarify` is present.
- The tool-call stream parsed, argument fragments accumulated (lengths 45 and
  58, joined length 103, valid JSON), the assistant text rendered, and the
  process returned to ready with no busy marker and no invented tool overlay.
- One chat request total; zero follow-up chat requests and zero
  tool-response requests.
- Ctrl+C exited cleanly with the alternate screen and termios restored.

## Safe boundary

Advertising the tool inventory is wire-contract parity only. Hades still never
executes, approves, or forwards tool calls; the completed-turn record from
HAD-115 (name, argument length, stable digest) is unchanged. Approval policy,
execution, results, retries, and follow-up requests remain explicit unknowns.

## Evidence

- `tests/fixtures/parity/OBS-0113-hades-tool-inventory-advertisement.json`
- `.hades/runtime/tool-call-deltas-replay.json`
