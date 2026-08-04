# Hades implementation observation: OBS-0033

- Subject: Hades remote OSC52 timing and bounded decoded-payload parity
- Task: HAD-033
- Reference contract: [OBS-0032](OBS-0032-hermes-osc52-timing-limits-2026-08-01.md)
- Hades fixture: `tests/fixtures/parity/OBS-0033-hades-osc52-timing-limits.json`
- Replay: `scripts/replay_osc52_timing_limits.py`

Hades now uses the observed 500 ms remote OSC52 response race. The direct-PTY
replay sends a usable BEL-terminated response at the 100 ms control and Hades
inserts it before invoking native xclip. A response supplied only after the
500 ms boundary falls through to `xclip -selection clipboard -out`; its late
OSC52 text is not inserted.

The implementation keeps the existing bare, TMUX, and STY query bytes while
scanning incoming OSC52 data incrementally, so bounded responses are not
rescanned from the beginning on every PTY chunk. Pasted text is inserted in one
composer operation, and the 120x40 Hermes surface renders only the visible tail
of an oversized single line; the full draft remains in application state.

The same replay consumes deterministic immediate 256 KiB and 512 KiB decoded
payloads before the timeout boundary. It checks the exact bare OSC52 query and
DA1 bytes, payload hashes or end markers, native-provider order, readiness,
absence of the busy marker, non-submission, and terminal cleanup. The existing
raw-response safety cap remains bounded, but these controls do not define a
universal Hades maximum-size contract.

## Model boundary

This implementation claim covers only the four OBS-0032 direct-PTY controls.
It does not claim larger-payload behavior, timing jitter parity, a universal
maximum-size limit, ST termination beyond the existing control, live
TMUX/STY/outer-terminal forwarding, images/paths, gateway behavior, or
concurrent input.
