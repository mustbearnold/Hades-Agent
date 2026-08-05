# 011 — Tool execution checklist

Tick items in order. A task may only be marked done with its evidence named.

- [ ] T1. Write `specs/011-tool-execution/spec.md`, `plan.md`, `tasks.md`
      (promotion; this checklist).
- [ ] T2. Reword spec 005's out-of-scope line to "pending observation
      capture"; remove the promoted line from `specs/BACKLOG.md`; add spec
      011 to `README.md`; add the tool-execution row to the parity matrix.
- [ ] T3. Register the capture stages as control-plane tasks
      (HAD-180 observe, HAD-181 implement, HAD-182 parity-verify) with
      dependencies on the promotion task.
- [x] T4. Stage 1: write `scripts/probe_hermes_tool_execution.py` and capture
      the S1–S4 reference observations (terminal → temp dirs, file tools,
      clarify, multi-hop loop).
      Evidence: `scripts/probe_hermes_tool_execution.py`;
      `.hades/runtime/hermes-tool-execution-{s1-terminal,s2-file-tools,s3-clarify,s4-multi-hop}-probe.json`
      (all `passed`); sandbox side effects `out.txt`/`sample.txt`/`hop.txt`
      observed on the probe-owned temp dirs; tool-result shapes recorded
      (terminal `error/exit_code/output`, write_file
      `bytes_written/dirs_created/files_modified/lint/resolved_path`,
      read_file `content/file_size/is_binary/is_image/total_lines/truncated`,
      search_files `files/total_count`, clarify 158-byte
      `question/choices_offered/user_response` identical to OBS-0116);
      multi-hop loop: 3 streaming requests (S4) with
      `system,user,assistant,tool` follow-up shape and plain-completion
      termination.
- [x] T5. Stage 2: sanitized OBS fixtures + observation documents; wire the
      probe into `justfile` and `scripts/verify.sh`.
      Evidence: `tests/fixtures/parity/OBS-0117-hermes-tool-execution-terminal.json`,
      `tests/fixtures/parity/OBS-0118-hermes-tool-execution-file-tools.json`,
      `tests/fixtures/parity/OBS-0119-hermes-tool-execution-clarify.json`,
      `tests/fixtures/parity/OBS-0120-hermes-tool-execution-multi-hop.json`
      (all valid under `validate_reference_fixture.py` and
      `validate_fixture`); `_attic/docs/parity-observations/OBS-0117/0118/0119/0120-hermes-tool-execution-*-2026-08-05.md`;
      `justfile` recipe `probe-tool-execution` + `validate-reference` lines;
      `scripts/verify.sh` run_probe lines + fixture validation loop;
      parity matrix row updated.
- [ ] T6. Stage 3: `crates/hades-tools/` executor with the sandbox boundary,
      terminal/file/clarify implementations, and the multi-hop follow-up
      loop; unit tests at the typed seam.
- [ ] T7. Stage 4: direct-PTY multi-hop replay + differential parity against
      the reference observations; update parity matrix, README, and task
      evidence.
- [ ] T8. Complete `just verify` with no skips before completion.
