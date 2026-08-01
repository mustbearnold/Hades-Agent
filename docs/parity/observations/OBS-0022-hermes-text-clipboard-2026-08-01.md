# Reference observation: OBS-0022

- Subject: Hermes TUI successful Ctrl+V text clipboard behavior
- Reference: Hermes Agent 0.19.1 / `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Terminal: direct PTY at 120x40 with raw byte writes
- Capture: ANSI-stripped PTY output with a synthetic `xclip` provider
- Runtime: Node 22.22.2, npm 10.9.7, Python 3.11.14, uv 0.12.1
- Task: HAD-022
- Contract fixture: `tests/fixtures/parity/OBS-0022-hermes-text-clipboard.json`
- Probe: `scripts/probe_hermes_text_clipboard.py`
- Oracle: `scripts/validate_reference_fixture.py`

This observation closes the successful text side of the Ctrl+V gap without
touching the host clipboard. The probe launches the pinned Hermes checkout in
a fresh direct PTY, puts a synthetic `xclip` command first in `PATH`, and logs
the exact provider arguments. It sends raw `0x16` after a draft is present.

## Observed successful text path

The synthetic provider returned `clip-one  \nclip-two\n\n`. Hermes invoked
`xclip -selection clipboard -out`, inserted the text at the cursor, preserved
the two spaces before the internal newline, removed only trailing newlines,
and kept the composer ready. The resulting draft was seed:clip-one  \nclip-two,
where \n denotes the internal newline and the two spaces before it are preserved.

No submission or busy marker occurred.

## Empty-provider control

When the same provider returned empty stdout, Hermes kept `empty-seed` intact
and did not submit. The subsequent image-fallback request was not observable in
this isolated direct PTY because no Hermes gateway response was attached. The
existing OBS-0010 capture remains the evidence for the no-provider
`No image found in clipboard` message; this observation does not widen that
claim.

## Explicitly unknown or environment-sensitive

- Remote/SSH OSC52 precedence versus native providers.
- Image-only clipboard attachment, path paste, and gateway-backed image tokens.
- Provider failures, binary-looking text, and size-limit behavior.
- Hades implementation parity, which remains a separate task.

## Linked artifacts

- [Sanitized reference fixture](../../../tests/fixtures/parity/OBS-0022-hermes-text-clipboard.json)
- [Reference probe](../../../scripts/probe_hermes_text_clipboard.py)
- [Original input/keymap observation](OBS-0010-hermes-input-editing-keymap-2026-08-01.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
