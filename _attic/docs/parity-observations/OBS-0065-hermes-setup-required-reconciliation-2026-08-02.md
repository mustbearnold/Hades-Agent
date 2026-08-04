# Hermes reference observation: OBS-0065

- Subject: reconciling `/help` setup-required behavior with the no-provider startup boundary
- Reference: pinned Hermes checkout at `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Version: Hermes Agent 0.19.1 (2026.7.30)
- Terminal: fresh 120x40 direct PTYs and tmux sessions
- Task: HAD-070
- Fixture: `tests/fixtures/parity/OBS-0065-hermes-setup-required-reconciliation.json`
- Probe: `scripts/probe_hermes_setup_required_reconciliation.py`

The older OBS-0001 setup-required observation is reproducible, but its
meaning is narrower than “all slash commands open setup.” In four fresh cases,
`/help` plus Enter transitioned from `starting agent` to `setup required`
within the 15-second bounded window. The result held both when `/help` was sent
after the first banner marker and when it was sent after repeated stable
starting-agent samples, in both direct PTY and tmux capture.

The setup-required surface exposed `/model`, `/setup`, and Ctrl+C, changed no
synthetic config, and exited cleanly after two Ctrl+C presses. By contrast,
OBS-0063 and OBS-0064 sent `/setup` or `/model` directly during the same
unconfigured startup boundary and observed no setup/model surface. `/help` is
therefore the next distinct Hades parity seam; no setup behavior is inferred
for the other commands.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0065-hermes-setup-required-reconciliation.json)
- [Direct-PTY/tmux probe](../../../scripts/probe_hermes_setup_required_reconciliation.py)
- [Original setup-required observation](OBS-0001-hermes-main-2026-08-01.md)
- [Unconfigured command observation](OBS-0063-hermes-unconfigured-setup-escape-2026-08-02.md)
- [Bounded resolution observation](OBS-0064-hermes-unconfigured-resolution-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
