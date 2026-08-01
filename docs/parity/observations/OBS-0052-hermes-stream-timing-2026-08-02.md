# Hermes reference observation: OBS-0052

- Subject: incremental provider deltas and pre-completion cancellation
- Reference: Hermes Agent 0.19.1, display build 2026.7.30
- Source commit: `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Terminal: fresh 120x40 direct PTYs
- Capture: deterministic loopback HTTP/SSE server with separated writes and a
  bounded release gate
- Task: HAD-056
- Fixture: `tests/fixtures/parity/OBS-0052-hermes-stream-timing.json`
- Probe: `scripts/probe_hermes_stream_timing.py`

## Observed boundary

In the delayed-delta case, Hermes sent the normalized authenticated
OpenAI-compatible chat request with `stream: true`, then rendered the first
assistant delta before the probe released the delayed second delta. After the
second release, the second marker became visible, the surface returned to
`ready`, and the bounded session exited cleanly.

In the cancellation case, Ctrl+C after the first delta and before the delayed
second release preserved the first delta, showed the interrupted surface, and
returned Hermes to `ready`. The second marker did not become visible. The
server observed a broken pipe while finishing the released response, which is
evidence that the provider connection closed, but the exact byte-level cutoff
is not claimed.

The completed case also produced two subsequent normalized chat requests after
the first streamed request. Their purpose was not isolated and remains
unknown; this observation does not label them retries, summaries, or tool
turns.

## Boundaries

The measured release gap and PTY observation delays are fixture-specific and
do not define universal Hermes timing, timeout, or cancellation constants.
This is reference evidence only. Hades still needs a genuinely incremental
transport and socket-cancellation implementation; retries, tools, malformed
streams, non-loopback providers, HTTPS, credentials, and persistence remain
outside this observation.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0052-hermes-stream-timing.json)
- [Repeatable direct-PTY/delayed-server probe](../../../scripts/probe_hermes_stream_timing.py)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
