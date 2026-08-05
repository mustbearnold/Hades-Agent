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
- [ ] T4. Stage 1: write `scripts/probe_hermes_tool_execution.py` and capture
      the S1–S4 reference observations (terminal → temp dirs, file tools,
      clarify, multi-hop loop).
- [ ] T5. Stage 2: sanitized OBS fixtures + observation documents; wire the
      probe into `justfile` and `scripts/verify.sh`.
- [ ] T6. Stage 3: `crates/hades-tools/` executor with the sandbox boundary,
      terminal/file/clarify implementations, and the multi-hop follow-up
      loop; unit tests at the typed seam.
- [ ] T7. Stage 4: direct-PTY multi-hop replay + differential parity against
      the reference observations; update parity matrix, README, and task
      evidence.
- [ ] T8. Complete `just verify` with no skips before completion.
