# Hades implementation observation: OBS-0041

- Subject: bounded Hades initial setup wizard and Escape fallback
- Reference contract: [OBS-0040](OBS-0040-hermes-setup-wizard-cancel-2026-08-01.md)
- Hades source: workspace implementation under test
- Terminal: fresh 120x40 tmux-backed PTY
- Capture: normalized screen markers from an isolated replay
- Task: HAD-042
- Fixture: `tests/fixtures/parity/OBS-0041-hades-setup-wizard-cancel.json`
- Replay: `scripts/replay_setup_wizard.py`

HAD-042 carries the smallest observed setup-wizard boundary into Hades. The
implementation keeps the option list and transitions typed in `hades-core`,
renders the stable wizard landmarks in the TUI, and deliberately stops before
credentials, OAuth, provider configuration, persistence, or network behavior.

## Verified behavior

The 120x40 replay proves the observed two-step `/setup` entry sequence: the
first Enter accepts the `/setup` completion and the second opens the wizard.
The initial surface includes the wizard title, setup explanation, Quick Setup,
Full setup, Blank Slate, the initial `→ (●)` Quick Setup row, and the Escape
hint.

Down moves the cursor to `Full setup` while leaving the committed radio marker
on Quick Setup. Escape changes the typed wizard surface to the observed
numbered fallback with `Enter for default (1)  Ctrl+C to exit` and
`Select [1-3] (1):`. Ctrl+C exits the process cleanly without entering Busy or
making a model request.

## Boundaries

Later setup pages, provider/API configuration, OAuth, persistence, numbered
choice submission, invalid input, existing-configuration setup, alternate
navigation keys, and successful setup remain unimplemented or unknown. This is
a bounded parity seam, not a claim about the complete Hermes setup wizard.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0041-hades-setup-wizard-cancel.json)
- [Replay](../../../scripts/replay_setup_wizard.py)
- [Hermes reference observation](OBS-0040-hermes-setup-wizard-cancel-2026-08-01.md)
- [Fixture validator](../../../scripts/validate_reference_fixture.py)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
