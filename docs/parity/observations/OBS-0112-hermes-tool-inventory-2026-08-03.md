# OBS-0112 — Hermes exact tool inventory with description text

Date: 2026-08-03

Reference source commit: `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`

Terminal: direct PTY, 120×40

Probe: `scripts/probe_hermes_tool_inventory.py`

## Scope

A fresh synthetic Hermes TUI process with a deterministic loopback provider
submitted one ordinary prompt. The complete `tools` array from the streaming
chat request was recorded in full: all 31 tool names, description text,
parameter property names/types, required fields, enum values, and nested
structure. Tool definitions are public API schemas from the pinned
open-source commit — not credentials or private state — so the fixture keeps
them verbatim.

## Anchoring to OBS-0109

The normalized structural marker digest
`90bc20dad34193bb183edab4038f4ca4cf220c63de3ebcec63b90fd9d14470bf` matches
the OBS-0109 inventory exactly, proving this is the same stable 31-tool
inventory — now with description text included. The raw-JSON inventory digest
is `b2cbd3f2bf77de3a91cf9a4844b324f6130aab8c72b2924a159cce533f38a220`.

The inventory is stable: the same names and order observed in OBS-0109
(`browser_back`, `browser_click`, …, `tool_search`, `tool_describe`,
`tool_call`) were captured again.

## Safe boundary

No tool was executed, approved, or forwarded. The provider request and
response stayed on the probe-owned 127.0.0.1 loopback, and the process was
interrupted and cleaned up after the bounded streamed answer. Tool execution,
approval, results, retries, and tool-call follow-up behavior remain unknown
and are not requirements from this fixture.

## Note on the validator

The shared fixture validator flags `sk-` at a token boundary (a credential
shape such as `"sk-…"`), which no longer false-positives on hyphenated prose
like "task-specific context" inside public tool descriptions.

## Evidence

- `tests/fixtures/parity/OBS-0112-hermes-tool-inventory.json`
- `.hades/runtime/hermes-tool-inventory-probe.json`
