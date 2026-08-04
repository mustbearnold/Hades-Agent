# Hermes reference observation: OBS-0046

- Subject: Full setup provider selection to first model-name prompt
- Reference: pinned Hermes checkout at `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Version: Hermes Agent 0.19.1 (2026.7.30)
- Terminal: fresh 120x40 direct PTY with an ANSI screen model
- Task: HAD-047
- Fixture: `tests/fixtures/parity/OBS-0046-hermes-provider-selection.json`
- Probe: `scripts/probe_hermes_full_setup_provider_selection.py`

The probe starts from the sanitized configured loopback provider used by
OBS-0044, opens `/setup`, selects Full setup through the observed `j` + Enter
path, and submits one Enter on the active `palette-loopback` provider row. It
then records the first post-selection surface and immediately cancels without
entering a model name or any provider credential.

## Observed boundary

The provider menu remains visible with the dynamic provider inventory and the
active loopback/model row. The first stable continuation marker is:

`Model name [palette-model]:`

The screen delta can retain the suffix `endpoint.` from the shorter prompt
overwriting the previous Custom endpoint row. This is recorded as a redraw
artifact, not as submitted input. Three fresh bounded captures agreed on the
prompt marker, the config-byte change, and clean Ctrl+C cleanup.

## Persistence and cleanup

Submitting the active provider row changes `config.yaml` bytes before the
model-name prompt is answered. The exact config delta is intentionally not
captured; no model name, endpoint, API key, secret, OAuth action, save action,
model request, or network-dependent behavior is entered. A timestamped config
backup was observed in each capture; `.hermes_history` and `.update_check`
appeared as timing-dependent artifact classes.

## Boundaries

Model-name validation and default acceptance, the exact persisted config
delta, custom endpoint entry, API keys, secrets, OAuth, model discovery, model
selection, save behavior, network behavior, and later Full setup sections
remain unobserved.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0046-hermes-provider-selection.json)
- [Direct-PTY probe](../../../scripts/probe_hermes_full_setup_provider_selection.py)
- [Earlier provider-menu observation](OBS-0044-hermes-full-setup-provider-menu-2026-08-01.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
