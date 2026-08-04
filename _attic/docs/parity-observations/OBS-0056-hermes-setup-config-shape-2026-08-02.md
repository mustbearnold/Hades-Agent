# Hermes reference observation: OBS-0056

- Subject: normalized setup config shape and platform-picker continuation
- Reference: pinned Hermes checkout at `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Version: Hermes Agent 0.19.1 (2026.7.30)
- Terminal: fresh 120x40 direct PTY with a redacted ANSI screen model
- Task: HAD-060
- Fixture: `tests/fixtures/parity/OBS-0056-hermes-setup-config-shape.json`
- Probe: `scripts/probe_hermes_setup_config_shape.py`

This capture repeats the safe OBS-0055 path in a fresh synthetic home. It
accepts the active synthetic loopback provider, the displayed `palette-model`
default, and the highlighted `Keep current (local)` backend. It stops at the
platform picker and sends Ctrl+C without selecting a platform. No endpoint,
credential, OAuth action, external network, or platform-specific setup is
entered.

## Config shape boundaries

The initial synthetic config contains `model` and `custom_providers` mappings,
with string fields for provider, model, URL, name, and API-key slots. The
probe records those key paths only; it never records their values.

Accepting the displayed model default changes the config and adds a top-level
`_config_version` integer. Accepting `Keep current (local)` changes it again
and adds the observed `agent.max_turns`, `display.tool_progress`, and
`session_reset.mode` paths. Cancelling at the platform picker does not add a
further change. The bounded byte counts were 261 before setup, 2,182 at the
terminal-backend picker, and 2,264 at the platform picker in this sanitized
capture.

## Platform continuation and readback

The next surface is `Select platforms to configure:` with `SPACE toggle`,
`ENTER confirm`, `ESC cancel`, and unconfigured Mattermost/Signal rows visible.
Ctrl+C exits cleanly. A fresh Hermes process using the resulting synthetic
home reaches `ready`, proving that this bounded config shape is loadable across
a process boundary.

The setup path also creates normalized artifact classes before the backend
picker: `.hermes_history`, `.update_check`, `config.yaml.bak.<timestamp>`, and
one non-contract `<other-file>` class. No additional artifact class appears
when the backend selection reaches platform setup.

## Unknowns and safety boundary

Exact scalar values, YAML ordering/formatting, backup contents, and the
identity of the non-contract artifact remain unknown. The observed `api_key`
paths are structural only and do not authorize Hades to read or persist
credentials. Platform selection, endpoint editing, provider credentials,
OAuth, model discovery, backend-specific setup, validation errors, and later
wizard continuation remain unobserved.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0056-hermes-setup-config-shape.json)
- [Direct-PTY probe](../../../scripts/probe_hermes_setup_config_shape.py)
- [Prior persistence observation](OBS-0055-hermes-provider-setup-persistence-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
