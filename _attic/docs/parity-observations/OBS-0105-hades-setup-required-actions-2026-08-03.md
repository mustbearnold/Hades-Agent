# Hades implementation observation: OBS-0105

- Subject: post-delay Setup Required action boundary
- Reference contract: [OBS-0104](OBS-0104-hermes-setup-required-actions-revalidation-2026-08-03.md)
- Task: HAD-109
- Terminal: fresh 120x40 direct PTYs without a provider endpoint
- Fixture: `tests/fixtures/parity/OBS-0105-hades-setup-required-actions.json`
- Replay: `scripts/replay_setup_required_actions.py`

Hades preserves the safe no-provider boundary observed in Hermes. In separate
fresh processes, submitting `/help`, waiting for Setup Required, then sending
`/model` or `/setup` followed by two Enter presses leaves the Setup Required
overlay visible. Neither a model picker nor setup wizard opens, no provider
request starts, and no config file is created.

The first Ctrl+C keeps the process alive and clears the retained `/help` draft;
the second exits with status zero, leaves the alternate screen, and restores
canonical input and echo. Focused reducer coverage and the direct PTY replay
inspect the latest screen frame for draft clearing so earlier PTY redraw history
cannot produce a false failure.

This is an intentional safe boundary, not a claim that `/model` or `/setup` can
never become actionable. The Hermes strings and unresolved ready-marker redraw
do not establish a route, so Hades does not invent one or reproduce an
ambiguous reference failure case.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0105-hades-setup-required-actions.json)
- [Direct-PTY replay](../../../scripts/replay_setup_required_actions.py)
- [Focused app test](../../../crates/hades-app/src/lib.rs)
- [Hermes contract](OBS-0104-hermes-setup-required-actions-revalidation-2026-08-03.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
