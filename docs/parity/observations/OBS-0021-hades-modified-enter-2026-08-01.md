# Hades implementation observation: OBS-0021

- Subject: Hades native modified Enter parity
- Reference contract: [OBS-0020](OBS-0020-hermes-modified-enter-2026-08-01.md)
- Terminal: direct PTY at 120x40 with raw byte writes
- Capture: ANSI-stripped PTY stream with stable composer and interrupt markers
- Contract fixture: `tests/fixtures/parity/OBS-0021-hades-modified-enter.json`
- Executable oracle: `scripts/replay_modified_enter.py`
- Task: HAD-021

Hades now decodes the stable CSI-u sequences observed at the Hermes boundary.
The CLI maps `KeyCode::Enter` carrying Shift or Alt to a typed
`Key::ModifiedEnter`; the application inserts a newline through the core
composer and stays ready. Plain `Enter` continues through the existing submit
transition.

## Verified cases

| Case | Direct PTY bytes | Hades result |
| --- | --- | --- |
| Shift+Enter | `ESC[13;2u` (`1b 5b 31 33 3b 32 75`) | `shift-probe` plus `after` remains a ready multiline draft; no busy marker. |
| Alt+Enter | `ESC[13;3u` (`1b 5b 31 33 3b 33 75`) | `alt-probe` plus `after` remains a ready multiline draft; no busy marker. |
| Plain Enter | `0d` | The draft submits and reaches the busy state; Ctrl+C interrupts and a second Ctrl+C exits cleanly. |

The replay sets the PTY window to 120x40 before launch and writes bytes to the
PTY master directly. Since the capture is a raw stream of successive terminal
frames rather than a reconstructed screen buffer, the busy control asserts the
stable `interrupt` suffix while the fixture retains the semantic
`Ctrl+C to interrupt…` reference marker.

## Explicitly unclaimed

- Terminal-emulator support for emitting CSI-u modified-key sequences.
- xterm modifyOtherKeys, Ctrl+Enter, and other alternate Return encodings.
- Modified Enter behavior in overlays, busy turns, and other input paths not
  represented by the stable reference contract.

## Linked artifacts

- [Hades implementation fixture](../../../tests/fixtures/parity/OBS-0021-hades-modified-enter.json)
- [Direct-PTY replay script](../../../scripts/replay_modified_enter.py)
- [Hermes reference observation](OBS-0020-hermes-modified-enter-2026-08-01.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
