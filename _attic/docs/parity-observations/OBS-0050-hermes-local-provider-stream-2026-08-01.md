# Hermes reference observation: OBS-0050

- Subject: first local-provider request and response-stream boundary
- Reference: Hermes Agent 0.19.1, display build 2026.7.30
- Source commit: `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Terminal: fresh 120x40 direct PTY
- Capture: deterministic loopback HTTP/SSE server with sanitized request recording
- Task: HAD-052
- Fixture: `tests/fixtures/parity/OBS-0050-hermes-local-provider-stream.json`
- Probe: `scripts/probe_hermes_local_provider_stream.py`

## Verified boundary

With a custom provider pointed at the probe-owned loopback endpoint, Hermes
waits for the actual `ready │` composer footer before accepting input. After a
sanitized prompt and Enter, its first chat request is an authenticated
OpenAI-compatible `POST /v1/chat/completions` with JSON content, the selected
model, system and user messages, `stream: true`, stream options, and tools.

The deterministic server returns three SSE chunks and a `[DONE]` landmark. The
TUI renders `Synthetic loopback response.`, exposes the normal interrupt
control, and returns to `ready`. Ctrl+C then exits cleanly from the bounded
probe session.

The recorder also saw ten normalized discovery requests and two subsequent
chat requests. Their purpose was not isolated, so the fixture records the
counts without calling them retries, summaries, or tool turns.

## Boundaries

This is reference evidence, not Hades runtime behavior. Hades does not yet
claim a real provider adapter or model response path. Tool calls, malformed or
delayed streams, cancellation during an active stream, native Ollama
`/api/chat`, provider errors, persistence, credentials, OAuth, and external
providers remain unknown.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0050-hermes-local-provider-stream.json)
- [Repeatable direct-PTY/local-server probe](../../../scripts/probe_hermes_local_provider_stream.py)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
