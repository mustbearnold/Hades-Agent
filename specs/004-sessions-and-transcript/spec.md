# 004 — Sessions and transcript

Status: active
Owner: project owner

## Purpose

The session surface: a typed session overlay (Ctrl+X open / Esc close), a
deterministic 120x40 session switcher projection, persistent disk history,
and the multi-turn transcript rendered with streaming, errors, retries, and
cancellation.

## Requirements

- R1. The session overlay opens with Ctrl+X and closes with Esc; the
  projection matches the observed markers at 120x40.
- R2. Input history persists across process restarts (newest-1,000 load cap,
  consecutive-duplicate suppression, multiline `+` encoding), resolved via
  `HERMES_HOME`/`HOME` with fail-open file I/O.
- R3. The transcript renders provider responses as they stream, preserves
  partial responses on interruption, and isolates failed turns (a failed turn
  stays visible but does not pollute the next request's context).
- R4. Conversation context carries the message-role boundary (system/user)
  and request shape across turns; recovery after provider failure is
  verified by a follow-up request.

## Acceptance criteria

- [ ] A1. Given a configured launch, when Ctrl+X is pressed, then the session
      overlay renders with the observed markers; Esc closes it.
- [ ] A2. Given two processes on the same home, when the first writes history
      and exits, then the second recalls it with duplicates suppressed.
- [ ] A3. Given an interrupted stream, when Ctrl+C is pressed mid-delta, then
      the partial response remains visible and the socket is closed.
- [ ] A4. Given a failed provider turn, when the next prompt is submitted,
      then the failed turn does not appear in the next request's messages.

## Out of scope

- Session creation/switching/refresh/persistence internals beyond the
  observed slice (explicit unknowns).
- Mouse-driven session selection.

## Open questions

- None recorded beyond the observed-slice boundaries in CONTEXT.md.

## Links

Code: `crates/hades-app`, `crates/hades-core` · Tests: `scripts/replay_configured_surfaces.py`,
`scripts/replay_conversation_context.py`, `scripts/replay_provider_recovery.py` ·
ADRs: ADR-0001
