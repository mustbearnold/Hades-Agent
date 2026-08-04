# Hermes reference observation: OBS-0048

- Subject: model-name default acceptance to terminal-backend picker
- Reference: pinned Hermes checkout at `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Version: Hermes Agent 0.19.1 (2026.7.30)
- Terminal: fresh 120x40 direct PTY with an ANSI screen model
- Task: HAD-049
- Fixture: `tests/fixtures/parity/OBS-0048-hermes-model-default-terminal-backend.json`
- Probe: `scripts/probe_hermes_full_setup_model_default.py`

The probe starts from the sanitized configured loopback provider used by
OBS-0046, reaches `Model name [palette-model]:`, and sends only Enter to
accept the displayed default. It stops at the first terminal-backend picker
and sends Ctrl+C without selecting a backend.

## Observed continuation

The stable 120x40 picker contains:

- `Select terminal backend:`
- `Local - run directly on this machine (default)`
- `Docker - isolated container with configurable resources`
- `Modal - serverless cloud sandbox`
- `SSH - run on a remote machine`
- `Daytona - persistent cloud development environment`
- `Vercel Sandbox - cloud microVM with snapshot filesystem persistence`
- `Singularity/Apptainer - HPC-friendly container`
- `Keep current (local)`

The picker also shows the `ENTER/SPACE select` and `ESC cancel` controls.
Three fresh bounded captures agreed on these rows, the config-byte change, and
clean Ctrl+C cleanup.

## Persistence and boundaries

Accepting the model default changes `config.yaml` bytes and creates a
timestamped config backup. The exact config delta is intentionally not
captured. Hermes may attempt a loopback model fetch while preparing the next
surface; no endpoint, credential, OAuth action, save action, model request,
or network-dependent choice is entered by the probe.

Terminal-backend selection, backend-specific configuration, persistence,
validation, errors, later setup sections, and successful setup remain
unobserved.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0048-hermes-model-default-terminal-backend.json)
- [Direct-PTY probe](../../../scripts/probe_hermes_full_setup_model_default.py)
- [Earlier model-prompt observation](OBS-0046-hermes-provider-selection-2026-08-01.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
