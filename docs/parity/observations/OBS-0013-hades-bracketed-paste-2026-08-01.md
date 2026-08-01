# Hades implementation contract: OBS-0013

- Subject: Hades bracketed-paste implementation slice
- Reference evidence: Hermes OBS-0010 at commit `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Terminal: tmux-backed PTY at 120x40
- Task: HAD-013
- Contract fixture: `tests/fixtures/parity/OBS-0013-hades-bracketed-paste.json`
- Executable oracle: `scripts/replay_paste.py`

OBS-0010 observed a bracketed paste containing `paste-one`, a newline, and
`paste-two`. Hermes preserved the newline in the composer and did not submit
the draft. Hades now accepts crossterm's decoded `Event::Paste`, inserts the
whole value at the composer cursor, and leaves submission to a later Enter.

The replay sends the terminal bracketed-paste start and end markers around one
value, then captures the actual 120x40 screen. It asserts both pasted lines
and the absence of busy/submission markers. The core and app tests also prove
that a paste is a reducer event rather than a sequence that can accidentally
trigger Enter.

This task does not claim successful clipboard-provider reads, image or path
paste, paste behavior in overlays or busy turns, or any selection/mouse
semantics. Those remain unknown until separately observed.

## Linked artifacts

- [Reference observation](OBS-0010-hermes-input-editing-keymap-2026-08-01.md)
- [Hades paste contract](../../../tests/fixtures/parity/OBS-0013-hades-bracketed-paste.json)
- [Paste replay](../../../scripts/replay_paste.py)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
