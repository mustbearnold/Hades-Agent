# Hermes reference observation: OBS-0066

- Subject: timing the delayed `/help` to Setup Required transition
- Reference: pinned Hermes checkout at `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Version: Hermes Agent 0.19.1 (2026.7.30)
- Terminal: fresh 120x40 direct PTYs with synthetic homes
- Task: HAD-071
- Fixture: `tests/fixtures/parity/OBS-0066-hermes-help-setup-timing.json`
- Probe: `scripts/probe_hermes_help_setup_timing.py`

Two fresh no-provider runs waited for the stable `starting agent` surface,
submitted `/help`, and sampled the rendered surface until Setup Required
appeared. The startup surface was first stable at 2188 ms and 2084 ms after
process start. Setup Required appeared at 10550 ms and 10336 ms after process
start, or 8344 ms and 8236 ms after `/help` submission.

Both runs retained the starting-agent marker while exposing `/model`, `/setup`,
and Ctrl+C on the setup-required surface. Neither changed the synthetic config
or entered a provider path. Two Ctrl+C presses exited with code 0, left the
alternate screen, and restored canonical input and echo. The samples describe
these bounded runs only; they do not establish a universal timing contract.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0066-hermes-help-setup-timing.json)
- [Timed direct-PTY probe](../../../scripts/probe_hermes_help_setup_timing.py)
- [Setup-required reconciliation](OBS-0065-hermes-setup-required-reconciliation-2026-08-02.md)
- [Bounded startup resolution](OBS-0064-hermes-unconfigured-resolution-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
