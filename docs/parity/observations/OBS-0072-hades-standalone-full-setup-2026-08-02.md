# Hades implementation observation: OBS-0072

- Subject: standalone `hades setup` Full setup continuation and cancellation
- Reference contract: [OBS-0071](OBS-0071-hermes-standalone-full-setup-2026-08-02.md)
- Binary: current debug Hades CLI under direct PTY
- Terminal: 120x40
- Task: HAD-077
- Fixture: `tests/fixtures/parity/OBS-0072-hades-standalone-full-setup.json`
- Replay: `scripts/replay_standalone_full_setup.py`

Hades now carries the standalone command through the observed Full setup
continuation. The replay starts with a fresh synthetic home and no provider
environment, sends the observed `j`, Enter sequence, and never submits a
provider, endpoint, model, credential, OAuth, or backend value.

## Verified continuation

Selecting Full setup creates a non-secret baseline `config.yaml` marker in the
synthetic `HERMES_HOME` and renders the stable Configuration Location and
Inference Provider landmarks. The config assertion checks only the bounded
marker and does not retain its contents or path.

## Verified cancellation chain

The first Ctrl+C at the provider boundary moves to the Terminal Backend
surface while raw input remains active. The second Ctrl+C leaves that surface
for the numbered fallback and restores canonical input and echo. The third
Ctrl+C exits with status 1, leaves the alternate screen, and preserves terminal
cleanup. No provider worker starts and no credential-like value is entered.

The initial Escape-to-choice-fallback route remains separately covered by
OBS-0070. Direct Ctrl+C from the initial curses surface and all later setup
selection remain outside this claim.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0072-hades-standalone-full-setup.json)
- [Direct-PTY replay](../../../scripts/replay_standalone_full_setup.py)
- [Hermes reference observation](OBS-0071-hermes-standalone-full-setup-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
