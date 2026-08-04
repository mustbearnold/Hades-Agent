# OBS-0116 — Hermes clarify question surface interaction

Date: 2026-08-03

Reference source commit: `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`

Terminal: direct PTY, 120×40

Probe: `scripts/probe_hermes_clarify_question_surface.py`

## Scope

Fresh synthetic Hermes TUI, deterministic loopback provider. One ordinary
prompt. Provider returns complete stream: fragmented `clarify` tool call,
`finish_reason: "tool_calls"`, terminal `[DONE]`. Once the question surface
renders, the probe sends only bounded non-submitting inputs (ArrowDown,
ArrowUp, then one Enter on the first visible choice), records the interaction
markers and the follow-up request carrying the real tool-result content, and
stops the process with bounded cleanup.

OBS-0114 observed the question surface as static markers and never pressed a
key on it. This observation exercises the surface interactively. `clarify` is
interactive-only: execution is confined to the TUI question surface, so this
involves no network, credential, OAuth, browser, filesystem, or installer side
effect.

## Observed boundary

- Question surface rendered after `[DONE]` with the question marker
  (`Clarify("synthetic clarification question")` tool-call row) and both
  choice markers visible.
- ArrowDown and ArrowUp during the bounded windows kept the surface alive with
  question and both choices still visible; no answer marker appeared and no
  submission happened.
- Enter on the first choice produced the follow-up answer: the second choice
  marker left the rendered frame while the answer text became visible; the
  process stayed alive and reached a ready marker.
- Request counts: 3 chat requests total, 1 initial + 2 subsequent. One
  follow-up streaming request carries the tool response with roles
  `system, user, assistant, tool` (assistant has `tool_calls_present: true`,
  tool message has string content). The third request is the same
  purpose-unknown auxiliary non-stream `system, user` request seen in
  OBS-0108/0109/0114.
- **Real tool-result content shape** (the exact unknown HAD-119 substituted
  with a Hades-owned synthetic marker): a 158-byte JSON string with top-level
  keys `choices_offered`, `question`, `user_response`; it contains both choice
  texts (inside `choices_offered`) and the selected choice text. Only the
  normalized shape is recorded (kind, length, digest, structural markers, JSON
  top-level keys); the content itself is never persisted. The digest was
  identical across two fresh probe runs (`7336fd6d…`).
- Clean Ctrl+C exit. Terminal restored.
- 8 loopback HTTP requests, all `127.0.0.1` owned by probe. No external
  traffic.

## Observed variation (recorded, not forced)

The first streaming request in this fresh run advertised **35 tools** until the
probe harness was fixed to strip desktop-app environment leakage
(`HERMES_DESKTOP`, `PYTHONPATH`) from the reference child; the corrected
observation advertises the anchored **31-tool** inventory matching OBS-0112.
The drift was an environment leak (this harness ran from inside the Hermes
desktop app), not a reference behavior change; the harness fix is part of the
OBS-0116 evidence. The tool-result content shape is unaffected by the fix
(identical digest `7336fd6d…` before and after).

## Safe boundary

Transport + interactive-UI evidence only. Hades must not reproduce any Hermes
defect or turn the observed question surface into execution, approval, or
forwarding behavior. Approval policy, execution semantics, retries, failure
behavior, and cursor-row cell-level markers: unknown.

## Evidence

- `tests/fixtures/parity/OBS-0116-hermes-clarify-question-surface.json`
- `.hades/runtime/hermes-clarify-question-surface-probe.json`
- `scripts/probe_hermes_clarify_question_surface.py`
- `scripts/probe_hermes_slash_commands.py` (harness environment sanitization:
  strips `HERMES_DESKTOP` and `PYTHONPATH` from the reference child so
  observations match the plain-CLI reference environment)
