# Hades implementation observation: OBS-0017

- Subject: Hades persistent input history
- Reference contract: [Hermes OBS-0016](OBS-0016-hermes-input-history-persistence-2026-08-01.md)
- Terminal: tmux-backed PTY at 120x40
- Contract fixture: `tests/fixtures/parity/OBS-0017-hades-input-history-persistence.json`
- Executable oracle: `scripts/replay_history.py`
- Task: HAD-017

Hades now resolves input history to `HERMES_HOME/.hermes_history`, falling back
to `HOME/.hermes/.hermes_history` when the explicit Hermes home is absent. The
runtime loads history before the TUI starts, injects the bounded entries into
the deterministic composer, and appends ordinary submitted drafts using the
observed `+` line format. Read and write failures are intentionally fail-open;
they do not prevent the TUI from starting or accepting input.

## Implemented contract

The implementation matches the reference-backed slice:

- outer whitespace is trimmed before history comparison and persistence;
- only a consecutive newest duplicate is suppressed;
- multiline drafts become one `+` record per logical line and reconstruct on
  load;
- only the newest 1,000 loaded entries are navigable;
- Up recalls the newest entry and Down returns to the saved empty draft after
  the newest entry;
- a second Hades process using the same `HERMES_HOME` recalls the first
  process's submitted draft.

## Verification

`python3 scripts/replay_history.py --binary target/debug/hades` runs four
isolated checks: process-restart recall, duplicate file-byte stability,
multiline history readback, and the 1,000-entry load boundary. The replay is
wired into `just verify`, alongside focused core/app tests for parsing,
serialization, trimming, deduplication, and injected history state.

## Explicitly unclaimed

History clearing, malformed-file recovery, concurrent writers, physical file
compaction, profile migration, and session transcript recovery remain outside
this slice.

## Linked artifacts

- [Hades contract fixture](../../../tests/fixtures/parity/OBS-0017-hades-input-history-persistence.json)
- [Hermes reference fixture](../../../tests/fixtures/parity/OBS-0016-hermes-input-history-persistence.json)
- [History replay](../../../scripts/replay_history.py)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
