# Hades bounded setup persistence extension: OBS-0107

- Subject: Hades-owned non-secret persistence at the standalone backend/platform boundary
- Reference contract: [OBS-0106](OBS-0106-hermes-setup-persistence-revalidation-2026-08-03.md), with cancellation lifecycle from [OBS-0074](OBS-0074-hades-standalone-terminal-platform-2026-08-02.md)
- Binary: current Hades debug CLI under direct PTY
- Terminal: 120x40
- Task: HAD-111
- Fixture: `tests/fixtures/parity/OBS-0107-hades-setup-persistence.json`
- Replay: `scripts/replay_standalone_terminal_platform.py`

Hades now persists a deliberately narrow sidecar when the displayed `Keep
current (local)` backend is accepted. The sidecar is
`hades-setup-boundary.conf`, stored beside the existing Hades baseline, and is
an explicit Hades-owned extension. It does not claim to reproduce Hermes YAML
values or authorize reading existing Hermes configuration.

## Verified persistence boundary

The direct-PTY replay runs two fresh cases. Cancelling at the terminal-backend
picker reaches the numbered fallback without creating the sidecar or changing
the existing non-secret baseline. Accepting the local backend creates the
sidecar before the empty platform picker; its normalized markers are:

```text
schema=1
setup_mode=full
terminal_backend=local
platform_selection=none
provider=unconfigured
```

The write uses a unique temporary file, flushes it, and commits it with a
same-directory rename. A duplicate write reads back byte-for-byte identically
and leaves no temporary file. The replay confirms that platform cancellation
does not mutate the sidecar, the baseline contains no credential-like fields,
no provider worker starts, and no `.env` file is created.

## Safety boundary

The sidecar is not read by startup provider detection, so the setup marker
cannot make an unconfigured process ready. Credentials, API keys, OAuth,
endpoint secrets, selected platforms, backend-specific configuration, and all
later setup behavior remain outside the claim. Hermes defects or unsafe failure
cases are not compatibility requirements.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0107-hades-setup-persistence.json)
- [Direct-PTY replay](../../../scripts/replay_standalone_terminal_platform.py)
- [Hermes persistence revalidation](OBS-0106-hermes-setup-persistence-revalidation-2026-08-03.md)
- [Hades terminal/platform replay](OBS-0074-hades-standalone-terminal-platform-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
