# Differential replay oracle: OBS-0005

- Subject: Hades visual and behavioral replay verification
- Reference trace: `tests/fixtures/parity/OBS-0003-submit-interrupt.json`
- Reference frame: `tests/fixtures/parity/OBS-0001-startup-120x40.txt`
- Visual state contract: `tests/fixtures/parity/OBS-0006-busy-interrupt-visual.json`
- Session trace and contract: `tests/fixtures/parity/OBS-0007-session-switcher.json`
- Command: `python3 scripts/differential_replay.py`
- Generated report: `.hades/runtime/differential-replay.json`
- Task: HAD-006

## Contract

The differential replay command runs one snapshot check and two bounded PTY
replays against the already-built Hades binary. First it invokes `hades
--snapshot` and compares its normalized 120x40 cell rows with the checked-in
Hermes startup golden frame. It then replays the sanitized submit/interrupt
trace: type `hello`, submit, interrupt the busy turn, and exit with the second
`Ctrl+C`. Finally it replays the session-switcher trace: open with `Ctrl+X`,
close with `Esc`, prove composer input resumes, and exit. The busy and
interrupted PTY markers come from OBS-0006; session markers come from OBS-0007.

The PTY check also proves the startup markers, raw terminal mode, successful
exit, alternate-screen leave sequence, and restoration of canonical input and
echo flags. The trace contains no credentials, model payloads, timing, or raw
reference terminal stream.

## Machine-readable result

The command emits a JSON report to stdout. `--report` writes the same report to
the generated runtime path without adding it to the reference fixtures. A
successful report has `passed: true` and passed results for
`visual_snapshot`, `behavior_replay`, and `session_switcher_replay`. A failure
has `passed: false` and a `failure` object with `kind`, `step`, and `message`.

Visual divergence stops at the first differing cell and reports its one-based
row and column, the expected and actual cell descriptions, and both row strings.
Behavioral divergence stops at the first failed replay assertion and includes a
bounded cleaned PTY output tail. This makes failures actionable without treating
the generated terminal stream as a new reference artifact.

## Intentional limits

| Difference | Reason |
| --- | --- |
| Snapshot comparison checks normalized text cells, not colors or cursor placement | The checked-in reference frame has already removed ANSI styling and dynamic cursor state. |
| PTY replay checks stable markers and transitions, not exact redraw timing | Terminal redraw streams vary with scheduling even when behavior is equivalent. |
| The command expects an already-built local binary | The `just replay-differential` recipe builds the locked CLI first; the script remains usable independently. |

## Linked artifacts

- [Replay command](../../../scripts/differential_replay.py)
- [Verification gate](../../../scripts/verify.sh)
- [Trace fixture](../../../tests/fixtures/parity/OBS-0003-submit-interrupt.json)
- [Golden frame](../../../tests/fixtures/parity/OBS-0001-startup-120x40.txt)
- [Busy/interrupt visual contract](../../../tests/fixtures/parity/OBS-0006-busy-interrupt-visual.json)
- [Session switcher trace and contract](../../../tests/fixtures/parity/OBS-0007-session-switcher.json)
- [Lifecycle PTY helpers](../../../scripts/probe_tui_lifecycle.py)
