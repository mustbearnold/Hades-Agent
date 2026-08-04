# Hermes reference observation: OBS-0071

- Subject: standalone `hermes setup` Full setup continuation and bounded cancellation
- Reference: pinned Hermes checkout at `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Version: Hermes Agent 0.19.1 (2026.7.30)
- Terminal: fresh 120x40 direct PTY with normalized stable markers
- Task: HAD-076
- Fixture: `tests/fixtures/parity/OBS-0071-hermes-standalone-full-setup.json`
- Probe: `scripts/probe_hermes_standalone_full_setup.py`

The standalone command was invoked as `hermes setup` in a fresh synthetic home
with no config, provider endpoint, credentials, OAuth action, external network,
provider value, or model selection. The probe moved from the default Quick
Setup row to Full setup with `j`, submitted only that choice, and stopped at the
first provider continuation.

## Verified continuation surface

After `j`, Enter, the normalized stream contains:

- `Configuration Location`
- `Config file:`
- `Secrets file:`
- `Data folder:`
- `Install dir:`
- `You can edit these files directly or use 'hermes config edit'`
- `Inference Provider`
- `Choose how to connect to your main chat model.`

Hermes is still in non-canonical, non-echo mode at this continuation. Selecting
Full setup creates a normalized `config.yaml` in the synthetic home; its content
is intentionally not retained. No secrets file is created.

## Verified cancellation chain

Ctrl+C at the Inference Provider surface skips provider setup and opens the
Terminal Backend curses surface. A second Ctrl+C leaves that surface for the
numbered terminal-backend fallback, restoring canonical input and echo. A third
Ctrl+C exits with status 1, leaves the alternate screen, and keeps the terminal
restored.

No terminal backend, provider, credential, OAuth, model, or network value is
submitted. The selection and cancellation chain is therefore a bounded
continuation observation, not a claim about successful setup.

## Dynamic boundaries and unknowns

The generated config contents, backup behavior, provider inventory, provider
submission, model/API key prompts, validation, terminal-backend selection,
Quick Setup OAuth, Blank Slate behavior, later setup sections, successful-save
summary, alternate key encodings, timing, and reachable-provider behavior
remain unknown.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0071-hermes-standalone-full-setup.json)
- [Direct-PTY probe](../../../scripts/probe_hermes_standalone_full_setup.py)
- [Fixture validator](../../../scripts/validate_reference_fixture.py)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
