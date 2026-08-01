# ADR-0007: Incremental loopback provider stream with cooperative cancellation

- Status: Accepted
- Date: 2026-08-02
- Scope: `hades-provider` and `hades-cli` local provider runtime

## Context

OBS-0052 shows that Hermes renders a first provider delta before a delayed
second delta and that Ctrl+C before completion preserves the partial response
while the provider connection closes. The HAD-055 transport buffered the whole
HTTP response before returning its parsed event vector, so the Hades worker
could not reproduce that observable boundary.

## Decision

`hades-provider` exposes an incremental `OpenAiStream` over the existing
loopback-only HTTP/SSE policy. It parses complete SSE frames as bytes arrive,
retains the existing request/response validation, and reports `Cancelled`
through a shared atomic `CancellationToken`. The read loop uses a short poll
interval so cancellation can be observed while the provider is idle; dropping
the stream closes the socket.

`hades-cli` owns one token per provider runtime. Ctrl+C and replacement of an
active request cancel and remove the runtime before the reducer can receive
late events. The worker sends each parsed delta as soon as the event loop
drains it, and cancellation is not converted into a visible provider failure
after the reducer has already handled the interrupt.

## Consequences

The bounded local provider path now renders incremental assistant text and
closes an active socket on interruption, with direct-PTY evidence in OBS-0053.
The implementation remains deliberately local-only: HTTPS, non-loopback
providers, retries, tool execution, provider discovery, credentials, OAuth,
persistence, and follow-up chat-request semantics are not introduced by this
decision. The poll interval is an implementation mechanism, not a Hermes
timing claim.
