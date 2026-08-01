# ADR-0004: Isolate the first local provider transport

- Status: accepted
- Date: 2026-08-01

## Context

OBS-0050 shows Hermes' first bounded local-provider turn crossing an
OpenAI-compatible streaming endpoint. Hades needs a real protocol seam before
the TUI can consume provider output, but the bootstrap must not acquire an
implicit external-network dependency or mix HTTP parsing into the reducer.

## Decision

Add a small `hades-provider` workspace crate for the first transport slice. It
owns request serialization, loopback URL validation, synchronous HTTP/1.1
exchange, and OpenAI-compatible SSE normalization into typed stream events.
The first implementation accepts only `http://127.0.0.1:<port>/...`; HTTPS,
non-loopback hosts, tool execution, persistence, and provider discovery remain
separate work. The app and TUI consume this seam only through typed events in a
later integration task.

## Consequences

The wire contract is independently testable against an in-process TCP fixture,
and the product can later add cancellation and async scheduling without
rewriting URL or SSE behavior. The first slice is intentionally narrow: it
cannot yet connect Hades' interactive reducer to a real model or serve cloud
providers.
