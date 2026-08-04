# Implementation observation: OBS-0025

- Subject: Hades bare-SSH OSC52-first Ctrl+V clipboard behavior
- Reference contract: [OBS-0024](OBS-0024-hermes-osc52-clipboard-2026-08-01.md)
- Terminal: direct PTY at 120x40 with raw byte writes
- Capture: synthetic `SSH_TTY`, controlled OSC52 responder, synthetic `xclip`, and isolated `HOME`
- Task: HAD-025
- Contract fixture: `tests/fixtures/parity/OBS-0025-hades-osc52-clipboard.json`
- Replay: `scripts/replay_osc52_clipboard.py`

Hades now checks the stable bare remote-shell path before native clipboard
providers. When `SSH_TTY`, `SSH_CONNECTION`, or `SSH_CLIENT` is present without
the unobserved `TMUX`/`STY` wrappers, ready non-overlay Ctrl+V writes the exact
OSC52 query `ESC ] 52 ; c ; ? BEL` followed by the DA1 barrier `ESC [ c`.

## OSC52 response path

The replay returns the controlled BEL-terminated OSC52 response for
`osc-remote  \nline-two\n\n` and acknowledges the DA1 response
`ESC [ ? 62 c`. Hades base64-decodes the response, removes only trailing
newlines, inserts the text at the cursor, remains ready, and does not invoke
the native xclip provider.

## Native fallback control

The no-response control acknowledges only the DA1 barrier. Hades treats the
bounded OSC52 read as unavailable, invokes `xclip -selection clipboard -out`,
inserts `native-fallback`, and remains ready without submission.

## Boundaries

- `TMUX`/`STY` passthrough wrapping is intentionally excluded because OBS-0024
  isolated the bare `SSH_TTY` path.
- Invalid, empty, delayed, and oversized responses are rejected or bounded at
  the protocol seam but do not have separate PTY claims in this task.
- Image/path clipboard, gateway behavior, and concurrent user input during the
  response window remain unknown.

## Linked artifacts

- [Hades OSC52 fixture](../../../tests/fixtures/parity/OBS-0025-hades-osc52-clipboard.json)
- [OSC52 replay](../../../scripts/replay_osc52_clipboard.py)
- [Hermes reference observation](OBS-0024-hermes-osc52-clipboard-2026-08-01.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
