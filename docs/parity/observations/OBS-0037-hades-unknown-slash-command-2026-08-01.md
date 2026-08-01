# Hades implementation observation: OBS-0037

- Subject: Hades unknown slash-command boundary
- Reference contract: [OBS-0036](OBS-0036-hermes-slash-command-surfaces-2026-08-01.md)
- Hades source: workspace commit under test
- Terminal: fresh 120x40 tmux-backed PTY
- Capture: normalized screen markers
- Task: HAD-038
- Fixture: `tests/fixtures/parity/OBS-0037-hades-unknown-slash-command.json`
- Replay: `scripts/replay_composer.py`

HAD-038 carries the bounded Hermes unknown-command behavior into Hades. A
slash command other than the currently implemented `/help` path now follows a
typed ready-state error transition: it is recorded in the transcript, the
composer is cleared, the ready footer remains visible, and no model/busy turn
starts.

## Verified behavior

The focused core test asserts the `Notice::UnknownCommand` transition, the
ready turn, empty composer, exact two-line error, and `Continue` outcome. The
Ratatui test asserts the same error and ready surface without the busy
interrupt marker. The isolated 120x40 replay additionally proves the command
is visible while editing, disappears from the composer after submission, and
the process exits cleanly with Ctrl+C.

## Boundaries

This implementation recognizes only the observed `/help` path and treats
other slash commands as unrecognized until their Hermes behavior is captured
and implemented. `/model`, `/setup`, aliases, command arguments, reachable
providers, and all model/network behavior remain separate tasks.

## Linked artifacts

- [Hades contract](../../../tests/fixtures/parity/OBS-0037-hades-unknown-slash-command.json)
- [Generic PTY replay](../../../scripts/replay_composer.py)
- [Hermes reference observation](OBS-0036-hermes-slash-command-surfaces-2026-08-01.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
