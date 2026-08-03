# OBS-0110 — Hermes tool-call response handoff without execution

Date: 2026-08-03

Reference source commit: `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`

Terminal: direct PTY, 120×40

Probe: `scripts/probe_hermes_tool_call_handoff.py`

## Scope

This is a fresh synthetic Hermes TUI process with a deterministic loopback
OpenAI-compatible provider. One ordinary prompt was submitted. The provider
returned a valid streaming response containing a registered `clarify` tool
call, fragmented JSON arguments, and `finish_reason: "tool_calls"`.

The probe flushed the finish-reason chunk but withheld the terminal `[DONE]`
marker. After a bounded 0.2-second observation window, the still-live Hermes
process was stopped with `SIGTERM`. No tool response or tool action was
allowed to occur.

## Observed boundary

The request contained the same 31-function inventory captured by OBS-0109,
including `clarify`. The response used four SSE chunks: an assistant role
delta, a tool-call delta with the synthetic call identifier and function name,
a second delta carrying the continuation of the JSON argument string, and a
final empty delta with `finish_reason: "tool_calls"`.

The argument stream arrived in two fragments with lengths 45 and 58. The
fixture records only per-fragment SHA-256 digests and lengths. It records no
prompt, argument, authorization, or session payload. The PTY showed the
synthetic assistant marker and the tool name, but did not show a processing
status before the bounded stop. There were no subsequent chat requests and no
tool-response request.

## Safe boundary

This is transport evidence, not Hades tool behavior. The exact post-`[DONE]`
Hermes transition—overlay presentation, transcript persistence, `tool.start`,
`clarify` invocation, follow-up request, retries, and failures—remains
unknown. Hades must parse and approve tool calls through an explicit safe seam;
it must not infer execution from this observation or intentionally reproduce
Hermes defects or unsafe behavior.

The provider, credentials, and runtime were confined to a throwaway synthetic
home and probe-owned loopback endpoint. No external network, OAuth flow,
browser, or tool-specific filesystem/result side effect was observed.

## Evidence

- `tests/fixtures/parity/OBS-0110-hermes-tool-call-handoff.json`
- `.hades/runtime/hermes-tool-call-handoff-probe.json`
