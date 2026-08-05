# OBS-0118 — Hermes file tool execution against a synthetic sandbox

Date: 2026-08-05

Reference source commit: `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`

Terminal: direct PTY, 120×40

Probe: `scripts/probe_hermes_tool_execution.py` (scenario `s2-file-tools`)

## Scope

Fresh synthetic Hermes TUI, deterministic loopback provider. One ordinary
prompt. The provider scripts three file-tool hops against the probe-owned
sandbox, each its own streaming tool-call turn:

1. `write_file` — path `<sandbox>/sample.txt`, content `synthetic file content`;
2. `read_file` — path `<sandbox>/sample.txt`;
3. `search_files` — pattern `*`, target `files`, path `<sandbox>` (list);

then a plain completion terminates the loop.

## Observed boundary

- All three tools executed against the sandbox: `sample.txt` exists with
  exactly `synthetic file content` (22 bytes, `f9de2e46…`).
- The multi-hop loop is confirmed: each tool result produces a follow-up
  streaming request whose history grows by one `assistant (tool_calls),
  tool` pair per hop — request 2 has 4 messages, request 3 has 6, request
  4 has 8. Every tool message references the synthetic call id.
- Real tool-result shapes (content never persisted, only shape):
  - write_file: 266-byte JSON, keys `bytes_written, dirs_created,
    files_modified, lint, resolved_path`, contains the `sample.txt` anchor.
    The digest varies per run — `resolved_path` embeds the probe-owned
    absolute path.
  - read_file: 133-byte JSON, keys `content, file_size, is_binary,
    is_image, total_lines, truncated`, contains the written content anchor.
    Digest stable across two fresh runs (`497ef28a…`).
  - search_files: 87-byte JSON, keys `files, total_count`, contains the
    `sample.txt` anchor. The digest varies per run — the `files` list
    embeds the probe-owned absolute path.
- Request counts: 5 chat requests (4 streaming + 1 auxiliary non-stream
  `system, user`), 15 loopback HTTP requests, all `127.0.0.1` owned by the
  probe.
- All three tool names visible in the rendered frame; completion marker
  visible in the canonical run; ready marker present.
- Clean Ctrl+C exit. Terminal restored.

## Observed variation (recorded, not forced)

The write_file and search_files result digests embed probe-owned paths and
differ between runs; read_file's digest is stable. This is normalization
evidence: path-embedded results must be compared structurally (keys,
lengths, anchors), never by digest.

## Safe boundary

Transport + sandbox side-effect evidence only. Hades must not reproduce any
Hermes defect. Approval UI, retries, failure paths, timing, and list
ordering remain unknown.

## Evidence

- `tests/fixtures/parity/OBS-0118-hermes-tool-execution-file-tools.json`
- `.hades/runtime/hermes-tool-execution-s2-file-tools-probe.json`
- `scripts/probe_hermes_tool_execution.py`
