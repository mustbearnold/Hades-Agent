# OBS-0101 — Hades configured `/help` lifecycle implementation

Date: 2026-08-03

Reference contract: [OBS-0100 Hermes configured help lifecycle](OBS-0100-hermes-help-lifecycle-2026-08-03.md)

Hades evidence: `scripts/replay_configured_help_lifecycle.py`,
`tests/fixtures/parity/OBS-0101-hades-configured-help-lifecycle.json`, and
`.hades/runtime/configured-help-lifecycle-replay.json`.

The configured Hades Help overlay now preserves its typed state when Escape is
pressed. The exact bordered `/help Show available commands` row and `❯ /help`
composer remain visible, the process remains alive, and Ctrl+C exits cleanly
with the terminal restored. No provider request or other command is started.

This is limited to the single OBS-0100 Escape sequence. Other focus,
navigation, close, repeated-help, catalog, and dynamic inventory behavior
remains unknown, and Hermes redraw anomalies are not treated as requirements to
copy into unsafe behavior.
