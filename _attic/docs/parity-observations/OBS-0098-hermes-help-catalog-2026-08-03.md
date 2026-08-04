# Reference observation: OBS-0098

- Subject: Hermes TUI stable `/help` panel and safe slash-command boundary
- Reference: Hermes Agent 0.19.1 / `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Terminal: fresh direct PTY at 120x40, `TERM=xterm-256color`, dark theme
- Capture: normalized stable landmarks plus a 120x40 ANSI screen model
- Task: HAD-103
- Fixture: `tests/fixtures/parity/OBS-0098-hermes-help-catalog.json`
- Probe: `scripts/probe_hermes_help_catalog.py`

This observation isolates the safe configured `/help` route. Hermes is started
with a synthetic configuration whose loopback endpoint is intentionally absent.
The probe submits only `/help`, waits for the bordered help row to remain stable,
and exits with Ctrl+C. It does not execute another slash command, send a
provider request, enter credentials, start OAuth, or use the external network.

## Stable help surface

At 120x40 the normalized screen contains the main Hermes landmarks `Hermes
Agent`, `Available Tools`, `Available Skills`, and `/help for commands`. The
help panel renders the following stable contract:

```text
╔════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
║  /help Show available commands                                                                                     ║
╚════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╝
❯ /help
```

The panel remains on the ready surface, with three identical rendered samples
recorded before cleanup. Ctrl+C restores terminal ownership and exits cleanly.

## Deliberate boundaries

The visible tool and skill counts, provider rows, discovery timing, redraw
ordering, complete command catalog, aliases, arguments, and pagination remain
unknown. This evidence does not authorize executing side-effecting slash
commands or inferring command semantics from labels. Hades should implement
only a typed, explicitly tested help surface from this contract and keep the
remaining catalog unknown until it is separately observed.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0098-hermes-help-catalog.json)
- [Direct-PTY probe](../../../scripts/probe_hermes_help_catalog.py)
- [Fixture validator](../../../scripts/validate_reference_fixture.py)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
