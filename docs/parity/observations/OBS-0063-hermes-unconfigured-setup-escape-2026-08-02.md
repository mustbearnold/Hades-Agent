# Hermes reference observation: OBS-0063

- Subject: `/setup` and `/model` during unconfigured startup
- Reference: pinned Hermes checkout at `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Version: Hermes Agent 0.19.1 (2026.7.30)
- Terminal: fresh 120x40 direct PTY with synthetic homes
- Task: HAD-067
- Fixture: `tests/fixtures/parity/OBS-0063-hermes-unconfigured-setup-escape.json`
- Probe: `scripts/probe_hermes_unconfigured_setup_escape.py`

Hermes remains on the stable `starting agent` surface when `/setup` or
`/model` is typed and submitted during a fresh no-provider startup. During the
three-second bounded observation, the command remains visible, but no setup
wizard or model picker appears, no ready/provider-error transition is visible,
and the synthetic config remains absent and unchanged.

Both cases exit cleanly after two Ctrl+C presses with the alternate screen left
and the terminal restored. This captures the startup boundary only; it does not
claim whether either command is eventually dispatched if startup resolves.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0063-hermes-unconfigured-setup-escape.json)
- [Direct-PTY probe](../../../scripts/probe_hermes_unconfigured_setup_escape.py)
- [Unconfigured startup observation](OBS-0059-hermes-unconfigured-startup-2026-08-02.md)
- [Unconfigured input observation](OBS-0061-hermes-unconfigured-input-queue-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
