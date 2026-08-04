# Hermes reference observation: OBS-0068

- Subject: post-delay Setup Required action semantics
- Reference: pinned Hermes checkout at `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Version: Hermes Agent 0.19.1 (2026.7.30)
- Terminal: fresh 120x40 direct PTYs with a normalized ANSI screen model
- Task: HAD-073
- Fixture: `tests/fixtures/parity/OBS-0068-hermes-setup-required-actions.json`
- Probe: `scripts/probe_hermes_setup_required_actions.py`

The delayed Setup Required surface is not an actionable `/model` or `/setup`
router in the bounded no-provider interaction captured here. In separate fresh
processes, typing `/model` or `/setup` after `/help` had reached Setup Required,
then pressing Enter twice, left the Setup Required overlay visible. Neither the
model picker nor setup wizard appeared, no config changed, and no provider
request started. The process then exited cleanly with one Ctrl+C after the
follow-up sequence.

A fresh control case confirmed the cleanup boundary: the first Ctrl+C kept the
process alive with Setup Required visible, and the second exited with status
zero, left the alternate screen, and restored canonical input and echo. The
screen model also saw a ready-marker redraw after the two follow-up Enter
presses while the overlay remained; that is recorded as an unresolved redraw or
underlying-state detail, not as successful startup or provider readiness.

This observation deliberately does not implement a Hades action route. The
next implementation decision requires a more specific Hermes focus/key
observation or a product-owner choice about whether the visible strings are
intended as instructions rather than controls.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0068-hermes-setup-required-actions.json)
- [Direct-PTY probe](../../../scripts/probe_hermes_setup_required_actions.py)
- [Delayed timing observation](OBS-0066-hermes-help-setup-timing-2026-08-02.md)
- [Hades delayed route](OBS-0067-hades-help-setup-required-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
