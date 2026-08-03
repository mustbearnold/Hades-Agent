# Hermes reference revalidation: OBS-0104

- Subject: post-delay Setup Required action semantics
- Reference: pinned Hermes checkout at `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Version: Hermes Agent 0.19.1 (2026.7.30)
- Terminal: fresh 120x40 direct PTYs with a normalized ANSI screen model
- Task: HAD-108
- Probe: `scripts/probe_hermes_setup_required_actions.py`

The current pinned Hermes checkout reproduces the bounded OBS-0068 contract. After `/help` reaches Setup Required, typing `/model` or `/setup` and pressing Enter twice leaves the Setup Required surface visible. No model picker, setup wizard, provider request, or config change appeared. The normalized screen model observed a ready-marker redraw after the follow-up presses; that remains an unresolved underlying redraw detail, not successful setup or provider readiness.

The control case also remains stable: the first Ctrl+C keeps the process alive with Setup Required visible, and the second exits cleanly with status zero while restoring the terminal. The capture entered no credentials, OAuth, provider/model values, or side-effecting actions.

Hades should preserve this safe no-provider boundary until a more specific reference observation establishes an actionable route. Hermes strings and ambiguous redraws are not treated as permission to reproduce defects or infer hidden setup behavior.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0104-hermes-setup-required-actions-revalidation.json)
- [Repeatable direct-PTY probe](../../../scripts/probe_hermes_setup_required_actions.py)
- [Original bounded observation](OBS-0068-hermes-setup-required-actions-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
