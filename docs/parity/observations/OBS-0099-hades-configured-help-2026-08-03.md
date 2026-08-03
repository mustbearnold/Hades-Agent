# OBS-0099 — Hades configured `/help` implementation

Date: 2026-08-03

Reference contract: [OBS-0098 Hermes stable help catalog](OBS-0098-hermes-help-catalog-2026-08-03.md)

Hades evidence: `scripts/replay_configured_help.py`,
`tests/fixtures/parity/OBS-0099-hades-configured-help.json`, and the generated
`.hades/runtime/configured-help-replay.json` report.

## Purpose

This replay closes the highest-value configured `/help` gap exposed by OBS-0098.
Before this change, a configured Hades process incorrectly opened the
`SetupRequired` overlay. The implementation now enters a typed `Overlay::Help`
state, keeps the session ready, retains the submitted `❯ /help` composer, and
renders the observed bordered `/help Show available commands` row.

## Bounded replay

The child runs in a fresh synthetic `HOME`/`HERMES_HOME` at 120x40 with a
configured but intentionally absent loopback endpoint and no credentials. It
submits only `/help`, waits for three identical screen samples, then sends the
observed Ctrl+C cleanup key. The replay proves the four stable main-surface
markers, exact double-border landmarks, configured ready state, no
setup-required overlay, and canonical/echo terminal restoration. The bottom
Help panel covers the visible ready footer at this geometry, matching the
reference lifecycle boundary.

No provider request, credential, OAuth flow, external network, or other slash
command is exercised.

## Implementation boundary

The complete command catalog, aliases, arguments, pagination, dynamic
tool/skill counts, redraw ordering, and command-specific behavior remain
unknown. Escape-to-close is a safe Hades convenience; the parity claim for
cleanup is limited to the observed Ctrl+C route. Hermes bugs or unsafe behavior
are not treated as implementation requirements.
