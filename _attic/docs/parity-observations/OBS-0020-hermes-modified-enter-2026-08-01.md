# Reference observation: OBS-0020

- Subject: Hermes TUI native modified Enter behavior
- Reference: Hermes Agent 0.19.1 / `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Terminal: direct PTY at 120x40 with raw byte writes
- Capture: ANSI-stripped PTY output after direct CSI-u input
- Runtime: Node 22.22.2, npm 10.9.7, Python 3.11.14, uv 0.12.1
- Task: HAD-020
- Contract fixture: `tests/fixtures/parity/OBS-0020-hermes-modified-enter.json`
- Oracle: `scripts/validate_reference_fixture.py`

OBS-0010 could not isolate modified Enter through `tmux send-keys`; this
observation removes that harness limitation by writing the documented terminal
bytes directly to the reference process's PTY. Each case used a fresh synthetic
`HERMES_HOME`, the loopback custom provider, and a PTY window explicitly set to
120x40 before launch.

## Direct PTY inputs

| Case | Bytes | Result |
| --- | --- | --- |
| Shift+Enter | `ESC[13;2u` (`1b 5b 31 33 3b 32 75`) | Inserts a newline; `shift-probe` followed by `after` remains a ready draft and does not enter busy state. |
| Alt+Enter | `ESC[13;3u` (`1b 5b 31 33 3b 33 75`) | Inserts a newline; `alt-probe` followed by `after` remains a ready draft and does not enter busy state. |
| Plain Enter control | `0d` | Submits the draft and enters busy state with `Ctrl+C to interrupt…`. |

Both modified cases were then cleared and exited with two Ctrl+C presses; the
reference restored the terminal cleanly. The contract therefore distinguishes
modified Return from ordinary Enter at the actual byte-stream boundary rather
than relying on a terminal key-name abstraction.

## Explicitly unknown or environment-sensitive

- Terminal emulators vary in whether and how they emit CSI-u or
  modifyOtherKeys sequences, so this is a reference parser contract rather
  than a claim that every terminal produces the bytes.
- The xterm modifyOtherKeys `ESC[27;2;13~` Shift+Enter encoding, Ctrl+Enter,
  and other modified Return forms were not captured here.
- Hades implementation parity is intentionally not claimed by this
  research-only observation.

## Linked artifacts

- [Sanitized reference fixture](../../../tests/fixtures/parity/OBS-0020-hermes-modified-enter.json)
- [Fixture validator](../../../scripts/validate_reference_fixture.py)
- [Hades implementation observation](OBS-0021-hades-modified-enter-2026-08-01.md)
- [Original keymap observation](OBS-0010-hermes-input-editing-keymap-2026-08-01.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
