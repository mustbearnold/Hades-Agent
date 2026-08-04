# Hades implementation observation: OBS-0057

- Subject: bounded setup platform-picker continuation
- Reference boundary: [OBS-0056](OBS-0056-hermes-setup-config-shape-2026-08-02.md)
- Task: HAD-061
- Fixture: `tests/fixtures/parity/OBS-0057-hades-setup-platform-picker.json`
- Replay: `scripts/replay_setup_terminal_backend.py` with the OBS-0057 contract

Hades now follows the captured setup sequence through the displayed active
loopback provider, the `palette-model` default, and the highlighted `Keep
current (local)` backend. Accepting that backend enters a typed in-memory
platform-picker surface.

The 120x40 replay renders the observed `Select platforms to configure:` title,
`SPACE toggle`, `ENTER confirm`, and `ESC cancel` controls, together with the
stable unconfigured Mattermost, Signal, and platform-status markers. Ctrl+C
from that surface exits through the existing terminal cleanup path.

This is deliberately a bounded transition. Platform toggling and confirmation,
config-file writes, credential handling, provider discovery, and later setup
pages are not implemented or claimed. The replay asserts no busy/provider
surface and no API-key/OAuth marker.

## Linked artifacts

- [Sanitized Hades fixture](../../../tests/fixtures/parity/OBS-0057-hades-setup-platform-picker.json)
- [Reference config-shape observation](OBS-0056-hermes-setup-config-shape-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
