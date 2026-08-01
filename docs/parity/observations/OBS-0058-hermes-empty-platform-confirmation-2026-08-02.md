# Hermes reference observation: OBS-0058

- Subject: empty-platform confirmation boundary
- Reference: pinned Hermes checkout at `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Version: Hermes Agent 0.19.1 (2026.7.30)
- Terminal: fresh 120x40 direct PTY with a redacted ANSI screen model
- Task: HAD-062
- Fixture: `tests/fixtures/parity/OBS-0058-hermes-empty-platform-confirmation.json`
- Probe: `scripts/probe_hermes_empty_platform_confirmation.py`

This capture repeats the safe OBS-0056 setup path, accepts the displayed
synthetic loopback provider, `palette-model` default, and `Keep current (local)`
backend, then presses Enter while every platform remains unselected. It does
not toggle a platform, enter credentials, invoke OAuth, select a later setup
value, or access external network.

## Bounded outcome

Hermes remains on the same `Select platforms to configure:` surface throughout
the finite observation window. The stable title, controls, Mattermost/Signal
rows, and `(not configured)` markers remain visible. No ready marker, provider
error, or later setup surface appears, and the process remains alive until the
probe sends Ctrl+C.

The normalized config shape remains 2,264 bytes before and after the empty
confirmation. No new artifact class appears. Ctrl+C exits cleanly, and a fresh
Hermes process using the resulting synthetic home reaches ready.

This is a bounded no-op observation, not a claim about whether Hermes can
eventually complete setup with zero platforms or what happens after a platform
is selected.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0058-hermes-empty-platform-confirmation.json)
- [Direct-PTY probe](../../../scripts/probe_hermes_empty_platform_confirmation.py)
- [Prior config-shape observation](OBS-0056-hermes-setup-config-shape-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
