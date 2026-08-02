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
without requiring an interactive terminal. `just run` launches the TUI. The
installed `hades` or `Hades` command launches the TUI with no arguments, and
`hades tui` / `Hades tui` are explicit aliases for the same path.
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
`just replay-osc52-clipboard` replays bare-SSH OSC52 response precedence and
the DA1-barrier native-provider timeout control in an isolated direct PTY.
`just replay-osc52-response-boundaries` replays the OBS-0026 empty and
malformed-response controls against Hades and verifies native fallback order.
`just probe-osc52-st-termination` replays the pinned Hermes ST-terminated
response controls and records the reference-only result.
`just probe-osc52-multiplexer` probes the pinned Hermes TMUX/STY OSC52 query
wrappers and their direct-response/native-fallback boundaries; it intentionally
models raw PTY responses rather than a live multiplexer server.
`just probe-osc52-timing-limits` probes the pinned Hermes 500 ms response race
and bounded 256 KiB/512 KiB decoded OSC52 payload controls; it records timing
diagnostics without turning transport jitter into a product contract.
`just probe-terminal-palette` captures the pinned Hermes SGR palette and
terminal-cell styles for deterministic startup, ready, busy, interrupted, and
setup-required surfaces; animated faces and unobserved response states remain
explicit unknowns. `just replay-terminal-palette` verifies the corresponding
Hades palette implementation through fresh direct PTYs, including grouped SGR
forms and color output when `NO_COLOR` is inherited.
`just replay-osc52-timing-limits` replays those four bounded controls against
Hades and checks the exact query/DA1 bytes, provider order, payload markers,
readiness, non-submission, and cleanup.
`just replay-osc52-st-termination` replays the same ST controls against Hades
and verifies OSC52 precedence plus native fallback.
`just replay-osc52-multiplexer` replays the OBS-0030 TMUX/STY wrapper controls
against Hades and verifies the exact query bytes plus fallback order.
`just validate-reference` also checks the deterministic Hermes editor-outcome
fixture covering modified, multiline, empty, and cancelled editor handoffs,
plus the direct-PTY modified-Enter reference and Hades implementation fixtures.
It also validates the synthetic-provider successful text clipboard and remote
OSC52 precedence fixtures.
The current work queue is in
`.hades/tasks.json`; use `just agent next` to select the next evidence-backed
task.

To install the release binary for direct terminal use, run `just install-user`.
It builds the locked release binary and creates `hades` and `Hades` symlinks in
`~/.local/bin`; it does not modify shell configuration and refuses to replace
an unrelated existing path. The existing shell must already include
`~/.local/bin` on `PATH`.
After source changes, rerun `just install-user`; the launcher points at the
release artifact and is not refreshed by a debug build or `cargo run`.

The development contract is in [`AGENTS.md`](AGENTS.md). The task ledger and
bounded execution policy are in [`.hades/`](.hades/), and the role/workflow
contracts are in [`.agents/`](.agents/). Product requirements live in
[`docs/PRODUCT_SPEC.md`](docs/PRODUCT_SPEC.md).

## Commands

```bash
just check                    # complete local gate
just run                      # interactive TUI
just run setup                # standalone first-run setup entry
just replay-cli-launch        # no-argument and explicit-tui PTY launch replay
just replay-unconfigured-help # delayed /help setup-required PTY replay
just replay-standalone-setup  # standalone hades setup PTY replay
just replay-standalone-full-setup # standalone Full setup continuation replay
just replay-standalone-terminal-platform # standalone platform cancellation replay
just install-user             # build and install hades/Hades on user PATH
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
just replay-osc52-clipboard  # bare-SSH OSC52 and native fallback PTY replay
just replay-osc52-response-boundaries # malformed/empty OSC52 fallback replay
just probe-osc52-st-termination # Hermes ST-terminated OSC52 reference probe
just probe-osc52-multiplexer # Hermes TMUX/STY OSC52 wrapper reference probe
just probe-osc52-timing-limits # Hermes OSC52 timing and bounded-size reference probe
just probe-terminal-palette    # Hermes SGR palette and cell-style reference probe
just probe-hermes-help-setup-timing # timed /help setup-required reference probe
just probe-hermes-setup-required-actions # post-delay /model /setup action probe
just probe-hermes-standalone-setup # standalone hermes setup first-run probe
just probe-hermes-standalone-full-setup # standalone Full setup continuation probe
just probe-hermes-standalone-terminal-platform # standalone backend/platform boundary probe
just probe-hermes-standalone-tool-configuration # standalone Tool Configuration action probe
just probe-hermes-tool-configuration-navigation # standalone Tool Configuration navigation probe
just probe-hermes-tool-provider-boundary # first-install provider boundary probe
just replay-terminal-palette   # Hades SGR palette and cell-style parity replay
just replay-osc52-timing-limits # Hades OSC52 timing and bounded-size parity replay
just replay-osc52-st-termination # Hades ST-terminated OSC52 parity replay
just replay-osc52-multiplexer # Hades TMUX/STY OSC52 wrapper parity replay
just replay-local-provider   # loopback provider worker PTY replay
just agent validate           # validate task/control-plane invariants
just agent next               # choose the highest-priority ready task
just agent claim HAD-001 bot  # claim a task with an agent identity
```

The repository intentionally has no external service or credential requirement
for its bootstrap path.

The first provider protocol seam lives in the `hades-provider` crate. It is
deliberately loopback-only (`http://127.0.0.1:<port>/...`). To connect a local
OpenAI-compatible server, set the endpoint before launching:

```bash
export HADES_PROVIDER_BASE_URL=http://127.0.0.1:8765/v1
export HADES_MODEL=palette-model              # optional
# export HADES_PROVIDER_API_KEY=...            # optional; never logged by Hades
hades tui
```

The CLI worker translates the local SSE response into typed reducer events and
renders the assistant response. Without `HADES_PROVIDER_BASE_URL`, a fresh
launch stays on the reference-backed `starting agent…` boundary and does not
start a provider worker or deliver prompts; the bounded clone still accepts a
visible draft during startup. Hermes also remains on that boundary for a
bounded 15-second window after `/setup` or `/model`, so those commands are not
yet a configuration escape in Hades. `/help` is the observed exception: after
submission it remains visible for the bounded 8000 ms route deadline, then
opens Setup Required with `/model`, `/setup`, and Ctrl+C.
`just replay-unconfigured-help` proves that transition against both launch
forms, and `just verify` also refreshes and replays the installed `hades` and
`Hades` launchers. Use `hades setup` for the separate first-run entry; its
current bounded slice reaches the observed Full setup continuation, accepts the
local terminal backend into the unconfigured platform picker, and carries
platform cancellation through the plain Hermes Tool Configuration boundary.
The bounded reference probe also records the first checklist navigation key
and the first-install provider handoff without selecting a tool. Provider
credentials, OAuth, platform selection, backend alternatives, and later setup
remain outside the clone contract. Configure the loopback endpoint
before expecting a model response. No external provider service is required
for the deterministic bootstrap path.
