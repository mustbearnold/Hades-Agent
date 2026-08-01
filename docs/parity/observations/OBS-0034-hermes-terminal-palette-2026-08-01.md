# Reference observation: OBS-0034

- Subject: Hermes TUI terminal palette and text styling
- Reference: Hermes Agent 0.19.1 / `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Terminal: direct PTY at 120x40, `TERM=xterm-256color`, dark theme
- Capture: raw PTY bytes plus a sanitized terminal-cell model
- Task: HAD-034
- Fixture: `tests/fixtures/parity/OBS-0034-hermes-terminal-palette.json`
- Probe: `scripts/probe_hermes_terminal_palette.py`

This observation closes the first visual unknown without pretending that one
terminal run is the whole Hermes theme. The probe runs the pinned executable in
fresh synthetic homes. The configured ready case uses a loopback custom
provider pointed at `http://127.0.0.1:8765/v1`; no server, network request,
credential, model response, or private runtime state is used. The second case
starts without a provider and invokes `/help` to expose the setup-required
surface.

## Deterministic styles observed

The 120x40 cell model associates the following stable landmark styles with the
visible surfaces:

| Surface | Landmark | Observed style |
| --- | --- | --- |
| Startup | Hermes Agent, Available Tools, Available Skills | bold `indexed(220)` foreground on the default background |
| Startup | Nous Research | `indexed(178)` foreground |
| Ready footer | `ready` | `indexed(72)` foreground |
| Ready composer | typed draft | `indexed(230)` foreground |
| Busy footer | `Ctrl+C to interrupt` | white `rgb(255,255,255)` on gold `rgb(184,134,11)` |
| Interrupted completion | `✓` | `indexed(178)` foreground |
| Setup overlay | Setup Required | bold `indexed(220)` foreground |
| Setup overlay | explanatory text and `/model`/`/setup` actions | `indexed(178)` foreground |
| Setup overlay | selected option style observed in the redraw stream | `indexed(230)` on `indexed(60)` |

The fixture retains the exact SGR byte forms seen for each surface, including
the indexed and truecolor sequences, while excluding the full redraw stream.
The generated runtime report retains per-surface byte lengths and digests for
the particular run without making those timing-sensitive values part of the
portable contract.

## Interaction controls

| Case | Input | Observed result |
| --- | --- | --- |
| Ready composer | type `palette-ready` | draft text uses the composer style and remains ready |
| Busy | Enter | the busy footer exposes the gold `Ctrl+C to interrupt` affordance; rotating face text appears in the stream |
| Interrupted completion | Ctrl+C | `interrupted`, a `✓` completion marker, and ready state are rendered |
| Setup required | fresh home, `/help` | Setup Required overlay renders provider guidance and `/model`, `/setup`, and Ctrl+C actions |

The probe also verifies that the configured busy case can be interrupted and
that a second Ctrl+C exits cleanly; the setup-required case exits cleanly after
the observed two-press sequence.

## Boundary and unknowns

The palette claim is limited to the named controls under the captured terminal,
theme, dimensions, and pinned reference commit. Musing-face animation is
dynamic: the probe records representative markers and SGR forms, not a fixed
face, frame order, or timing. Successful model streaming, partial tokens, tool
calls, tool results, provider errors, retries, other themes and terminals,
mouse styling, hyperlinks, exact cursor placement, and wide-cell behavior were
not observed.

This is a Hermes reference observation. Hades implementation styling parity is
not claimed by OBS-0034.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0034-hermes-terminal-palette.json)
- [Direct-PTY probe](../../../scripts/probe_hermes_terminal_palette.py)
- [Fixture validator](../../../scripts/validate_reference_fixture.py)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
