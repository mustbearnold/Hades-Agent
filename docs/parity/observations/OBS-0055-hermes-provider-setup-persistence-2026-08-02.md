# Hermes reference observation: OBS-0055

- Subject: provider setup cancellation and bounded persistence readback
- Reference: pinned Hermes checkout at `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Version: Hermes Agent 0.19.1 (2026.7.30)
- Terminal: fresh 120x40 direct PTY with an ANSI screen model
- Task: HAD-059
- Fixture: `tests/fixtures/parity/OBS-0055-hermes-provider-setup-persistence.json`
- Probe: `scripts/probe_hermes_provider_setup_persistence.py`

The probe uses an isolated synthetic home with the same sanitized loopback
provider used by the earlier Full setup captures. It enters Full setup, submits
the active loopback provider, accepts the displayed `palette-model` default,
and reaches the terminal-backend picker. No endpoint, API key, OAuth action,
external network, or later backend-specific value is entered.

## Cancellation boundary

At the terminal-backend picker Hermes highlights `Keep current (local)`. A
bounded Ctrl+C exits cleanly without any additional backend action. The config
has already changed before this picker is reached because accepting the model
default is itself a mutating setup boundary; the config does not change again
when the picker is cancelled. The probe also records the normalized setup
artifact classes created before the picker and none created by the cancellation
itself.

## Bounded commit and readback

Accepting the highlighted `Keep current (local)` row advances to a
`Select platforms to configure:` surface with the observed navigation controls
and unconfigured platform rows. The config changes again at that selection.
After bounded cleanup, a fresh Hermes process launched with the same synthetic
home reaches `ready` and exits cleanly, proving that this bounded configuration
is loadable across a process boundary.

The checked-in fixture records only change boundaries, normalized artifact
classes, stable screen markers, and the fresh-process result. It does not store
config contents or hashes.

## Unknowns

The exact config delta and the identity of one normalized non-contract artifact
remain unknown. Platform selection, credentials, OAuth, endpoint editing, model
discovery, backend-specific setup, save errors, and later wizard continuation
remain unobserved. This capture does not generalize cancellation semantics to
setup paths reached before or after the displayed model default.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0055-hermes-provider-setup-persistence.json)
- [Direct-PTY probe](../../../scripts/probe_hermes_provider_setup_persistence.py)
- [Earlier terminal-backend observation](OBS-0048-hermes-model-default-terminal-backend-2026-08-01.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
