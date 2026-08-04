# Reference observation: OBS-0028

- Subject: Hermes remote OSC52 ST-terminated response handling
- Task: HAD-028
- Reference checkout: `/tmp/hades-hermes-ref-X3bLd0`
- Source commit: `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Capture: direct PTY at 120x40, synthetic `SSH_TTY`, no `TMUX`/`STY`, synthetic
  `xclip`, and raw OSC52/DA1 bytes
- Probe: `scripts/probe_hermes_osc52_st_termination.py`

The probe sent Ctrl+V as raw `0x16`, observed Hermes emit the exact bare query
`ESC ] 52 ; c ; ? BEL`, and supplied one ST-terminated response per fresh
process. ST is the exact two-byte `ESC \` terminator.

Hermes accepted the usable ST-terminated response before invoking native xclip.
The decoded payload preserved internal spacing and line breaks while removing
only its two trailing newlines. Empty and invalid-base64 ST responses fell
through to `xclip -selection clipboard -out`; each native payload had its one
trailing newline removed.

All three cases preserved the existing draft, reached the ready state without
the busy interrupt marker, did not submit an agent turn, and cleaned up after
the bounded PTY probe. The exact response bytes, barrier bytes, input bytes,
provider arguments, and output markers are recorded in the machine-validated
fixture.

## Explicitly unknown or unavailable

- Delayed responses after Hermes' 500 ms OSC52 read race and oversized payloads
  were not exercised.
- BEL-terminated malformed and unterminated controls are covered by OBS-0026;
  this observation covers only ST-terminated valid, empty, and invalid-base64
  responses.
- TMUX/STY passthrough wrapping, image/path clipboard behavior, gateway
  behavior, concurrent input, and Hades implementation parity remain separate
  unknowns.

## Evidence

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0028-hermes-osc52-st-termination.json)
- [ST termination probe](../../../scripts/probe_hermes_osc52_st_termination.py)
- [Prior response-boundary observation](OBS-0026-hermes-osc52-response-boundaries-2026-08-01.md)
- [Task ledger](../../../.hades/tasks.json)
