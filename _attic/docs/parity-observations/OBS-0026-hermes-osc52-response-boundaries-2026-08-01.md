# Reference observation: OBS-0026

- Subject: Hermes remote OSC52 empty and malformed-response boundaries
- Task: HAD-026
- Reference checkout: `/tmp/hades-hermes-ref-X3bLd0`
- Source commit: `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Capture: direct PTY at 120x40, synthetic `SSH_TTY`, no `TMUX`/`STY`, synthetic
  `xclip`, and raw OSC52/DA1 bytes
- Probe: `scripts/probe_hermes_osc52_response_boundaries.py`

The probe sent Ctrl+V as raw `0x16`, observed Hermes emit the exact bare query
`ESC ] 52 ; c ; ? BEL`, and supplied one malformed response per fresh process.
Each case then answered the two DA1 barriers emitted by the TUI. Empty payload,
query-marker payload, invalid base64, invalid selection, and an unterminated
OSC52 response all fell through to the synthetic native provider:
`xclip -selection clipboard -out`.

Every observed fallback inserted the case-native text after the existing draft,
removed the provider's trailing newline, stayed in the ready state, and did not
submit an agent turn. The native provider was not invoked before the OSC52
boundary was answered, and the PTY cleanup completed without a busy-state
interrupt marker.

The exact response and barrier bytes, sanitized input sequences, provider
arguments, and output markers are recorded in the machine-validated fixture.

## Explicitly unknown or unavailable

- Delayed responses after Hermes' 500 ms OSC52 read race and oversized payloads
  were not claimed by this bounded fixture.
- ST-terminated response variants were not separately observed; this fixture
  covers BEL termination and one unterminated response.
- TMUX/STY passthrough wrapping, image/path clipboard behavior, gateway
  behavior, and concurrent input remain separate unknowns.
- This is reference research only; it does not claim Hades implementation
  parity.

## Evidence

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0026-hermes-osc52-response-boundaries.json)
- [Boundary probe](../../../scripts/probe_hermes_osc52_response_boundaries.py)
- [Prior bare-SSH OSC52 observation](OBS-0024-hermes-osc52-clipboard-2026-08-01.md)
- [Task ledger](../../../.hades/tasks.json)
