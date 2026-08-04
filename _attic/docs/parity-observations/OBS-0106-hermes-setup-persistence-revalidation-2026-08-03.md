# Hermes reference revalidation: OBS-0106

- Subject: bounded Full setup persistence and config-shape boundaries
- Reference: pinned Hermes checkout at `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Version: Hermes Agent 0.19.1 (2026.7.30)
- Terminal: fresh 120x40 direct PTYs with redacted screen/config models
- Task: HAD-110
- Probes: `scripts/probe_hermes_provider_setup_persistence.py`, `scripts/probe_hermes_setup_config_shape.py`

The current pinned Hermes checkout revalidates the existing bounded setup
persistence contract. In a fresh synthetic home, entering Full setup, accepting
the displayed loopback provider and `palette-model` default changes config
before the terminal-backend picker. Cancelling at the highlighted `Keep current
(local)` backend does not add another config change. Accepting that backend
advances to the platform picker, changes config again, and a fresh process reads
the resulting state as ready.

The normalized config shape revalidation records the existing structural paths
at the backend and platform boundaries, including `_config_version`, model and
custom-provider containers, and the bounded `agent`, `display`, and
`session_reset` additions. It records no values or secrets. Backup/artifact
classes remain normalized, and the one unrelated artifact identity remains
unknown.

This evidence is sufficient to define a future non-secret Hades persistence
task, but not to invent provider credentials, OAuth, endpoint editing, model
discovery, or later platform behavior.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0106-hermes-setup-persistence-revalidation.json)
- [Persistence probe](../../../scripts/probe_hermes_provider_setup_persistence.py)
- [Config-shape probe](../../../scripts/probe_hermes_setup_config_shape.py)
- [Original persistence observation](OBS-0055-hermes-provider-setup-persistence-2026-08-02.md)
- [Original config-shape observation](OBS-0056-hermes-setup-config-shape-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
