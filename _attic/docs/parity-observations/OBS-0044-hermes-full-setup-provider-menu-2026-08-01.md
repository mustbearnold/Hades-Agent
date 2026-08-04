# Hermes reference observation: OBS-0044

- Subject: Full setup Inference Provider pre-selection boundary
- Reference: pinned Hermes checkout at `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Version: Hermes Agent 0.19.1 (2026.7.30)
- Terminal: fresh 120x40 direct PTY with an ANSI screen model
- Task: HAD-045
- Fixture: `tests/fixtures/parity/OBS-0044-hermes-full-setup-provider-menu.json`
- Probe: `scripts/probe_hermes_full_setup_provider.py`

The probe starts from the sanitized configured loopback provider used by
OBS-0042, opens `/setup`, selects Full setup through the observed `j` + Enter
path, and stops at the first provider picker. It sends one reversible Down
navigation and then Ctrl+C; it never presses Enter in the provider picker.

## Observed surface

The stable 120x40 surface includes the Configuration Location and Inference
Provider headers, the current model and active provider lines, the provider
picker title, the visible `palette-loopback` / `palette-model` active row, the
Custom endpoint row, and the saved-custom-provider removal row. The visible
provider inventory is deliberately not treated as complete because the list
extends beyond the viewport and includes dynamic provider/group entries.

Across three fresh bounded captures, `config.yaml` remained byte-for-byte
unchanged, no provider selection was submitted, and Ctrl+C exited cleanly.
The timestamped `config.yaml.bak.*` artifact was observed each time. The
synthetic home also showed `.hermes_history` after cleanup, while `.update_check`
appeared in some runs; those files are recorded as timing-dependent artifact
classes, not as provider-selection side effects.

## Boundaries

Provider selection, grouped-provider navigation, custom endpoint entry, API
keys, OAuth, model discovery, model selection, persistence after a provider
action, network behavior, and later Full setup sections remain unobserved.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0044-hermes-full-setup-provider-menu.json)
- [Direct-PTY probe](../../../scripts/probe_hermes_full_setup_provider.py)
- [Earlier Full setup boundary](OBS-0042-hermes-full-setup-continuation-2026-08-01.md)
- [Task ledger](../../../.hades/tasks.json)
