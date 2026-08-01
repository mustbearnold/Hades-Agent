# Hermes reference observation: OBS-0059

- Subject: fresh unconfigured startup boundary
- Reference: pinned Hermes checkout at `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Version: Hermes Agent 0.19.1 (2026.7.30)
- Terminal: fresh 120x40 direct PTY with a redacted ANSI screen model
- Task: HAD-063
- Fixture: `tests/fixtures/parity/OBS-0059-hermes-unconfigured-startup.json`
- Probe: `scripts/probe_hermes_unconfigured_startup.py`

This capture starts Hermes with an empty synthetic `HOME`/`HERMES_HOME` and no
config, provider endpoint, credential, OAuth action, or setup input. It never
submits a prompt. Ctrl+C is used only for bounded cleanup.

## Bounded startup outcome

Hermes renders the normal startup shell and displays `glm-5.2 · Nous Research`,
but the first stable footer is `starting agent`, not `ready`. The ready footer
does not appear during the eight-second observation window. The same status and
model/provider marker repeat in a fresh process using the resulting synthetic
home.

No `config.yaml` exists after startup or cleanup. The run creates normalized
runtime artifact classes including tool/cache state, logs, `projects.db`, skill
state, and `tui-theme-boot.json`; those side effects are recorded as bounded
classes rather than treated as a complete persistence contract. Both processes
exit cleanly with Ctrl+C.

This explains why a blank environment cannot be used to infer a provider error
or a completed ready state: Hermes itself remains in startup initialization. The
cause and eventual resolution are intentionally outside this safe observation.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0059-hermes-unconfigured-startup.json)
- [Direct-PTY probe](../../../scripts/probe_hermes_unconfigured_startup.py)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
