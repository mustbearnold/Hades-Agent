# Hermes reference observation: OBS-0064

- Subject: bounded eventual resolution of no-provider startup
- Reference: pinned Hermes checkout at `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Version: Hermes Agent 0.19.1 (2026.7.30)
- Terminal: fresh 120x40 direct PTY with synthetic homes
- Task: HAD-068
- Fixture: `tests/fixtures/parity/OBS-0064-hermes-unconfigured-resolution.json`
- Probe: `scripts/probe_hermes_unconfigured_resolution.py`

Across three fresh cases, Hermes remained on the stable `starting agent`
surface for the full 15-second observation window. With no input, no ready
surface appeared and one Ctrl+C exited cleanly. After `/setup` or `/model` plus
Enter, the command remained visible, the status did not resolve, no setup wizard
or model picker appeared, no provider error was visible, and the synthetic
config stayed unchanged. Both command cases exited cleanly after two Ctrl+C
presses with the alternate screen left and the terminal restored.

This establishes a longer bounded startup boundary, not an eventual timeout or
dispatch contract. Hermes behavior after the observation window and any
configured setup/model route remain unknown.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0064-hermes-unconfigured-resolution.json)
- [Direct-PTY probe](../../../scripts/probe_hermes_unconfigured_resolution.py)
- [Setup/model startup observation](OBS-0063-hermes-unconfigured-setup-escape-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
