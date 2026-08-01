# Busy and interrupt visual contract: OBS-0006

- Subject: Hades 120x40 busy and interrupted projection
- Reference: OBS-0001 steps 3 and 4
- Product surface: hades-tui
- Contract fixture: `tests/fixtures/parity/OBS-0006-busy-interrupt-visual.json`
- Executable oracle: `hades-tui` focused snapshot test and `differential-replay`
- Task: HAD-007

## Contract

After submitting text, the reference presents an interruptible busy composer
with `musing…`, `mulling…`, and `Ctrl+C to interrupt…` face-state markers. The
exact face-state timing and phase order are not stable enough to claim, so Hades
renders both captured markers in a deterministic normalized footer while keeping
the interrupt prompt visible.

After Ctrl+C interrupts the turn, the reference returns to ready, shows an
`interrupted` transcript marker, and exposes a completed elapsed marker. Hades
projects that state as an `interrupted` marker plus `ready` and `✓ <seconds>s`,
where dynamic elapsed time is normalized exactly as in OBS-0001.

The typed `TurnState::Busy` to `TurnState::Ready` transition remains in
`hades-app`; this task changes the 120x40 rendering contract only.

## Normalization boundary

The snapshot test asserts exact normalized marker strings. The PTY replay uses
stable compact markers because crossterm's sparse cursor-addressed redraw stream
does not preserve every inter-word space in raw output. It does not assert face
animation timing, color, cursor placement, or a model response.

## Linked artifacts

- [Contract fixture](../../../tests/fixtures/parity/OBS-0006-busy-interrupt-visual.json)
- [Renderer and snapshot test](../../../crates/hades-tui/src/lib.rs)
- [Differential replay](../../../scripts/differential_replay.py)
- [Reference observation](OBS-0001-hermes-main-2026-08-01.md)
