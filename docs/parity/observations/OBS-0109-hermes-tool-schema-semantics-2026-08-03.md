# OBS-0109 — Hermes tool-schema semantics

Date: 2026-08-03

Reference source commit: `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`

Terminal: direct PTY, 120×40

Probe: `scripts/probe_hermes_tool_schema_semantics.py`

## Scope

This is a fresh synthetic Hermes TUI process with a deterministic loopback
OpenAI-compatible provider. Two ordinary prompts were submitted and both
streamed answers were allowed to complete. The server recorded request
schemas in memory and returned ordinary assistant responses only.

No tool-call response was returned. No tool was executed, no credential or
OAuth flow was entered, and no external network was used.

## Observed boundary

Hermes sent 31 function tools on both ordinary streaming requests. The
normalized inventory is stable across the two requests and has digest
`90bc20dad34193bb183edab4038f4ca4cf220c63de3ebcec63b90fd9d14470bf`.

The captured semantics include tool names, function-level description
presence/length/digest markers, parameter property names, JSON-schema types,
required-property names, enum counts/kinds, nested array/object structure,
and schema-key markers. The fixture intentionally omits description text and
arbitrary parameter values.

The bounded request order was two schema-bearing streaming chat requests and
one auxiliary non-stream JSON request with no tools. The auxiliary request’s
purpose remains unknown; it is not classified as a retry, title generation,
summary, or Hades requirement.

## Safe boundary

This observation establishes provider wire evidence only. Tool-call response
handling, approval, execution, retries, discovery, persistence, error
semantics, and Hades tool-adapter behavior remain unknown. A future Hades tool
task must define explicit allowlisting, argument validation, approval, and
failure behavior instead of turning Hermes’s advertised inventory into
automatic execution.

## Evidence

- `tests/fixtures/parity/OBS-0109-hermes-tool-schema-semantics.json`
- `.hades/runtime/hermes-tool-schema-semantics-probe.json`
