# Hades implementation observation: OBS-0039

- Subject: bounded Hades model picker model stage and back controls
- Reference contract: [OBS-0038](OBS-0038-hermes-model-picker-model-stage-2026-08-01.md)
- Hades source: workspace implementation under test
- Terminal: fresh 120x40 tmux-backed PTY
- Capture: normalized screen markers from an isolated replay
- Task: HAD-040
- Fixture: `tests/fixtures/parity/OBS-0039-hades-model-picker-model-stage.json`
- Replay: `scripts/replay_model_picker.py`

HAD-040 carries the reference-backed model-picker state boundary into Hades
without inventing provider discovery or network behavior. The implementation
uses a typed local catalog containing the observed `palette-loopback` provider
and `palette-model` model, so the state transitions and renderer can be proven
independently of credentials or external services.

## Verified behavior

The 120x40 replay proves the observed two-step `/model` entry sequence: the
first Enter accepts the `/model` completion and the second opens the provider
picker. The provider surface includes the stable title, current model,
filtering guidance, session persistence, and Escape/`q` hints. Typing
`palette` narrows the visible provider to `palette-loopback`.

Enter advances to the model stage with `palette-loopback`, `palette-model`,
`type to filter`, `persist: session`, and `Esc clear/back · q close` visible.
Typing `palette` keeps the model visible. The first Escape clears the active
filter and remains on the model stage; a second Escape returns to providers.
`q` closes the picker to the ready surface. The replay confirms no Busy footer,
model request, setup flow, or network side effect occurs, and Ctrl+C exits
cleanly afterward.

## Boundaries

The catalog is deliberately deterministic and bounded to the observed seam.
Provider discovery, credentials, network requests, model inventory refresh,
actual model switching, persistence toggling, setup/key entry, disconnect,
empty-list behavior, and model responses remain unknown. The implementation
does not claim the complete Hermes provider/model universe or parity at other
terminal sizes and themes.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0039-hades-model-picker-model-stage.json)
- [Replay](../../../scripts/replay_model_picker.py)
- [Hermes reference observation](OBS-0038-hermes-model-picker-model-stage-2026-08-01.md)
- [Fixture validator](../../../scripts/validate_reference_fixture.py)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
