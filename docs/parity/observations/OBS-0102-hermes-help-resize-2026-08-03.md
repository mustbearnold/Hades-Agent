# OBS-0102 — Hermes configured `/help` resize boundary

Date: 2026-08-03

Reference: pinned Hermes checkout at `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`.
Fixture: `tests/fixtures/parity/OBS-0102-hermes-help-resize.json`.
Probe: `scripts/probe_hermes_help_resize.py`.

In a fresh configured Hermes PTY, `/help` renders a three-row double-bordered
panel one cell in from the left edge and one row above the composer. The panel
tracks the terminal width and height: 118×3 at 120×40 with its top row at 36,
98×3 at 100×30 with its top row at 26, and 158×3 at 160×50 with its top row at
46. The `/help` composer remains on the final row, the process stays alive,
and bounded Ctrl+C restores the terminal.

Only `/help`, safe PTY resize signals, and Ctrl+C cleanup were exercised. Small
terminal clipping, focus/navigation, repeated-help behavior, dynamic catalog
behavior, and provider behavior remain unknown.
