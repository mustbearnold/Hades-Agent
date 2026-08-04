# 005 — Provider transport

Status: active
Owner: project owner

## Purpose

The provider transport carries chat-completion requests to local
OpenAI-compatible endpoints (Ollama etc.) and streams deltas back into the
reducer. Local providers commonly use `Transfer-Encoding: chunked`; the
transport must decode chunk framing, tolerate cold model loads, and support
cooperative cancellation.

## Requirements

- R1. Requests target a loopback OpenAI-compatible endpoint
  (`/v1/chat/completions`) with a synthetic key; no real credential ever
  crosses the replay boundary.
- R2. The SSE parser decodes HTTP chunked transfer encoding before line
  parsing; non-chunked responses pass through unchanged.
- R3. The header-read wait ceiling is 120 s (cold local model loads can take
  tens of seconds before the first byte); connect/write timeouts stay at
  10 s.
- R4. Streams are reducible at the provider-event boundary (ADR-0005):
  role delta, content deltas, tool-call deltas, finish_reason, DONE — with
  cooperative cancellation closing the socket.
- R5. Tool-call deltas accumulate JSON argument fragments; a bounded follow-up
  answers plainly so the one-hop loop terminates.
- R6. Failure modes are replayed: HTTP error, malformed SSE, incomplete
  stream (no DONE), and recovery with a follow-up request.

## Acceptance criteria

- [ ] A1. Given a chunked SSE response, when streamed, then deltas arrive in
      order and the final DONE is parsed — identical events to the plain
      path.
- [ ] A2. Given a delayed first byte (cold model), when the request is sent,
      then the header wait tolerates the delay up to the 120 s ceiling.
- [ ] A3. Given an active stream, when Ctrl+C is pressed, then the provider
      socket is closed and the partial response is preserved.
- [ ] A4. Given malformed SSE, when parsed, then the failure surfaces as a
      provider error and recovery works on the next turn.

## Out of scope

- Remote/gateway providers and OAuth (explicit unknowns).
- Tool execution (deltas are rendered, not executed).

## Open questions

- None recorded beyond the observed contracts (OBS-0051, OBS-0053).

## Links

Code: `crates/hades-provider/src/lib.rs` · Tests: `scripts/replay_local_provider.py`,
`scripts/replay_local_provider_timing.py`, `scripts/replay_tool_call_deltas.py` ·
ADRs: ADR-0004, ADR-0005, ADR-0006, ADR-0007
