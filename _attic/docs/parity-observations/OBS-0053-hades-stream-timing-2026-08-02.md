# Hades implementation observation: OBS-0053

- Subject: incremental provider deltas and pre-completion cancellation
- Reference contract: [OBS-0052 Hermes delayed-delta boundary](OBS-0052-hermes-stream-timing-2026-08-02.md)
- Terminal: fresh 120x40 direct PTYs
- Capture: Hades debug binary with a probe-owned delayed loopback HTTP/SSE server
- Task: HAD-057
- Fixture: `tests/fixtures/parity/OBS-0053-hades-stream-timing.json`
- Replay: `scripts/replay_local_provider_timing.py`

## Verified implementation boundary

Hades now opens the local HTTP response as an incremental SSE stream. The
direct-PTY replay proves that `HADES_DELAY_FIRST` becomes visible before the
server releases `HADES_DELAY_SECOND`, and that the completed response returns
to `ready` before clean terminal restoration.

When Ctrl+C arrives after the first delta and before the second release, Hades
preserves the partial assistant response, renders the interrupted surface,
returns to `ready`, and exits cleanly after the second Ctrl+C. The worker’s
cancellation token causes the socket to close; the server observes a
`BrokenPipeError` while finishing the released response, and the second delta
does not render.

The provider crate retains the request and malformed/incomplete SSE guards,
while the CLI owns the cancellation token and receiver lifecycle. No API key
is configured in this replay.

## Boundaries

The probe establishes only the bounded loopback behavior covered by OBS-0052.
It does not claim retry semantics, tool execution, provider errors, HTTPS,
non-loopback providers, credentials, OAuth, persistence, or model discovery.
The exact cutoff between a server write, kernel buffering, parser delivery, and
socket-close detection remains timing-sensitive.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0053-hades-stream-timing.json)
- [Repeatable direct-PTY replay](../../../scripts/replay_local_provider_timing.py)
- [Provider transport](../../../crates/hades-provider/src/lib.rs)
- [CLI worker](../../../crates/hades-cli/src/main.rs)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
