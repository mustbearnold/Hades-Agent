# Hermes reference observation: OBS-0061

- Subject: input queue during fresh unconfigured startup
- Reference boundary: [OBS-0059](OBS-0059-hermes-unconfigured-startup-2026-08-02.md)
- Reference: pinned Hermes checkout at `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Terminal: fresh 120x40 direct PTY with an ANSI screen model
- Task: HAD-065
- Fixture: `tests/fixtures/parity/OBS-0061-hermes-unconfigured-input-queue.json`
- Probe: `scripts/probe_hermes_unconfigured_input_queue.py`

## Result

In two fresh no-config Hermes processes, sanitized `queued hello` text followed
by Enter became visible in the composer while the footer remained
`starting agent…`. The process did not show a ready footer, provider error, or
assistant output during the bounded three-second window, and `config.yaml` did
not appear or change. The result was identical whether input was sent as soon
as the starting marker appeared or after the startup surface stabilized.

The first Ctrl+C cleared the visible draft while Hermes remained on the
starting-agent surface. A second Ctrl+C exited with status zero, left the
alternate screen, and restored canonical input and echo. This proves that the
reference accepts input during startup; it does not prove that the draft was
sent or queued to a provider.

## Deliberate unknowns

The eventual startup resolution, queue depth, provider request timing, and
setup/provider persistence remain unobserved. Hades should not infer a queue
implementation or setup route from this bounded capture alone.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0061-hermes-unconfigured-input-queue.json)
- [Direct-PTY probe](../../../scripts/probe_hermes_unconfigured_input_queue.py)
- [Prior startup observation](OBS-0059-hermes-unconfigured-startup-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
