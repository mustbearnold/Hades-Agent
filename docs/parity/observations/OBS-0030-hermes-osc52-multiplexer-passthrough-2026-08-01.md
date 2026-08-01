# Reference observation: OBS-0030

- Subject: Hermes remote OSC52 TMUX/STY passthrough query behavior
- Task: HAD-030
- Reference checkout: `/tmp/hades-hermes-ref-X3bLd0`
- Source commit: `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Capture: direct PTY at 120x40, synthetic `SSH_TTY`, one synthetic `TMUX` or
  `STY` marker per fresh process, synthetic `xclip`, and raw OSC52/DA1 bytes
- Probe: `scripts/probe_hermes_osc52_multiplexer.py`

Hermes wrapped the bare OSC52 query according to the environment marker. With
`TMUX`, Ctrl+V produced:

```text
ESC P tmux; ESC ESC ] 52 ; c ; ? BEL ESC \\
```

The exact bytes are recorded in the fixture. With `STY`, Ctrl+V produced:

```text
ESC P ESC ] 52 ; c ; ? BEL ESC \\
```

In this direct-PTY model, a raw BEL-terminated OSC52 response supplied after
either wrapped query was consumed before native xclip. The decoded payload
preserved the internal spaces and line break while removing its trailing
newlines. When no OSC52 response was supplied, answering the observed two DA1
barriers led to `xclip -selection clipboard -out`; the native payload's one
trailing newline was removed.

All four controls preserved the draft, reached ready without the busy interrupt
marker, did not submit an agent turn, and cleaned up after the bounded probe.
The fixture records the exact Ctrl+V, wrapper, response, DA1, provider, and
output markers.

## Model boundary

The probe sets environment markers and writes bytes directly to Hermes' PTY. It
does not start a live tmux or GNU Screen daemon, configure an outer terminal,
or prove forwarding through a real multiplexer. A response observed here is
therefore a direct raw-response model for the wrapper boundary, not complete
live multiplexer parity.

Image/path payloads, gateway behavior, delayed or oversized responses, and
concurrent input remain unobserved.

## Evidence

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0030-hermes-osc52-multiplexer-passthrough.json)
- [Direct PTY probe](../../../scripts/probe_hermes_osc52_multiplexer.py)
- [Bare SSH_TTY comparison](OBS-0024-hermes-osc52-clipboard-2026-08-01.md)
- [Task ledger](../../../.hades/tasks.json)
