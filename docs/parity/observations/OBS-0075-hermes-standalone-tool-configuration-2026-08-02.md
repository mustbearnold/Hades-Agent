# Hermes standalone Tool Configuration action boundary: OBS-0075

- Subject: standalone `hermes setup` Tool Configuration handoff and bounded Escape action
- Reference: pinned Hermes checkout at commit `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Terminal: 120x40 direct PTY
- Task: HAD-080
- Fixture: `tests/fixtures/parity/OBS-0075-hermes-standalone-tool-configuration.json`
- Probe: `scripts/probe_hermes_standalone_tool_configuration.py`

This probe continues the safe standalone Full setup route from OBS-0073. It
skips provider setup, accepts only the displayed local terminal backend,
cancels the unconfigured platform picker, and then exercises one Escape at the
plain Tool Configuration handoff. No platform, tool, provider, credential, or
model value is submitted.

## Observed Tool Configuration handoff

The first platform cancellation restores canonical input and echo and prints:

- `No platforms selected. Run 'hermes setup gateway' later to configure.`
- `Hermes Tool Configuration`
- `Enable or disable tools per platform.`
- `Tools that need API keys will be configured when enabled.`

The setup config has already been created with normalized agent/display/session
settings by this point. The config remains unchanged by the bounded action and
no `.env` secrets file is created.

## Observed Escape boundary

Escape keeps the process alive and opens a raw `Tools for 🖥️  CLI` checklist.
The stable controls are `SPACE toggle`, `ENTER confirm`, and `ESC cancel`; the
visible rows include Web Search & Scraping, Browser Automation, Terminal &
Processes, and File Operations. The probe stops before submitting any row.

Because the next checklist is raw and may continue into provider-specific
configuration, cleanup sends only repeated Ctrl+C cancellation keys. Hermes
exits with status 130 after three bounded cleanup presses, restores canonical
input and echo, and leaves the config unchanged. Later tool/provider prompts
remain unknown.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0075-hermes-standalone-tool-configuration.json)
- [Direct-PTY probe](../../../scripts/probe_hermes_standalone_tool_configuration.py)
- [Prior platform boundary](OBS-0073-hermes-standalone-terminal-platform-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
