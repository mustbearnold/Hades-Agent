# Reference observation: OBS-0036

- Subject: Hermes TUI slash-command and configuration entry surfaces
- Reference: Hermes Agent 0.19.1 / `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Terminal: fresh direct PTYs at 120x40, `TERM=xterm-256color`, dark theme
- Capture: normalized stable text landmarks from four configured sessions
- Task: HAD-037
- Fixture: `tests/fixtures/parity/OBS-0036-hermes-slash-command-surfaces.json`
- Probe: `scripts/probe_hermes_slash_commands.py`

This observation covers the command/configuration entry points that are useful
for the next Hades parity slice. Each case starts Hermes in a fresh synthetic
home with a custom provider pointed at an intentionally absent loopback
endpoint. The probe filters credential-like environment variables and writes
only a synthetic configuration into the temporary home. It does not select a
provider, run OAuth, enter an API key, or provide a model response.

## Observed controls

| Input | Stable result | Cleanup |
| --- | --- | --- |
| `/help`, Enter | A help transcript/panel includes `/help`, `Show available commands`, `Available Skills`, and `/help for commands`; the session remains ready. | Ctrl+C exits cleanly. |
| `/model`, Enter, Enter | A provider picker shows `Select provider (step 1/2)`, `Full model IDs on the next step`, `Current: palette-model`, filtering guidance, session persistence, and Escape/`q` close controls. | Escape closes the picker; bounded Ctrl+C cleanup exits. |
| `/setup`, Enter, Enter | Hermes launches the external `hermes setup` wizard with its title, setup explanation, Quick Setup, Full setup, Blank Slate, and Escape-cancel landmarks. | Ctrl+C exits without selecting a setup option. |
| `/not-a-real-hermes-command`, Enter, Enter | The transcript reports `Unknown command: /not-a-real-hermes-command` and `Type /help for available commands`; it returns to ready without entering a model/busy turn. | Ctrl+C exits cleanly. |

The first Enter accepts slash completion in this capture. The second Enter is
therefore required to submit `/model`, `/setup`, and the unknown command. The
help path was observed with one Enter.

## Dynamic boundaries and unknowns

The provider and model rows, tool and skill counts, loading/spinner text,
discovery timing, redraw ordering, and exact provider warning text are dynamic
and are not promoted to fixed parity claims. The complete slash-command
catalog, arguments and aliases, deeper setup pages, OAuth/API configuration,
reachable-provider behavior, model selection persistence, streaming, tool
calls, and network errors remain unknown. The checked-in fixture retains only
stable landmarks and states these boundaries explicitly.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0036-hermes-slash-command-surfaces.json)
- [Direct-PTY probe](../../../scripts/probe_hermes_slash_commands.py)
- [Fixture validator](../../../scripts/validate_reference_fixture.py)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
