# ADR-0002: Evidence-first parity

- Status: accepted
- Date: 2026-08-01

## Context

An exact clone is unusually vulnerable to plausible invention. Terminal
applications have many behaviors that are not visible in a static source
inspection: resize rules, cursor placement, cleanup, key handling, transient
states, and error timing.

## Decision

Treat the Hermes reference as an oracle only through provenance-bearing
observations. Each parity claim must link a reference observation to a
normalized contract and a Hades executable oracle. Unknown behavior is a first-
class state in the parity ledger and task system.

The preferred oracle order is:

1. differential replay;
2. normalized cell-level golden frame;
3. deterministic lifecycle or performance probe;
4. focused unit or integration test.

Manual inspection can guide research, but it cannot close a parity task alone.

## Consequences

Early progress may appear slower because the project captures the reference
before coding. Later agents inherit durable evidence instead of rediscovering
behavior or accumulating incompatible approximations.
