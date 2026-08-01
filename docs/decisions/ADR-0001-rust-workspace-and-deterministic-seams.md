# ADR-0001: Rust workspace with deterministic seams

- Status: accepted
- Date: 2026-08-01

## Context

Hades Agent must become a high-fidelity terminal application while remaining
tractable for autonomous agents. A single binary with terminal code, state
transitions, and external effects mixed together would make parity failures
difficult to localize and replay.

## Decision

Use a small Cargo workspace with four initial crates:

- `hades-core` owns serializable domain events, session state, and reference
  trace vocabulary;
- `hades-app` owns deterministic state transitions;
- `hades-tui` owns terminal rendering and snapshot generation;
- `hades-cli` owns process lifecycle and terminal I/O.

External effects must enter through an explicit seam. The application reducer
must be testable without a terminal, and the renderer must be testable without
an interactive terminal.

## Consequences

Agents can implement and verify a behavior at one seam before integrating it.
The workspace has more files than a one-crate prototype, but that cost buys
replayability, narrower reviews, and clearer ownership.
