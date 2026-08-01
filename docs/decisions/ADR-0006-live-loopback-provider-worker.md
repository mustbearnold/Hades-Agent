# ADR-0006: Connect the loopback transport through a disposable CLI worker

- Status: Accepted
- Date: 2026-08-01
- Scope: `hades-cli` runtime integration

## Context

HAD-053 provides a synchronous, loopback-only OpenAI-compatible transport and
HAD-054 provides the typed reducer events. Calling the transport directly from
the crossterm event loop would freeze redraw and input while the provider is
connecting or reading its response.

## Decision

The CLI reads an explicit `HADES_PROVIDER_BASE_URL`, with `HADES_MODEL`
defaulting to `palette-model` and an optional `HADES_PROVIDER_API_KEY`. The
URL is validated by `hades-provider`, which currently permits only
`http://127.0.0.1:<port>/...`. Each submitted user turn gets a worker thread
and an owned channel. The worker translates transport events into
`ProviderEvent`s; the main loop drains them between redraws.

Transport construction failures become visible reducer errors. Ctrl+C drops
the active receiver, and a new request replaces the old receiver, so late
worker sends cannot be delivered to a later turn. The API key is passed only to
the transport and is never logged or included in replay evidence. A later
unconfigured-startup boundary selects a typed startup state before dispatch,
so a fresh no-endpoint launch currently remains on `starting agent…` rather
than reaching this provider error guard.

## Consequences

`hades tui` is no longer a silent submission shell when a local endpoint is
configured. A fresh no-endpoint launch follows the separately captured
Hermes starting-agent boundary and now retains a bounded visible draft without
delivering it to a provider. It is not yet a setup or eventual queue-drain
flow. The initial HAD-055 transport buffered the complete HTTP response before
returning its parsed event vector; ADR-0007 supersedes that implementation
limitation with incremental parsing and cooperative socket cancellation. This
decision does not add HTTPS, cloud providers, credentials discovery,
persistence, retries, or tool execution.
