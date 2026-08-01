# Hermes reference observation: OBS-0073

- Subject: standalone `hermes setup` Full setup terminal-backend and platform-picker boundary
- Reference: pinned Hermes checkout at `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Version: Hermes Agent 0.19.1 (2026.7.30)
- Terminal: fresh 120x40 direct PTY with an ANSI screen model
- Task: HAD-078
- Fixture: `tests/fixtures/parity/OBS-0073-hermes-standalone-terminal-platform.json`
- Probe: `scripts/probe_hermes_standalone_terminal_platform.py`

The standalone command was invoked as `hermes setup` in a fresh synthetic home
with provider-related environment removed and no configuration. The probe moved
from Quick Setup to Full setup with `j`, submitted Full setup, and sent Ctrl+C
at the unconfigured Inference Provider surface. It accepted only the highlighted
`Keep current (local)` terminal backend, then stopped at platform selection.
No platform was toggled or confirmed, and no credentials, OAuth action, model,
endpoint, or external network was exercised.

## Verified continuation

The first Ctrl+C skips the unconfigured provider and opens the terminal-backend
curses surface with these stable rows:

- `Select terminal backend:`
- the seven displayed backend alternatives
- `Keep current (local)`

The terminal-backend surface is non-canonical and non-echo. Enter on the
highlighted `Keep current (local)` creates or updates a normalized config and
opens the platform picker. The picker shows `Select platforms to configure:`
with `SPACE toggle`, `ENTER confirm`, `ESC cancel`, and unconfigured Mattermost,
Signal, and other platform rows.

The observed config shape at the backend surface contains only `_config_version`.
At the platform picker it additionally contains normalized `agent.max_turns`,
`display.tool_progress`, and `session_reset.mode` paths. Cancelling the platform
picker does not change that shape, and no `.env` secrets file is created.

## Cancellation and process boundary

The first platform-picker Ctrl+C restores canonical input and echo, leaves the
alternate screen, and advances to `No platforms selected. Run 'hermes setup
gateway' later to configure.` followed by `Hermes Tool Configuration`. The
setup process remains alive there. A second Ctrl+C exits with status 130. The
terminal remains canonical with echo enabled after cleanup. A bounded fresh
`hermes --tui` process using the resulting synthetic home shows the normal
`Hermes Agent`/`starting agent` surface; it does not reach `Setup Required` in
the captured window.

## Unknowns and safety boundary

Provider inventory, endpoint/model values, credentials, OAuth, network behavior,
alternative terminal backends, platform selection, platform-specific setup,
tool selection/configuration after the observed heading, validation errors, later
wizard sections, successful-save behavior, exact config values, and direct
initial-surface Ctrl+C remain unknown. The normalized config shape is structural
evidence only; no secret value was read into the report.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0073-hermes-standalone-terminal-platform.json)
- [Direct-PTY probe](../../../scripts/probe_hermes_standalone_terminal_platform.py)
- [Prior standalone Full observation](OBS-0071-hermes-standalone-full-setup-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
