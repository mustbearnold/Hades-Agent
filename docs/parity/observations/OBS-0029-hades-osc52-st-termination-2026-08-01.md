# Implementation observation: OBS-0029

- Subject: Hades remote OSC52 ST-terminated response parity
- Task: HAD-029
- Reference observation: [OBS-0028](OBS-0028-hermes-osc52-st-termination-2026-08-01.md)
- Capture: direct PTY at 120x40, synthetic `SSH_TTY`, no `TMUX`/`STY`, synthetic
  `xclip`, and raw OSC52/DA1 bytes
- Replay: `scripts/replay_osc52_clipboard.py`

Hades matched the observed Hermes ST boundary behavior in all three controls.
The usable ST-terminated response inserted `st-remote  ` and `line-two` before
the native provider could run. Empty and invalid-base64 ST responses invoked
`xclip -selection clipboard -out` after the response boundary and inserted the
case-native payload.

Each case preserved the draft, removed only the provider or OSC52 payload's
trailing newlines, stayed ready without the busy interrupt marker, did not
submit an agent turn, and exited cleanly after Ctrl+C. The replay asserts the
exact query, ST response, DA1 barrier, provider order, provider arguments, and
screen markers from the sanitized OBS-0028 contract.

This slice required no runtime source change: the existing typed OSC52 parser
and fallback seam already matched the newly observed reference behavior. The
new contract prevents that claim from remaining unit-test-only.

## Explicitly unknown or unavailable

- Delayed or oversized responses, BEL variants beyond OBS-0027, TMUX/STY
  passthrough, image/path payloads, gateway behavior, and concurrent input
  remain unknown.
- This observation claims only the three OBS-0028 ST controls in Hades.

## Evidence

- [Sanitized Hades contract](../../../tests/fixtures/parity/OBS-0029-hades-osc52-st-termination.json)
- [Reference contract](../../../tests/fixtures/parity/OBS-0028-hermes-osc52-st-termination.json)
- [Direct PTY replay](../../../scripts/replay_osc52_clipboard.py)
- [Task ledger](../../../.hades/tasks.json)
