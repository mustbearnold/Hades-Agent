# Hermes reference observation: OBS-0069

- Subject: standalone `hermes setup` first-run entry and cancellation boundary
- Reference: pinned Hermes checkout at `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Version: Hermes Agent 0.19.1 (2026.7.30)
- Terminal: fresh 120x40 direct PTY with normalized stable markers
- Task: HAD-074
- Fixture: `tests/fixtures/parity/OBS-0069-hermes-standalone-setup.json`
- Probe: `scripts/probe_hermes_standalone_setup.py`

The standalone command was invoked as `hermes setup` in a fresh synthetic home
with no config, provider endpoint, credentials, OAuth action, external network,
provider value, or platform selection.

## First-run entry

Hermes first enters a curses-style setup choice surface with the `Hermes Agent
Setup Wizard` banner, the Quick Setup/Full setup/Blank Slate choices, and the
`ESC cancel` control. The PTY is in non-canonical, non-echo mode and the
alternate screen is active.

Pressing Escape leaves that surface and returns to a numbered fallback prompt
with `Enter for default (1)`, `Ctrl+C to exit`, and `Select [1-3] (1):`. The
terminal is canonical with echo restored on this fallback surface. No setup
choice is submitted.

## Bounded cancellation

Ctrl+C from the numbered fallback exits the standalone command with status 1,
leaves the alternate screen, restores canonical input and echo, and leaves the
config absent and unchanged. One normalized non-contract artifact class was
observed; it is retained as an artifact class only and is not promoted to a
product contract.

This is a first-entry observation, not a claim about direct Ctrl+C from the
initial curses surface or any selected setup path.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0069-hermes-standalone-setup.json)
- [Direct-PTY probe](../../../scripts/probe_hermes_standalone_setup.py)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
