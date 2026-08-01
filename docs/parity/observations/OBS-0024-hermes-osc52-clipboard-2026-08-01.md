# Reference observation: OBS-0024

- Subject: Hermes remote-shell OSC52-first Ctrl+V clipboard behavior
- Reference: Hermes Agent 0.19.1 / `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Terminal: direct PTY at 120x40 with raw byte writes
- Capture: synthetic `SSH_TTY`, synthetic xclip provider, and explicit OSC52/DA1 responses
- Runtime: Node 22.22.2, npm 10.9.7, Python 3.11.14, uv 0.12.1
- Task: HAD-024
- Contract fixture: `tests/fixtures/parity/OBS-0024-hermes-osc52-clipboard.json`
- Probe: `scripts/probe_hermes_osc52_clipboard.py`

This observation resolves the remote text-provider precedence left open by
OBS-0022. With `SSH_TTY` set, Hermes sends a bare OSC52 clipboard query before
native providers. The direct PTY answers the query and the queued DA1 barriers
explicitly; no terminal emulator is involved.

## OSC52 response path

Hermes sends the exact query bytes `ESC ] 52 ; c ; ? BEL`. A response carrying
`osc-remote  \nline-two\n\n` is decoded, trailing newlines are removed, and the
text is inserted into the ready composer. The synthetic xclip provider is not
invoked and the draft is not submitted.

The probe also answers two DA1 barriers: one still queued from startup and one
created by the clipboard read. This is part of the transport evidence, not a
claim that every terminal emits the same startup query count.

## Timeout/native control

When no OSC52 response is sent, Hermes flushes the query, then falls back to
`xclip -selection clipboard -out`. The native payload is inserted after the
existing draft, trailing newlines are removed, and the composer remains ready.

## Boundaries

- `TMUX`/`STY` passthrough wrapping was not claimed; this capture isolates the bare remote path.
- Invalid, empty, delayed, and oversized OSC52 responses remain unknown beyond the observed timeout control.
- Hades OSC52 behavior remains unimplemented; this task is research-only.
- Image/path clipboard and gateway behavior remain separate unknowns.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0024-hermes-osc52-clipboard.json)
- [Reference probe](../../../scripts/probe_hermes_osc52_clipboard.py)
- [Native clipboard observation](OBS-0022-hermes-text-clipboard-2026-08-01.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
