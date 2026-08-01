# OBS-0051: Hades local-provider worker boundary

- Observation: `OBS-0051`
- Reference boundary: `OBS-0050`
- Product: Hades Agent workspace
- Capture: fresh debug binary in a direct 120x40 PTY
- Provider: probe-owned `127.0.0.1` HTTP/SSE server only
- Contract: `tests/fixtures/parity/OBS-0051-hades-local-provider-stream.json`
- Replay: `scripts/replay_local_provider.py`

## Result

The opt-in CLI worker accepted a sanitized prompt, sent one `POST
/v1/chat/completions` request to the loopback server, translated the bounded
SSE response into reducer events, rendered `Synthetic loopback response.`,
returned to `ready`, and exited cleanly. The normalized request retained the
OpenAI-compatible top-level keys, `palette-model`, `stream: true`, and
system/user message roles. The replay also verified a visible error when
`HADES_PROVIDER_BASE_URL` is absent and a two-step Ctrl+C cleanup while the
provider response is held open.

The server was bound to `127.0.0.1` and no API key was supplied. Prompt text,
paths, session IDs, timestamps, raw ANSI bytes, and any private environment
state are excluded from the fixture.

## Deliberate unknowns

The current transport buffers the complete HTTP response before returning its
parsed event vector, so this observation does not claim per-token redraw
timing or socket-level cancellation. Retries, malformed/delayed responses,
tool execution, HTTPS, non-loopback providers, OAuth, persistence, and model
discovery remain separate work. The system prompt and empty tool list are
adapter choices, not claims about Hermes hidden prompt/tool behavior.
