# Differential replay oracle: OBS-0005

- Subject: Hades visual and behavioral replay verification
- Reference trace: `tests/fixtures/parity/OBS-0003-submit-interrupt.json`
- Reference frame: `tests/fixtures/parity/OBS-0001-startup-120x40.txt`
- Visual state contract: `tests/fixtures/parity/OBS-0006-busy-interrupt-visual.json`
- Command: `python3 scripts/differential_replay.py`
- Generated report: `.hades/runtime/differential-replay.json`
- Task: HAD-006

## Contract

The differential replay command runs two bounded checks against the already-built
Hades binary. First it invokes `hades --snapshot` and compares its normalized
120x40 cell rows with the checked-in Hermes startup golden frame. Then it opens
the actual binary in a 120x40 pseudo-terminal and replays every input in the
sanitized submit/interrupt trace: type `hello`, submit, interrupt the busy turn,
and exit with the second `Ctrl+C`. The busy and interrupted PTY markers are
loaded from the separate OBS-0006 visual state contract.

The PTY check also proves the startup markers, raw terminal mode, successful
exit, alternate-screen leave sequence, and restoration of canonical input and
echo flags. The trace contains no credentials, model payloads, timing, or raw
reference terminal stream.

## Machine-readable result

The command emits a JSON report to stdout. `--report` writes the same report to
the generated runtime path without adding it to the reference fixtures. A
successful report has `passed: true` and one passed result for
`visual_snapshot` and `behavior_replay`. A failure has `passed: false` and a
`failure` object with `kind`, `step`, and `message`.

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
- [Lifecycle PTY helpers](../../../scripts/probe_tui_lifecycle.py)
