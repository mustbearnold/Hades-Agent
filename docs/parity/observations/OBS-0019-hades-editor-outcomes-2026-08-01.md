# Hades implementation contract: OBS-0019

- Subject: Hades deterministic editor handoff outcomes
- Reference contract: [OBS-0018](OBS-0018-hermes-editor-outcomes-2026-08-01.md)
- Terminal: tmux-backed PTY at 120x40
- Contract fixture: `tests/fixtures/parity/OBS-0019-hades-editor-outcomes.json`
- Executable oracle: `scripts/replay_editor_outcomes.py`
- Task: HAD-019

Hades now exercises the deterministic editor outcomes captured from the pinned
Hermes reference. The replay starts each case with a fresh `HERMES_HOME`,
injects a controlled `VISUAL`/`EDITOR` command, and observes the actual TUI
after `Ctrl+G` returns.

## Implemented contract

- A clean editor exit with non-empty output submits the edited text and enters
  the busy state.
- Internal newlines are preserved and `trim_end()` removes the final editor
  line ending without stripping spaces before an internal newline.
- Empty clean output leaves the original composer draft and does not change its
  ready state.
- A nonzero editor exit is treated as cancellation; the original draft remains
  and no submission occurs.
- Tokenized `VISUAL`/`EDITOR` commands can be replayed without changing the
  ordinary Enter submission path.

The implementation contract is intentionally narrower than a full editor
integration. Interactive editor prompts, unavailable-editor fallback and
launch failures, busy-turn handoff, attachments, queue editing, and an empty
initial composer remain unclaimed.

## Linked artifacts

- [Hades implementation fixture](../../../tests/fixtures/parity/OBS-0019-hades-editor-outcomes.json)
- [Replay script](../../../scripts/replay_editor_outcomes.py)
- [Hermes reference observation](OBS-0018-hermes-editor-outcomes-2026-08-01.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
