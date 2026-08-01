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

`just snapshot` renders the normalized Hermes startup surface at 120x40
without requiring an interactive terminal. `just run` launches the TUI.
`just probe-lifecycle` runs the actual binary in a PTY and verifies startup,
resize, exit, and terminal restoration. `just replay-differential` compares
the normalized startup frame and replays the checked-in submit/interrupt,
session-switcher, and setup-required traces against the actual binary, writing
its generated report under `.hades/runtime/`. `just validate-reference` checks
the provenance and sanitization contracts for the reference-only input-editing
and persistent-history fixtures. `just replay-composer` replays the implemented editing, history, and
multiline contract in isolated PTY cases. `just replay-completion` replays the
implemented `/he` slash-completion and Tab-application contract in isolated PTY
cases. `just replay-paste` replays the bracketed-paste contract and verifies
that embedded newlines remain in the draft without submitting it. `just
replay-editor` replays the configured `EDITOR=/bin/true` handoff and verifies
the unchanged draft enters the busy state.
`just replay-editor-outcomes` replays modified, multiline, empty-output, and
cancelled deterministic editor handoffs against isolated Hades processes.
`just replay-modified-enter` replays direct-PTY CSI-u Shift+Enter and Alt+Enter
newline insertion, with plain Enter as the submission control.
`just replay-clipboard` replays the empty-clipboard Ctrl+V fallback and checks
that the draft is unchanged. `just replay-history` proves persistent history
across two Hades processes, multiline file encoding, duplicate byte stability,
and the newest-1,000 load cap.
`just replay-clipboard-text` replays successful native text insertion with a
synthetic xclip provider plus the empty-provider control.
`just validate-reference` also checks the deterministic Hermes editor-outcome
fixture covering modified, multiline, empty, and cancelled editor handoffs,
plus the direct-PTY modified-Enter reference and Hades implementation fixtures.
It also validates the synthetic-provider successful text clipboard fixture.
The current work queue is in
`.hades/tasks.json`; use `just agent next` to select the next evidence-backed
task.

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
just replay-differential     # visual + behavioral parity replay
just replay-composer         # composer editing/history/multiline PTY replay
just replay-completion       # slash completion and Tab application PTY replay
just replay-paste            # bracketed paste PTY replay
just replay-editor             # unchanged-draft editor handoff PTY replay
just replay-modified-enter     # native modified-Enter direct-PTY replay
just replay-clipboard        # empty-clipboard Ctrl+V PTY replay
just replay-clipboard-text   # successful text clipboard PTY replay
just agent validate           # validate task/control-plane invariants
just agent next               # choose the highest-priority ready task
just agent claim HAD-001 bot  # claim a task with an agent identity
```

The repository intentionally has no external service or credential requirement
for its bootstrap path.
