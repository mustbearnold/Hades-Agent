# Implementation observation: OBS-0031

- Subject: Hades remote OSC52 TMUX/STY passthrough parity
- Task: HAD-031
- Reference observation: [OBS-0030](OBS-0030-hermes-osc52-multiplexer-passthrough-2026-08-01.md)
- Capture: direct PTY at 120x40, synthetic `SSH_TTY`, one synthetic `TMUX` or
  `STY` marker per fresh process, synthetic `xclip`, and raw OSC52/DA1 bytes
- Contract: `tests/fixtures/parity/OBS-0031-hades-osc52-multiplexer-passthrough.json`
- Replay: `scripts/replay_osc52_clipboard.py --contract ...OBS-0031...`

Hades now selects the same OSC52 query wrappers observed in Hermes when the
remote shell has a `TMUX` or `STY` marker. TMUX has precedence when both
markers are present, matching the reference wrapper selection order. The bare
`SSH_TTY` path remains unchanged.

In the synthetic direct-PTY model, Hades consumed a usable raw OSC52 response
after both wrappers before invoking native xclip. With no response, the DA1
barrier led to `xclip -selection clipboard -out`; the native payload's trailing
newline was removed. All four controls preserved the draft, remained ready,
did not submit an agent turn, and exited cleanly after Ctrl+C.

This implementation claim is limited to the exact wrapper and fallback bytes
in OBS-0030. The replay does not start a live tmux or GNU Screen daemon,
configure an outer terminal, or prove forwarding through a real multiplexer.
Image/path payloads, gateway behavior, delayed or oversized responses, and
concurrent input remain unobserved.

## Evidence

- [Sanitized Hades fixture](../../../tests/fixtures/parity/OBS-0031-hades-osc52-multiplexer-passthrough.json)
- [Direct-PTY replay](../../../scripts/replay_osc52_clipboard.py)
- [Hermes reference observation](OBS-0030-hermes-osc52-multiplexer-passthrough-2026-08-01.md)
- [Task ledger](../../../.hades/tasks.json)
