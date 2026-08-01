# Hades Agent project context

Status date: 2026-08-01

## Mission

Build Hades Agent, an exact Hermes TUI clone rewritten in Rust, with a
development loop that lets bounded AI agents make independently verifiable
progress from August 1, 2026 through 2027.

## Confirmed current state

- The repository began as an empty workspace on 2026-08-01.
- Rust 1.97.1 is available and pinned by `rust-toolchain.toml`.
- The initial scaffold is a Cargo workspace with core state, application
  transitions, a Ratatui view, and a CLI entry point.
- The autonomous development control plane lives in `.hades/` and `.agents/`.
- The Hermes reference is pinned to commit
  `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`; the provenance and sanitized
  startup/lifecycle artifacts are in `docs/parity/observations/OBS-0001*`.
- HAD-003 established a real-PTY lifecycle oracle in
  `scripts/probe_tui_lifecycle.py`.
- HAD-004 implements the first reference-backed core transition:
  submit text, enter a typed busy state, interrupt with Ctrl+C, then exit with
  Ctrl+C from ready.
- HAD-007 aligns the 120x40 busy and interrupted projection with the observed
  Hermes markers and drives those PTY assertions from the OBS-0006 visual
  contract; exact face-state timing remains intentionally unclaimed.
- HAD-008 adds typed session-overlay state, Ctrl+X open/Esc close transitions,
  and a deterministic 120x40 session switcher projection; session creation,
  switching, refresh, and persistence remain unknown.
- HAD-009 adds the observed `/help` setup-required path with retained-input
  rendering, first-Ctrl+C clearing, and second-Ctrl+C clean exit; provider setup
  and model selection remain unimplemented.
- HAD-010 captures the pinned Hermes input-editing/keymap subset: persistent
  history recall, cursor editing, multiline fallback, slash completion, Ctrl+G
  editor return, bracketed paste, and the empty-clipboard miss path. Native
  modified Enter, mouse input, successful clipboard flows, and persistence
  across process restart remain explicit unknowns.
- HAD-011 implements the reference-backed composer subset with a dedicated
  Unicode-safe cursor model, session-local history recall, backslash-plus-Enter
  multiline input, terminal Home/End mapping, focused tests, and isolated PTY
  replay. Disk history, completion, paste, editor handoff, mouse, and other
  unobserved keymap behavior remain outside the claim.
- HAD-012 implements the observed slash-completion slice: exact `/he` items,
  deterministic rendering, and Tab application of `/help` before the fallback
  surface cycle. Completion gateway timing, other prefixes, multiline/busy
  behavior, and selection semantics remain unknown.

## Unknown until observed

- Hermes TUI color palette, typography, the unobserved keymap/focus surfaces,
  copy, error states, timing, persistent history, and the remaining interaction
  surfaces.
- Which Hermes behaviors are stable contracts versus implementation details.
- Successful provider/model streaming, tool calls, and the exact behavior of
  terminal-dependent surfaces beyond the captured observations.

Unknowns are deliberate. The first product task is to capture the reference
contract rather than let the scaffold become an accidental specification.

## Working vocabulary

- **Reference** — the Hermes TUI build and environment used for a specific
  observation.
- **Observation** — a provenance-bearing record of one reference interaction.
- **Trace** — ordered inputs and observable outputs that can be replayed.
- **Golden frame** — a normalized terminal buffer snapshot used as a visual
  oracle.
- **Parity claim** — a statement backed by an observation and an executable
  Hades oracle.
- **Unknown** — a behavior not yet observed or not stable enough to claim.

## Non-goals for the scaffold

The bootstrap application still does not pretend to implement Hermes behavior
that has not been captured. It provides the seams needed to add that behavior
safely: typed events, a reducer, deterministic rendering, snapshot output, task
dependencies, and proof-required task completion.
