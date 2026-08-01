# ADR-0005: Keep provider lifecycle events at the reducer boundary

- Status: Accepted
- Date: 2026-08-01
- Scope: `hades-core`, `hades-app`, and the 120x40 TUI renderer

## Context

OBS-0050 establishes a bounded Hermes local-provider stream: a turn starts,
assistant text arrives as deltas, and the terminal returns to a ready state.
HAD-053 implements the wire transport, but the interactive Hades event loop
must not make HTTP or SSE details part of the reducer or renderer.

## Decision

Define a serializable `ProviderEvent` in `hades-core` with `Started`,
`TextDelta`, `Completed`, `Failed`, and `Cancelled` variants. `hades-app`
accepts those events through `InputEvent::Provider`, accumulates deltas into an
assistant message only while a turn is busy, and owns all turn/status/notice
transitions. The TUI renders the latest assistant response and bounded failure
or cancellation notices from app state.

The CLI/provider adapter remains a separate seam. It will translate
`hades-provider` stream events into these core events and deliver them without
blocking terminal input. This decision does not authorize credentials, external
HTTPS, tool execution, persistence, retries, or claims about Hermes behavior
outside OBS-0050.

## Consequences

The product plane has a deterministic oracle for streamed output before the
live adapter is connected. Provider protocol changes remain isolated from app
state, and stale events delivered while the app is ready are ignored. The next
integration task must define request ownership/cancellation for the live worker
before enabling a real provider in the CLI.
