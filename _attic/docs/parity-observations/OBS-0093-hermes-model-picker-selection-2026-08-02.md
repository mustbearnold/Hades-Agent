# Reference observation: OBS-0093

- Subject: Hermes model-picker selection boundary
- Reference: Hermes TUI 0.19.1 / `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Terminal: fresh 120x40 direct PTY with a rendered ANSI screen model
- Capture: synthetic custom loopback provider, no-selection control, bounded
  Enter on `palette-model`, and fresh-process readback
- Task: HAD-098
- Fixture: `tests/fixtures/parity/OBS-0093-hermes-model-picker-selection.json`
- Probe: `scripts/probe_hermes_model_picker_selection.py`

## Observed boundary

The no-selection control reached the existing model-stage landmarks without
selecting a row. Hermes then received one additional bounded Enter on the
visible `palette-model` row. The resulting rendered screen exposed the status
marker `model → palette-model`, which is evidence of a transient selection
event in that process.

The selection control did not change the normalized config bytes relative to
the no-selection control. A fresh process still showed `Current:
palette-model` and the same model-stage catalog. Because `palette-model` was
already current before the selection, this does not prove persistence or a
changed effective provider model. A later isolated chat request with a
distinct model is required for that claim.

The local fixture recorded bounded model discovery/detail calls on
`/api/v1/models`, `/v1/models`, `/v1/models/palette-model`, and `/api/show`.
The generated run observed repeated metadata requests after the selection
input. That is preserved as reference diagnostic evidence only; it is not a
Hades behavior requirement, especially where it may represent a retry or
failure boundary.

## Safety and parity boundary

No real credentials, external network, host clipboard, or live provider were
used. Synthetic authorization presence is recorded only as a boolean and no
credential value is emitted. Hermes startup normalized the synthetic config
and created a large runtime artifact set even in the no-selection control; the
probe separates that initialization from the selection delta and emits only
artifact classes/counts.

Hades model selection remains unimplemented by this task. The safe next
implementation must preserve the observed transient selection surface while
proving effective model use and persistence independently; it must not copy
the reference's repeated metadata requests or any stuck/error behavior.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0093-hermes-model-picker-selection.json)
- [Direct-PTY probe](../../../scripts/probe_hermes_model_picker_selection.py)
- [Related model-stage observation](OBS-0038-hermes-model-picker-model-stage-2026-08-01.md)
- [Fixture validator](../../../scripts/validate_reference_fixture.py)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
