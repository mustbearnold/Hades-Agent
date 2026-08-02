# Hades implementation observation: OBS-0091

- Subject: safe local-provider failure recovery and explicit follow-up
- Reference boundary: [OBS-0054](OBS-0054-hermes-provider-errors-2026-08-02.md)
- Hades source baseline: `57c1a88ec8c2e8eb39f40361c21bccdd368cfb73`
- Capture: fresh 120x40 direct PTYs after `hades setup --local`, with a
  deterministic loopback HTTP/SSE server
- Fixture: `tests/fixtures/parity/OBS-0091-hades-provider-failure-recovery.json`
- Replay: `scripts/replay_provider_recovery.py`

## Observed Hades contract

Hades handles three local failure classes—HTTP 500, malformed SSE, and an
incomplete stream—by showing a bounded `Provider error:` notice and returning
to the Ready interaction state. No failure caused an automatic second request.

For the incomplete stream, the already-rendered partial assistant text remains
visible as diagnostic context, but it is not treated as a completed answer.
Typing a new prompt clears the notice. Enter then creates exactly one explicit
follow-up request, which streams `Recovered answer.` to completion using the
configured loopback model.

Each case used the model `vertical-model`, sent exactly two local streaming
requests with `system` and `user` roles, sent no authorization header, and
exited with code 0 after leaving the alternate screen and restoring canonical
input and echo. The replay also verified that setup wrote only the sanitized
Hades sidecar and did not create or mutate Hermes `config.yaml`.

## Safety and parity boundary

The pinned Hermes failure observation records repeated requests and a busy
surface in bounded failure windows. Hades does not intentionally reproduce
that unsafe or ambiguous behavior. The Hades contract is an explicit,
user-driven follow-up with visible failure state and no automatic retry.

The replay does not claim behavior for external providers, authentication,
timeouts, tool failures, concurrent input, session restart after failure, or
backoff policy.

## Evidence

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0091-hades-provider-failure-recovery.json)
- [Direct PTY replay](../../../scripts/replay_provider_recovery.py)
- [Hermes reference boundary](OBS-0054-hermes-provider-errors-2026-08-02.md)
- [Task ledger](../../../.hades/tasks.json)
