# Hades implementation observation: OBS-0070

- Subject: standalone `hades setup` first-run entry and cancellation boundary
- Reference contract: [OBS-0069](OBS-0069-hermes-standalone-setup-2026-08-02.md)
- Binary: current debug Hades CLI under direct PTY
- Terminal: 120x40
- Task: HAD-075
- Fixture: `tests/fixtures/parity/OBS-0070-hades-standalone-setup.json`
- Replay: `scripts/replay_standalone_setup.py`

Hades now exposes a standalone `hades setup` command. It prints the observed
setup banner, enters an alternate-screen choice surface with the Quick
Setup/Full setup/Blank Slate choices, and preserves the raw terminal boundary.

Escape leaves the alternate screen and renders the numbered fallback prompt.
Ctrl+C from that canonical fallback exits with status 1 and leaves canonical
input and echo restored. The replay starts without a provider or config and
does not write config, start a provider, enter credentials, invoke OAuth, or
select a setup path.

The command intentionally stops at this reference-backed entry boundary.
Selected setup paths, persistence, provider/model configuration, credentials,
OAuth, and direct Ctrl+C from the initial curses surface remain unknown or
unimplemented.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0070-hades-standalone-setup.json)
- [Direct-PTY replay](../../../scripts/replay_standalone_setup.py)
- [Hermes reference observation](OBS-0069-hermes-standalone-setup-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
