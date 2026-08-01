# Hades implementation contract: OBS-0015

- Subject: Hades empty-clipboard Ctrl+V fallback
- Reference evidence: Hermes OBS-0010 at commit `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Terminal: tmux-backed PTY at 120x40
- Task: HAD-015
- Contract fixture: `tests/fixtures/parity/OBS-0015-hades-empty-clipboard.json`
- Executable oracle: `scripts/replay_clipboard.py`

OBS-0010 observed Ctrl+V with no readable clipboard provider reporting
`No image found in clipboard` while leaving the composer unchanged. Hades now
implements exactly that deterministic miss path in ready state. The status
message is rendered in the Hermes 120x40 surface and the draft remains
editable.

This task does not claim successful clipboard reads, text/image/path paste,
provider discovery, or clipboard behavior in overlays or busy turns. Those
remain unknown until separately observed.

## Linked artifacts

- [Reference observation](OBS-0010-hermes-input-editing-keymap-2026-08-01.md)
- [Hades clipboard contract](../../../tests/fixtures/parity/OBS-0015-hades-empty-clipboard.json)
- [Clipboard replay](../../../scripts/replay_clipboard.py)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
