# Hermes reference observation: OBS-0054

- Subject: local-provider HTTP failure, malformed SSE, and incomplete-stream
  boundaries
- Reference: Hermes Agent 0.19.1, display build 2026.7.30
- Source commit: `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Terminal: fresh 120x40 direct PTYs
- Capture: deterministic loopback failure fixtures with a bounded post-request
  quiet window
- Task: HAD-058
- Fixture: `tests/fixtures/parity/OBS-0054-hermes-provider-errors.json`
- Probe: `scripts/probe_hermes_provider_errors.py`

## Observed boundary

With an HTTP 500 response or malformed SSE JSON, Hermes sent the expected
streaming chat request but showed no normalized provider-error marker and did
not return to a ready surface during the bounded quiet window. Ctrl+C then
interrupted the busy turn, and a second Ctrl+C exited cleanly.

With a stream that emitted a role delta and `HERMES_PARTIAL_ERROR` before
closing without `[DONE]`, Hermes issued four observed chat requests in the
bounded quiet window. Each later request contained a growing assistant/user
role sequence. The partial marker remained visible and the surface reached a
ready marker after that sequence. The probe records these requests without
calling them retries or inferring their purpose.

## Boundaries

The quiet window is an observation boundary, not a timeout or retry contract.
The exact error copy, backoff, retry limit, transient-state timing, draft
persistence, tool failures, authentication failures, and external-provider
behavior remain unknown. This is reference evidence only; Hades has not yet
implemented the corresponding failure/retry policy.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0054-hermes-provider-errors.json)
- [Repeatable direct-PTY/failure-fixture probe](../../../scripts/probe_hermes_provider_errors.py)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
