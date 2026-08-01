# Implementation observation: OBS-0023

- Subject: Hades successful Ctrl+V text clipboard behavior
- Reference contract: [OBS-0022](OBS-0022-hermes-text-clipboard-2026-08-01.md)
- Terminal: direct PTY at 120x40 with raw byte writes
- Capture: synthetic `xclip` provider, isolated `HOME`, and no host clipboard access
- Task: HAD-023
- Contract fixture: `tests/fixtures/parity/OBS-0023-hades-text-clipboard.json`
- Replay: `scripts/replay_clipboard_text.py`

Hades now resolves ready, non-overlay Ctrl+V at the CLI boundary. The provider
order follows the stable Hermes contract: WSL PowerShell when WSL markers are
present, Wayland `wl-paste --type text`, then X11 `xclip -selection clipboard
-out`. A command failure falls through; a successful but unusable result keeps
the existing image-miss fallback path.

## Successful text path

The replay places a synthetic `xclip` first in `PATH` and returns
`clip-one  \nclip-two\n\n`. Hades records the exact provider arguments, inserts the
text at the cursor, preserves the two spaces before the internal newline,
removes only trailing newlines, and remains ready. The resulting composer is
`seed:clip-one  \nclip-two`; the draft is not submitted.

## Empty-provider control

When the synthetic provider returns empty stdout, Hades leaves `empty-seed`
unchanged and retains the existing `No image found in clipboard` fallback
message. It does not submit or enter the busy state.

## Boundaries

- Provider order and normalization are unit-tested without invoking the host clipboard.
- The direct PTY replay proves only the synthetic xclip success and empty controls.
- Image attachments, path paste, OSC52 precedence, and gateway behavior remain unknown.
- Busy and overlay Ctrl+V paths do not read the provider; their prior behavior remains unchanged.

## Linked artifacts

- [Hades text clipboard fixture](../../../tests/fixtures/parity/OBS-0023-hades-text-clipboard.json)
- [Clipboard replay](../../../scripts/replay_clipboard_text.py)
- [Hermes reference observation](OBS-0022-hermes-text-clipboard-2026-08-01.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
