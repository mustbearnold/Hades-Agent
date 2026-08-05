# OBS-0120 — Hermes multi-hop tool execution loop

Date: 2026-08-05

Reference source commit: `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`

Terminal: direct PTY, 120×40

Probe: `scripts/probe_hermes_tool_execution.py` (scenario `s4-multi-hop`)

## Scope

Fresh synthetic Hermes TUI, deterministic loopback provider. One ordinary
prompt. The provider scripts the full multi-hop loop:

1. streaming `terminal` tool call — `mkdir -p <sandbox>/hopdir && echo
   hop-one > <sandbox>/hopdir/hop.txt`;
2. answers the resulting tool message with a streaming `read_file` tool
   call for `<sandbox>/hopdir/hop.txt`;
3. answers the second tool result with a plain completion.

Two hops, then termination.

## Observed boundary

- Hop 1 executed: `hop.txt` exists with exactly `hop-one\n` (8 bytes,
  `8dafa0ec…`).
- Hop 2 executed: the `read_file` result contains the `hop-one` anchor —
  the second hop read the file the first hop wrote, proving the sandbox is
  shared across hops.
- Real tool-result shapes (content never persisted, only shape):
  - terminal: 45-byte JSON, keys `error, exit_code, output`, digest
    `708054e2…` — identical to OBS-0117 and stable across two runs with
    different sandbox paths.
  - read_file: 121-byte JSON, keys `content, file_size, is_binary,
    is_image, total_lines, truncated`, digest `fb3accfc…` stable across two
    runs.
- Loop termination: after the second tool result, the follow-up stream
  carried no tool calls (plain completion, `finish_reason: "stop"`,
  `[DONE]`), the completion was served, and the process exited cleanly.
  The loop does not continue past a non-tool-call response.
- Request counts: 4 chat requests (3 streaming: initial + two tool-result
  follow-ups; 1 auxiliary non-stream `system, user`), 14 loopback HTTP
  requests, all `127.0.0.1` owned by the probe. Each follow-up's history
  grows by one `assistant (tool_calls), tool` pair per hop and every tool
  message references the synthetic call id.
- Terminal and read_file tool names visible in the rendered frame; ready
  marker present.
- Clean Ctrl+C exit. Terminal restored.

## Safe boundary

Transport + sandbox side-effect evidence only. Hades must not reproduce any
Hermes defect. Approval UI, retries, failure paths, and any termination
bound beyond the observed plain-completion stop remain unknown.

## Evidence

- `tests/fixtures/parity/OBS-0120-hermes-tool-execution-multi-hop.json`
- `.hades/runtime/hermes-tool-execution-s4-multi-hop-probe.json`
- `scripts/probe_hermes_tool_execution.py`
