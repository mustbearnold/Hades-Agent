# Hades Agent

Hades Agent is an exact Hermes TUI clone rewritten in Rust. The project is
parity-first: every claimed behavior needs reference evidence and an executable
oracle.

The repository is ready for autonomous development. Start with:

```bash
just verify
just agent next
just snapshot
```

`just snapshot` renders the deterministic bootstrap frame without requiring an
interactive terminal. `just run` launches the TUI. `just probe-lifecycle`
runs the actual binary in a PTY and verifies startup, resize, exit, and terminal
restoration. The current work queue is in `.hades/tasks.json`; use `just agent next`
to select the next evidence-backed task.

The development contract is in [`AGENTS.md`](AGENTS.md). The task ledger and
bounded execution policy are in [`.hades/`](.hades/), and the role/workflow
contracts are in [`.agents/`](.agents/). Product requirements live in
[`docs/PRODUCT_SPEC.md`](docs/PRODUCT_SPEC.md).

## Commands

```bash
just check                    # complete local gate
just run                      # interactive TUI
just snapshot                 # deterministic terminal snapshot
just probe-lifecycle          # PTY lifecycle and cleanup oracle
just agent validate           # validate task/control-plane invariants
just agent next               # choose the highest-priority ready task
just agent claim HAD-001 bot  # claim a task with an agent identity
```

The repository intentionally has no external service or credential requirement
for its bootstrap path.
