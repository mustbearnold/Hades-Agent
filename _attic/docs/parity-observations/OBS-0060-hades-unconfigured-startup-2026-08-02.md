# Hades implementation observation: OBS-0060

- Subject: Hades unconfigured startup boundary
- Reference contract: [OBS-0059](OBS-0059-hermes-unconfigured-startup-2026-08-02.md)
- Task: HAD-064
- Fixture: `tests/fixtures/parity/OBS-0060-hades-unconfigured-startup.json`
- Replay: `scripts/replay_unconfigured_startup.py`

Hades now selects a typed `StartupState::Unconfigured` when the real CLI has no
`HADES_PROVIDER_BASE_URL`. The state does not accept prompt input or start a
provider worker. At 120x40 it renders the captured startup shell with
`glm-5.2 · Nous Research` and a `starting agent…` footer, without a ready footer
or prompt placeholder.

Both `hades` and `hades tui` were replayed in fresh synthetic homes. Each
entered raw mode and the alternate screen, reached the same unconfigured
markers, exited with Ctrl+C and status zero, left the alternate screen, and
restored canonical input and echo. The replay is deliberately bounded: setup,
provider persistence, credentials, OAuth, eventual startup resolution, and
configured prompt behavior remain future work.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0060-hades-unconfigured-startup.json)
- [Direct-PTY replay](../../../scripts/replay_unconfigured_startup.py)
- [Hermes reference observation](OBS-0059-hermes-unconfigured-startup-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
