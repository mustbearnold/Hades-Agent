# Hades implementation observation: OBS-0049

- Subject: bounded model-default acceptance to terminal-backend picker
- Reference contract: [OBS-0048](OBS-0048-hermes-model-default-terminal-backend-2026-08-01.md)
- Hades source: workspace implementation under test
- Terminal: fresh 120x40 tmux-backed PTY
- Capture: normalized screen markers from an isolated replay
- Task: HAD-051
- Fixture: `tests/fixtures/parity/OBS-0049-hades-model-default-terminal-backend.json`
- Replay: `scripts/replay_setup_terminal_backend.py`

HAD-051 carries the stable OBS-0048 terminal-backend picker landmarks into a
typed, display-only Hades setup surface. The transition begins when Enter
accepts the displayed model default. Backend selection and every later setup
action remain outside the claim.

## Verified behavior

The 120x40 replay proves the existing `/setup` path through Full setup, the
active provider row, and the display-only `Model name [palette-model]:` prompt.
The next Enter reaches:

`Select terminal backend:`

The picker renders the captured Local, Docker, Modal, SSH, Daytona, Vercel
Sandbox, Singularity/Apptainer, and Keep current rows plus the
`ENTER/SPACE select` and `ESC cancel` controls. It retains the sanitized
provider/model context and exits cleanly on Ctrl+C before any backend action.

## Boundaries

Backend cursor movement, selection, configuration, persistence, validation,
errors, credentials, OAuth, model requests, network behavior, and later setup
sections remain unimplemented or unknown. This is a bounded parity seam, not a
claim about complete Hermes setup.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0049-hades-model-default-terminal-backend.json)
- [Replay](../../../scripts/replay_setup_terminal_backend.py)
- [Hermes reference observation](OBS-0048-hermes-model-default-terminal-backend-2026-08-01.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
