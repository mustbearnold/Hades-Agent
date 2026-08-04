# Reference observation: OBS-0032

- Subject: Hermes remote OSC52 timing and bounded decoded-payload behavior
- Task: HAD-032
- Reference checkout: `/tmp/hades-hermes-ref-X3bLd0`
- Source commit: `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Capture: direct PTY at 120x40, synthetic `SSH_TTY`, synthetic `xclip`, no
  TMUX/STY markers, and raw OSC52/DA1 bytes
- Probe: `scripts/probe_hermes_osc52_timing_limits.py`

Hermes' pinned `readOsc52Clipboard` implementation races its OSC52 response
against a 500 ms timer, then flushes the terminal querier with a DA1 sentinel.
The direct-PTY probe supplied a usable BEL-terminated response at a 100 ms
target delay and observed the OSC52 text winning before the native provider.
When the same kind of response was supplied only after the timeout DA1
sentinel, Hermes used `xclip -selection clipboard -out`; the late OSC52 text
did not appear in the composer.

The successful timing controls preserved the draft, removed the two trailing
newlines from the OSC52 decoded text, reached ready without the busy interrupt
marker, did not submit an agent turn, and cleaned up after Ctrl+C. The
reference emitted the bare query `ESC ] 52 ; c ; ? BEL`, and the probe answered
two observed DA1 barriers with `ESC [ ? 62 c`.

Two deterministic immediate-response size controls also succeeded. Hermes
consumed a 256 KiB decoded payload whose response occupied 349,536 bytes, and
a 512 KiB decoded payload whose response occupied 699,060 bytes. Both had
stable start/end markers and recorded SHA-256 hashes in the sanitized fixture.
The generated runtime report records representative transport timings; those
measurements are diagnostic, not product contracts.

## Model boundary

This observation covers only the supplied direct-PTY controls: a 100 ms
pre-timeout response, a response delivered after the timeout flush, and
immediate 256 KiB and 512 KiB decoded payloads. It does not establish a
universal timeout or maximum-size limit, nor behavior for larger payloads,
other response delays, wall-clock jitter, multiplexers, ST termination,
attachments, gateway behavior, or concurrent input. It is reference research
only and does not claim Hades implementation parity.
