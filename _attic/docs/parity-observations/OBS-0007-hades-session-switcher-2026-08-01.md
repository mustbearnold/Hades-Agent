# Session switcher contract: OBS-0007

- Subject: Hades 120x40 `Ctrl+X` session switcher projection
- Reference: OBS-0001 step 5 and step 6
- Product surface: hades-core, hades-app, and hades-tui
- Contract fixture: `tests/fixtures/parity/OBS-0007-session-switcher.json`
- Executable oracle: focused reducer/snapshot tests and `differential-replay`
- Task: HAD-008

## Contract

From ready state, `Ctrl+X` opens a modal titled `Sessions`. The modal exposes
the observed live/resumable counts, `+ new`, the current session, and the
keyboard affordances for switching, creating, refreshing, closing, and pressing
Esc. Hades uses deterministic placeholders for session identity and counts;
session creation, switching, refresh, and persistence remain outside this
slice.

`Esc` closes the overlay and returns control to the composer. The replay proves
that by typing `hello` after closing and then exiting cleanly with Ctrl+C.
While the modal is open, ordinary input is intentionally consumed so unobserved
session semantics cannot be accidentally implied.

## Normalization boundary

The snapshot test asserts the fixed 120x40 text landmarks. The PTY replay checks
the stable modal markers and post-close input acceptance, while allowing sparse
crossterm redraw output to omit spaces. Colors, cursor position, exact modal
geometry beyond the supported frame, and session persistence are not claimed.

## Linked artifacts

- [Contract fixture](../../../tests/fixtures/parity/OBS-0007-session-switcher.json)
- [Core state and reducer](../../../crates/hades-core/src/lib.rs)
- [Application transition](../../../crates/hades-app/src/lib.rs)
- [Renderer and snapshot test](../../../crates/hades-tui/src/lib.rs)
- [Differential replay](../../../scripts/differential_replay.py)
- [Reference observation](OBS-0001-hermes-main-2026-08-01.md)
