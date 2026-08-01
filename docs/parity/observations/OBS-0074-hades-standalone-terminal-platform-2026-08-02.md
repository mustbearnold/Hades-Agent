# Hades standalone terminal-backend/platform boundary: OBS-0074

- Subject: standalone `hades setup` terminal-backend and platform-picker cancellation
- Reference contract: [OBS-0073](OBS-0073-hermes-standalone-terminal-platform-2026-08-02.md)
- Binary: current Hades debug CLI under direct PTY
- Terminal: 120x40
- Task: HAD-079
- Fixture: `tests/fixtures/parity/OBS-0074-hades-standalone-terminal-platform.json`
- Replay: `scripts/replay_standalone_terminal_platform.py`

Hades now carries the bounded standalone setup route through the observed
terminal-backend and platform-picker boundary. The replay starts with a fresh
synthetic home and no provider environment, sends only `j`, Enter, provider
Ctrl+C, backend Enter, platform Ctrl+C, and a final Ctrl+C from the restored
terminal surface.

## Verified surfaces

After the provider cancellation, the highlighted `Keep current (local)`
terminal backend is accepted and the platform picker renders its title,
controls, and unconfigured platform rows. No platform is selected and no
provider behavior starts.

The platform picker is intentionally bounded: platform movement and selection,
platform-specific setup, tool enablement, credentials, OAuth, network calls,
and successful save behavior are not claimed.

## Verified cancellation boundary

The first platform-picker Ctrl+C leaves the alternate screen, restores
canonical input and echo, and prints:

- `No platforms selected. Run 'hermes setup gateway' later to configure.`
- `Hermes Tool Configuration`
- `Enable or disable tools per platform.`
- `Tools that need API keys will be configured when enabled.`

The setup process remains alive on that plain terminal surface. A second
Ctrl+C is delivered as SIGINT and exits with status 130. The non-secret setup
config remains unchanged and no `.env` secrets file is created.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0074-hades-standalone-terminal-platform.json)
- [Direct-PTY replay](../../../scripts/replay_standalone_terminal_platform.py)
- [Hermes reference observation](OBS-0073-hermes-standalone-terminal-platform-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
