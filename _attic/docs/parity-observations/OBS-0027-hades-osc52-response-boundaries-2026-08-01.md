# Hades observation: OBS-0027

- Subject: Hades remote OSC52 empty and malformed-response fallback parity
- Reference: [OBS-0026](OBS-0026-hermes-osc52-response-boundaries-2026-08-01.md)
- Task: HAD-027
- Capture: direct PTY at 120x40, synthetic `SSH_TTY`, no `TMUX`/`STY`, synthetic
  `xclip`, and raw response bytes from OBS-0026
- Contract: `tests/fixtures/parity/OBS-0027-hades-osc52-response-boundaries.json`
- Replay: `scripts/replay_osc52_clipboard.py --contract ...OBS-0027...`

Hades was replayed in a fresh process for each OBS-0026 response control:
empty payload, query-marker payload, invalid base64, invalid selection, and an
unterminated OSC52 response. Every case emitted the exact bare query
`ESC ] 52 ; c ; ? BEL`, emitted the DA1 barrier `ESC [ c`, accepted the
controlled response bytes, and then invoked the synthetic native provider with
`-selection clipboard -out`.

Each fallback inserted the native payload after the existing draft, removed the
provider's trailing newline, remained ready without submitting a turn, and
exited cleanly after Ctrl+C. The existing OBS-0025 replay continues to prove
that a usable OSC52 response wins before the native provider.

This closes only the response-boundary behavior observed in OBS-0026. It does
not widen parity to delayed, oversized, or ST-terminated responses, TMUX/STY
passthrough, image/path attachments, gateway behavior, or concurrent input.

## Evidence

- [Hades response-boundary fixture](../../../tests/fixtures/parity/OBS-0027-hades-osc52-response-boundaries.json)
- [Direct-PTY replay](../../../scripts/replay_osc52_clipboard.py)
- [Hermes reference observation](OBS-0026-hermes-osc52-response-boundaries-2026-08-01.md)
- [Task ledger](../../../.hades/tasks.json)
