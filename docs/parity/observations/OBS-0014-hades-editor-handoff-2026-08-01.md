# Hades implementation contract: OBS-0014

- Subject: Hades unchanged-draft editor handoff
- Reference evidence: Hermes OBS-0010 at commit `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Terminal: tmux-backed PTY at 120x40
- Task: HAD-014
- Contract fixture: `tests/fixtures/parity/OBS-0014-hades-editor-handoff.json`
- Executable oracle: `scripts/replay_editor.py`

OBS-0010 observed that with `EDITOR=/bin/true`, typing `editor-probe` and
pressing Ctrl+G returned cleanly from the editor and submitted the unchanged
draft into the busy state. Hades now models Ctrl+G as an explicit editor
request, suspends raw mode and the alternate screen, writes a temporary draft,
runs the configured `EDITOR`, restores the terminal, and submits the resulting
file after a successful exit.

The contract intentionally proves only the unchanged-draft `/bin/true` path.
The PTY replay asserts the busy markers after the editor returns, then
interrupts and exits through the normal cleanup path.

Modified drafts, editor cancellation, multiline editor round-trips, missing or
invalid editors, and editor command-line parsing remain unknown and are not
part of this parity claim.

## Linked artifacts

- [Reference observation](OBS-0010-hermes-input-editing-keymap-2026-08-01.md)
- [Hades editor contract](../../../tests/fixtures/parity/OBS-0014-hades-editor-handoff.json)
- [Editor replay](../../../scripts/replay_editor.py)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
