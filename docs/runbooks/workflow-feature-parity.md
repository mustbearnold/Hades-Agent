# Feature parity workflow

Use this workflow for every non-trivial Hermes-compatible behavior.

1. **Orient.** Resolve the repository root and read the project contract. Do
   not inspect ignored runtime state or credentials.
2. **Select and claim.** Use `just agent next`, then claim one task. A claim
   creates a visible lease and prevents two agents from silently editing the
   same frontier.
3. **Observe.** Capture Hermes with exact provenance. Repeat the probe when
   stability matters. Record unknowns separately.
4. **Specify.** Turn observations into a trace, frame contract, lifecycle
   contract, or performance budget. Add the oracle kind to the task.
5. **Implement.** Change the narrowest Rust seam. Keep the reducer and renderer
   deterministic and independently testable.
6. **Verify.** Run focused checks while iterating, then run `just verify` at the
   candidate boundary. Compare the reference artifact, not a remembered image.
7. **Review.** Perform an adversarial scope and safety review. Check that the
   task does not claim more than its evidence.
8. **Close.** Complete only with a summary and existing evidence paths. If an
   external observation or authority is missing, mark the task blocked.

## Failure policy

An agent may retry transient local failures, but each retry must preserve the
original error in its run log. Environment failures are reported with the
command and exact output. A skipped gate is not a passing gate.
