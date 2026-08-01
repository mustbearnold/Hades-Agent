# Reference observation: OBS-0040

- Subject: Hermes TUI initial setup wizard navigation and cancellation
- Reference: Hermes Agent 0.19.1 / `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Terminal: fresh direct PTYs at 120x40, `TERM=xterm-256color`, dark theme
- Capture: normalized PTY landmarks plus a 120x40 ANSI screen model for the radio list
- Task: HAD-041
- Fixture: `tests/fixtures/parity/OBS-0040-hermes-setup-wizard-cancel.json`
- Probe: `scripts/probe_hermes_setup_wizard.py`

This observation isolates the first reversible setup-wizard boundary. Each case
starts Hermes with a fresh synthetic home and a custom provider pointed at an
intentionally absent loopback endpoint. The probe filters credential-like
environment variables and never selects a setup option, starts OAuth, enters a
secret, writes setup state, or reaches a provider.

## Initial wizard surface

After `/setup`, Enter, Enter, the normalized PTY stream contains:

- `Hermes Agent Setup Wizard`
- `Let's configure your Hermes Agent installation.`
- `Press Ctrl+C at any time to exit.`
- `How would you like to set up Hermes?`
- `Quick Setup (Nous Portal)`
- `Full setup`
- `Blank Slate`
- `ESC cancel`

The rendered 120x40 radio list starts with `Quick Setup (Nous Portal)` both
selected (`●`) and under the cursor (`→`). `Full setup` and `Blank Slate` are
unselected (`○`).

## Reversible controls

| Input | Stable result | Cleanup |
| --- | --- | --- |
| Escape before any option is submitted | Hermes leaves the curses radio list and prints its numbered fallback, including `Enter for default (1)  Ctrl+C to exit` and `Select [1-3] (1):`. It does not return directly to the chat surface. | Ctrl+C interrupts the fallback prompt and exits cleanly. |
| Down before any option is submitted | The cursor moves to `Full setup`, while the committed radio selection remains `Quick Setup (Nous Portal)`. | Ctrl+C exits without submitting a setup option. |

The apparent Escape-to-numbered-fallback behavior is the observed reference
contract for this pinned build, even though the curses hint calls the control
`ESC cancel`. The probe deliberately stops at the fallback prompt so no option
is selected.

## Dynamic boundaries and unknowns

The numbered fallback's choice submission, invalid input, later setup pages,
provider/API configuration, OAuth, persistence, existing-configuration flow,
deeper cancellation, exact redraw bytes, timing, and other terminal geometries
remain unknown. This observation makes no claim about successful setup or
reachable-provider behavior.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0040-hermes-setup-wizard-cancel.json)
- [Direct-PTY probe](../../../scripts/probe_hermes_setup_wizard.py)
- [Fixture validator](../../../scripts/validate_reference_fixture.py)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
