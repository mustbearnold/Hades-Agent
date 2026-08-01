# Lifecycle probe: OBS-0002

- Subject: Hades Agent bootstrap terminal lifecycle
- Reference contract: [OBS-0001 Hermes reference observation](OBS-0001-hermes-main-2026-08-01.md)
- Hades binary: target/debug/hades
- Host/OS: CachyOS Linux, kernel 6.18.40-1-cachyos-lts
- Probe runtime: Python standard-library pty.fork, 80x24 startup, 100x30 resize
- Probe command: just probe-lifecycle
- Captured at: 2026-08-01T01:12:58+00:00

## Contract

The lifecycle oracle launches the actual Hades binary in a pseudo-terminal and
fails with a nonzero exit code when any required state is missing. It emits a
machine-readable JSON report for each case.

| State | Input/action | Required observable result |
| --- | --- | --- |
| Startup | Launch in an 80x24 PTY | Hades is alive; the frame contains HADES AGENT, session, transcript, and input; alternate-screen entry is observed; termios is raw (canonical=false, echo=false). |
| Resize | Set the PTY slave to 100x30 | The application reports Terminal size: 100x30. and remains alive. |
| Normal exit | Press q with an empty composer | The process exits with code 0. |
| Interrupt exit | Type hello, submit, then press Ctrl+C | The submitted-turn status is visible, then the process exits with code 0. |
| Terminal cleanup | After either exit | Alternate-screen leave and cursor-restore sequences are observed; termios is restored (canonical=true, echo=true). |

Cleanup is checked at two independent layers: emitted terminal control
sequences and the actual terminal flags on the child PTY slave after process
exit. This catches a process that exits successfully while leaving the user's
terminal in raw mode or the alternate screen.

## Reference boundary

The current Hades bootstrap has no model adapter or distinct in-flight turn.
Therefore its interrupt case proves process interruption after submission, not
Hermes's active-turn cancellation behavior. The active-turn busy/interrupt
contract remains the reference behavior captured in OBS-0001 and is intentionally
left for a later interaction task.

The probe does not claim visual parity, model streaming, or full keymap parity.
It establishes terminal ownership and cleanup as a verified executable seam for
the next state-transition implementation.

## Linked artifacts

- Probe: [scripts/probe_tui_lifecycle.py](../../../scripts/probe_tui_lifecycle.py)
- Verification hook: [scripts/verify.sh](../../../scripts/verify.sh)
- Local command: [justfile](../../../justfile)
- Reference trace: [tests/fixtures/parity/OBS-0001-lifecycle.json](../../../tests/fixtures/parity/OBS-0001-lifecycle.json)
- Task: HAD-003
