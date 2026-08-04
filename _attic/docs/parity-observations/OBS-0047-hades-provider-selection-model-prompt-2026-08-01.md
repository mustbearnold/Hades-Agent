# Hades implementation observation: OBS-0047

- Subject: bounded provider selection to model-name prompt
- Reference contract: [OBS-0046](OBS-0046-hermes-provider-selection-2026-08-01.md)
- Hades source: workspace implementation under test
- Terminal: fresh 120x40 tmux-backed PTY
- Capture: normalized screen markers from an isolated replay
- Task: HAD-048
- Fixture: `tests/fixtures/parity/OBS-0047-hades-provider-selection-model-prompt.json`
- Replay: `scripts/replay_setup_provider_model_prompt.py`

HAD-048 carries the observed Hermes model-name prompt boundary into Hades as a
typed display-only surface. It preserves the sanitized provider context and
stops before model editing, validation, persistence, or any external action.

## Verified behavior

The 120x40 replay proves the existing two-step `/setup` entry sequence, Down
navigation to Full setup, Enter transition to the bounded provider menu, and a
second Enter transition from the active loopback row to:

`Model name [palette-model]:`

The screen retains `Current model: palette-model`,
`Active provider: palette-loopback`, and the active loopback row. Ctrl+C exits
cleanly without Busy, a model request, or credential/OAuth behavior.

## Boundaries

Model-name editing, default acceptance, validation, persistence, save
behavior, error handling, subsequent provider/model setup, dynamic provider
inventory, credentials, OAuth, and network behavior remain unimplemented or
unknown. This is a bounded parity seam, not a claim about complete Hermes
provider setup.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0047-hades-provider-selection-model-prompt.json)
- [Replay](../../../scripts/replay_setup_provider_model_prompt.py)
- [Hermes reference observation](OBS-0046-hermes-provider-selection-2026-08-01.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
