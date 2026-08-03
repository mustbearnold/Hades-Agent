# ADR-0008: Hades Agent is entirely Rust — including development tooling

- Status: accepted
- Date: 2026-08-04

## Context

The product (crates `hades-core`, `hades-app`, `hades-tui`, `hades-cli`,
`hades-provider`) is Rust. The development harness that drives the parity
loop — reference probes, Hades replays, the differential replay, fixture
validation, the control plane, and the verify orchestration — is ~31k LOC of
Python across 100 files under `scripts/`, plus 518 LOC of shell.

The project owner directed that Hades Agent be *entirely* Rust. The current
split means the product and its quality gates are written in two languages,
the harness cannot reuse the product's typed seams, and the parity machinery
itself is not subject to the same engineering laws as the product.

## Decision

Migrate all development tooling to Rust, in phases, with every phase keeping
the gate green:

1. **Harness foundation** — new workspace crate `hades-dev` providing the
   shared primitives every probe and replay depends on: the ANSI terminal
   screen emulator (`Screen`, `Cell`, `Style`, SGR parsing), PTY spawn and
   control (window sizing, raw mode, terminal flags), and the
   wait/drain/write/stop harness. Unit-tested against the same escape
   sequences the Python harness already parses.
2. **Fixture validation** — `validate_reference_fixture.py` semantics as a
   Rust subcommand (provenance, sanitization, normalization contracts).
3. **Control plane** — `scripts/agent/control_plane.py` semantics as a Rust
   subcommand (validate/next/show/claim/complete/block/cancel over
   `.hades/tasks.json`).
4. **Hades replays** — `scripts/replay_*.py` as Rust subcommands driving the
   Hades binary through the harness.
5. **Hermes reference probes** — `scripts/probe_hermes_*.py` as Rust
   subcommands observing the pinned reference through the harness. This is
   the largest phase; probes keep their exact report JSON shapes so the
   gate's per-probe contracts and `.hades/runtime/` evidence stay compatible.
6. **Verify orchestration** — `scripts/verify.sh` / `verify_fast.sh` as a
   Rust `verify` subcommand, replacing the shell wrapper; `justfile` targets
   delegate to it.

Migration rules:

- Every phase lands behind the existing `just verify` gate. A Python module
  is only deleted when its Rust replacement passes the same contract with
  the same report shape.
- Reference observations (OBS-*.md), parity fixtures under
  `tests/fixtures/parity/`, and the captured reference checkout remain the
  source of truth; Rust tooling must not re-negotiate them.
- The harness crate follows the same engineering laws as the product:
  typed state transitions, no invented behavior, regression oracles at the
  narrowest seam.
- Until a phase completes, the gate runs both the remaining Python and the
  new Rust tooling so no parity evidence is ever unguarded.

## Consequences

- One language across product and gates; harness code can reuse product
  types (e.g., the provider event reducer) instead of re-deriving shapes.
- The ~40 reference probes can eventually run in parallel (the harness
  controls ports), shrinking the completion gate from ~14 minutes.
- Phased migration keeps `just verify` green throughout; no big-bang
  rewrite.
- The pinned Hermes reference remains Python (it is the *observed* system,
  not part of Hades); the Rust harness drives it through a PTY exactly as
  the Python harness does today.
- `scripts/` shrinks to zero Python by the end; `justfile` targets become
  thin delegates to `cargo run --bin hades-dev ...`.
