# Hermes reference observation: OBS-0108

- Subject: bounded multi-turn provider request boundary
- Reference: Hermes Agent 0.19.1, display build 2026.7.30
- Source commit: `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Terminal: fresh 120x40 direct PTY
- Capture: deterministic loopback HTTP/SSE server with protocol-appropriate
  streaming and non-streaming responses
- Task: HAD-112
- Fixture: `tests/fixtures/parity/OBS-0108-hermes-multi-turn-provider.json`
- Probe: `scripts/probe_hermes_multi_turn_provider.py`

## Verified boundary

In one configured synthetic Hermes process, two ordinary prompts produced two
streaming `POST /v1/chat/completions` requests. The first request contained a
system message and the first user message. The second contained the system
message, the first user/assistant turn, and the second user message, proving
that a completed turn is included in the next request at this bounded seam.

Both streaming requests used the selected model, `stream: true`, stream
options, and a structural tool schema with 31 tool definitions. The probe
records tool names and parameter-shape counts without copying parameter values
or executing any tool.

Hermes also issued one auxiliary non-stream request with the normalized body
shape `messages`, `model`, and `temperature`, and accepted a protocol-correct
JSON response. Its purpose is not classified as a retry, title request, or
summary request. The probe deliberately reports the shape and count without
turning that observation into a Hades requirement.

The direct PTY replay rendered both synthetic answers and exited cleanly after
bounded Ctrl+C cleanup. No external network, OAuth flow, provider action,
credential, or private runtime state was used.

## Boundaries

This is reference evidence only. It does not establish tool-call execution,
tool response encoding, retries, discovery semantics, token accounting,
persistence, cancellation races, or behavior beyond two ordinary completed
turns. Hades must not reproduce Hermes defects or auxiliary behavior without a
separate safe implementation contract.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0108-hermes-multi-turn-provider.json)
- [Repeatable direct-PTY/provider probe](../../../scripts/probe_hermes_multi_turn_provider.py)
- [Reference first-turn boundary](OBS-0050-hermes-local-provider-stream-2026-08-01.md)
- [Hades context boundary](OBS-0092-hades-conversation-context-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
