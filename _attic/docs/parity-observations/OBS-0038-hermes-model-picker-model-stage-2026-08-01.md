# Reference observation: OBS-0038

- Subject: Hermes TUI model picker model stage and back controls
- Reference: Hermes Agent 0.19.1 / `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Terminal: fresh configured direct PTY at 120x40, `TERM=xterm-256color`, dark theme
- Capture: printable input sent one key at a time; the complete ANSI stream was replayed through a 120x40 screen model so incremental Ink redraws were observed as rendered state
- Task: HAD-039
- Fixture: `tests/fixtures/parity/OBS-0038-hermes-model-picker-model-stage.json`
- Probe: `scripts/probe_hermes_model_picker.py`

This observation extends the bounded `/model` surface from OBS-0036 into the
second picker stage. It uses a fresh synthetic home and a custom provider aimed
at an intentionally absent loopback endpoint. The provider is narrowed by the
visible `palette` filter before advancing to the model stage; no model is
selected, persisted, or sent to a provider.

## Observed controls

The observed completion/submission sequence is `/model`, Enter, Enter. The
provider stage includes `Select provider (step 1/2)`, `Current: palette-model`,
`type to filter`, `persist: session`, `Esc clear/back`, and `q close`. Typing
`palette` one character at a time renders `filter: palette` and leaves the
synthetic `palette-loopback` provider as the selected row.

Pressing Enter advances to a model stage with these stable landmarks:

- `Select model (step 2/2)`
- `palette-loopback · Esc back`
- `type to filter · ↑/↓ select`
- the current `palette-model` row
- `persist: session`
- `↑/↓ select · Enter switch · Esc clear/back · q close`

Typing `palette` renders the model-stage `filter: palette` state with
`palette-model` still visible. Escape first clears that filter and remains on
the model stage. A second Escape, with no active filter, returns to the
provider stage. `q` then closes the picker and returns to ready. Bounded Ctrl+C
cleanup exits the process cleanly.

## Dynamic boundaries and unknowns

Provider/model rows, counts, ordering, loading and warning copy, discovery
timing, and visual styling are not promoted to fixed parity claims. Model
selection, persistence toggling, setup/key entry, disconnect, empty-model
handling, reachable-provider behavior, and other terminal sizes/themes remain
unobserved. Hades model-picker behavior is not implemented by this research
task; the fixture is reference evidence for a later implementation task.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0038-hermes-model-picker-model-stage.json)
- [Direct-PTY probe](../../../scripts/probe_hermes_model_picker.py)
- [Related slash-command observation](OBS-0036-hermes-slash-command-surfaces-2026-08-01.md)
- [Fixture validator](../../../scripts/validate_reference_fixture.py)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
