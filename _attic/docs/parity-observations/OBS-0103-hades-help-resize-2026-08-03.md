# OBS-0103 — Hades configured `/help` resize implementation

Date: 2026-08-03

Reference contract: [OBS-0102 Hermes configured `/help` resize boundary](OBS-0102-hermes-help-resize-2026-08-03.md).
Fixture: `tests/fixtures/parity/OBS-0103-hades-configured-help-resize.json`.
Replay: `scripts/replay_configured_help_resize.py`.

Hades now keeps its Hermes startup surface usable at the observed 100×30 and
160×50 sizes, and its configured Help overlay follows the reference geometry:
one-cell horizontal margins, three rows high, bottom-anchored immediately
above the final `/help` composer row. The typed configured state remains ready,
the process remains alive through resize, and Ctrl+C restores canonical input,
echo, and the alternate screen.

The implementation is limited to the observed geometry seam. It does not infer
minimum-size clipping, focus/navigation, repeated-help behavior, dynamic
catalog behavior, or provider semantics, and it does not reproduce Hermes
defects or unsafe side effects.
