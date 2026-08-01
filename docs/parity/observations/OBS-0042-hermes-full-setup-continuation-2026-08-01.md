# Reference observation: OBS-0042

- Subject: Hermes TUI Full setup first continuation boundary
- Reference: Hermes Agent 0.19.1 / `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Terminal: fresh direct PTYs at 120x40, `TERM=xterm-256color`, dark theme
- Capture: normalized PTY landmarks plus a synthetic-home persistence check
- Task: HAD-043
- Fixture: `tests/fixtures/parity/OBS-0042-hermes-full-setup-continuation.json`
- Probe: `scripts/probe_hermes_full_setup.py`

This observation follows the bounded initial wizard only far enough to expose
the first Full setup continuation. Each case starts Hermes with a fresh
synthetic home and a custom provider pointed at an intentionally absent
loopback endpoint. The probe uses the observed `j` navigation key, submits the
Full setup choice, and stops at the first Inference Provider boundary. It does
not select a provider, enter a secret, start OAuth, reach a model response, or
run a network request.

## Verified continuation surface

After `/setup`, Enter, Enter, `j`, Enter, the normalized stream contains:

- `Configuration Location`
- `Config file:`
- `Secrets file:`
- `Data folder:`
- `Install dir:`
- `You can edit these files directly or use 'hermes config edit'`
- `Inference Provider`
- `Choose how to connect to your main chat model.`

The probe then sends Ctrl+C from the first provider boundary and observes a
clean process exit.

## Persistence boundary

The synthetic `config.yaml` bytes are unchanged and no secrets file is
created. Hermes does create a timestamped config-backup artifact when Full
setup begins; the artifact name and path are normalized away. No provider or
setup value is submitted beyond choosing the Full setup branch, and the
temporary synthetic home is removed after the probe.

## Dynamic boundaries and unknowns

The provider inventory, cursor/default, provider submission, model/API key
prompts, validation, later Full setup sections, numbered fallback choices,
Quick Setup OAuth, Blank Slate, existing-configuration setup, successful-save
summary, backup contents/retention, alternate key encodings, timing, and
reachable-provider behavior remain unknown.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0042-hermes-full-setup-continuation.json)
- [Direct-PTY probe](../../../scripts/probe_hermes_full_setup.py)
- [Fixture validator](../../../scripts/validate_reference_fixture.py)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
