# Hades implementation observation: OBS-0092

- Subject: successful conversation context and failed-turn isolation
- Reference boundary: [OBS-0054](OBS-0054-hermes-provider-errors-2026-08-02.md)
- Hades source baseline: `602050fac4db7073a5c4ee447abb70400ed35456`
- Capture: one fresh 120x40 direct PTY after `hades setup --local`, with a
  deterministic loopback HTTP/SSE server
- Fixture: `tests/fixtures/parity/OBS-0092-hades-conversation-context.json`
- Replay: `scripts/replay_conversation_context.py`
- Task: HAD-097

## Observed Hades contract

The replay completed two successful turns before starting a third request. The
second request contained exactly one provider system prompt, the first user
prompt, the first completed assistant answer, and the second user prompt. The
bootstrap display message was not sent to the provider.

The third request received a partial assistant delta and then ended without
`[DONE]`. Hades kept that partial answer visible with a provider error, made no
automatic request, and accepted a new prompt only after the user edited and
submitted it. The fourth request retained the two successful turns but omitted
both the failed prompt and its partial assistant diagnostic text.

All four requests used `vertical-model`, streamed over the loopback endpoint,
sent no authorization header, and exited with code 0 after leaving the
alternate screen and restoring canonical input and echo. Setup wrote only the
sanitized Hades sidecar and did not create or mutate Hermes `config.yaml`.

## Safety and parity boundary

The provider context is owned by a typed turn lifecycle rather than reconstructed
from display strings. Completed turns become model context; failed, cancelled,
or incomplete turns remain visible for diagnosis but are not treated as model
history. This preserves the safer explicit-follow-up behavior from HAD-096 and
does not reproduce Hermes failure behavior or impose a Rust performance ceiling.

The replay does not claim process-restart persistence, session switching,
tool-call or multimodal message encoding, context-window budgeting, concurrent
submissions, cancellation races, or external-provider behavior.

## Evidence

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0092-hades-conversation-context.json)
- [Direct PTY replay](../../../scripts/replay_conversation_context.py)
- [Provider recovery boundary](OBS-0091-hades-provider-failure-recovery-2026-08-02.md)
- [Task ledger](../../../.hades/tasks.json)
