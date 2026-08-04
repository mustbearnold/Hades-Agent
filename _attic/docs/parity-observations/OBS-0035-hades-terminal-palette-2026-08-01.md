# Hades implementation observation: OBS-0035

- Subject: Hades implementation of the Hermes terminal palette subset
- Reference contract: [OBS-0034](OBS-0034-hermes-terminal-palette-2026-08-01.md)
- Hades source: workspace commit under test
- Terminal: fresh direct PTY at 120x40, `TERM=xterm-256color`
- Capture: raw PTY bytes plus a sanitized terminal-cell model
- Task: HAD-035
- Fixture: `tests/fixtures/parity/OBS-0035-hades-terminal-palette.json`
- Replay: `scripts/replay_terminal_palette.py`

HAD-035 carries the styles observed in OBS-0034 into the typed Hades
renderer. The palette is represented by a dedicated `HermesPalette` value in
`crates/hades-tui/src/lib.rs`; the startup text and geometry remain the
existing 120x40 contract, while the final styled projection assigns only the
observed landmarks.

## Verified controls

The focused Ratatui test checks the modeled cells for the startup brand,
secondary text, ready footer, composer, busy interrupt affordance, and
interrupted completion marker. The direct-PTY replay additionally checks the
same styles after actual Crossterm emission for startup, typed composer, busy
interruption, interrupted completion, and setup-required controls.

The live backend emits Ratatui's grouped forms: indexed foregrounds include a
default-background reset (`38;5;<index>;49m`), and the busy white/gold pair is
emitted as one grouped truecolor sequence. These are implementation-specific
SGR forms; the replay treats them as required emitted representatives while
the modeled cell styles remain the parity assertion.

Hades explicitly enables Crossterm color output before entering the TUI. This
matches the observed Hermes behavior when the parent environment contains
`NO_COLOR=1`; the replay therefore exercises the inherited environment rather
than silently removing it. The busy case is interrupted before any response,
and the setup-required case exits after the observed two-Ctrl+C cleanup.

## Boundary and unknowns

This implementation claim covers the named OBS-0034 styles under
`TERM=xterm-256color`, the dark/default Hades surface, and a 120x40 PTY. It
does not claim byte-for-byte redraw identity, a complete Hermes theme,
animated face frames, successful model streaming, partial tokens, tool calls,
provider errors, retries, alternate themes or terminals, cursor placement,
hyperlinks, mouse styling, or wide-cell behavior.

## Linked artifacts

- [Hades palette fixture](../../../tests/fixtures/parity/OBS-0035-hades-terminal-palette.json)
- [Direct-PTY replay](../../../scripts/replay_terminal_palette.py)
- [Focused renderer tests](../../../crates/hades-tui/src/lib.rs)
- [Fixture validator](../../../scripts/validate_reference_fixture.py)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
