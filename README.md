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
`just replay-fresh-shell-launch` verifies both command names from clean Bash and
Fish shells, checks that they resolve to the current release artifact, and
proves the installed TUI renders and restores the terminal after Ctrl+C.

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
just replay-fresh-shell-launch # fresh Bash/Fish command resolution and installed TUI lifecycle
just replay-vertical-slice    # setup -> local provider/model -> prompt -> streamed answer
just replay-configured-help   # configured /help panel parity replay
just replay-configured-help-lifecycle # configured /help Escape lifecycle replay
just replay-model-selection   # session model selection -> effective request -> fresh-process reset
just probe-distinct-model-selection # Hermes alternate-model effectiveness and persistence probe
just replay-installed-model-selection # release hades/Hades aliases -> same vertical slice
just replay-unconfigured-help # delayed /help setup-required PTY replay
just replay-standalone-setup  # standalone hades setup PTY replay
just replay-standalone-full-setup # standalone Full setup continuation replay
just replay-standalone-terminal-platform # standalone platform cancellation replay
just replay-standalone-empty-platform # bounded empty-platform confirmation replay
just probe-empty-platform-confirmation # Hermes empty-platform boundary and reconciliation probe
just replay-standalone-tool-provider # standalone tool checklist/provider boundary replay
just replay-standalone-tool-provider-inventory # standalone Browser Automation provider inventory replay
just replay-standalone-tool-provider-inventory-navigation # bounded cyclic provider navigation replay
just replay-standalone-tool-provider-inventory-selection # bounded safe provider action replay
just install-user             # build and install hades/Hades on user PATH
just snapshot                 # deterministic terminal snapshot
just probe-lifecycle          # PTY lifecycle and cleanup oracle
just replay-differential     # visual + behavioral parity replay
just replay-composer         # composer editing/history/multiline PTY replay
just replay-completion       # slash completion and Tab application PTY replay
just probe-help-catalog      # Hermes stable /help panel reference probe
just probe-help-lifecycle    # Hermes configured /help Escape lifecycle probe
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
just probe-hermes-tool-provider-inventory # bounded Browser Automation provider inventory probe
just probe-hermes-tool-provider-inventory-interaction # bounded provider navigation/cancellation probe
just probe-hermes-tool-provider-inventory-edges # bounded provider cursor edge probe
just probe-hermes-tool-provider-inventory-selection # bounded provider selection/cancellation probe
just replay-terminal-palette   # Hades SGR palette and cell-style parity replay
just replay-osc52-timing-limits # Hades OSC52 timing and bounded-size parity replay
just replay-osc52-st-termination # Hades ST-terminated OSC52 parity replay
just replay-osc52-multiplexer # Hades TMUX/STY OSC52 wrapper parity replay
just replay-local-provider   # loopback provider worker PTY replay
just probe-model-picker-selection # Hermes model selection side-effect boundary
just agent validate           # validate task/control-plane invariants
just agent next               # choose the highest-priority ready task
just agent claim HAD-001 bot  # claim a task with an agent identity
```

The repository intentionally has no external service or credential requirement
for its bootstrap path.

The first provider protocol seam lives in the `hades-provider` crate. It is
deliberately loopback-only (`http://127.0.0.1:<port>/...`). To connect a local
OpenAI-compatible server, set the endpoint before launching:

    export HADES_PROVIDER_BASE_URL=http://127.0.0.1:8765/v1
    export HADES_MODEL=palette-model
    hades tui

For the first working setup-to-answer journey, configure the loopback provider
once and then launch a fresh process:

    hades setup --local http://127.0.0.1:8765/v1 palette-model
    hades

That command writes only Hades' hades-local-provider.conf sidecar under
HERMES_HOME (or ~/.hermes) and leaves Hermes' config.yaml untouched. The
stored loopback endpoint and model are used when the environment variables are
absent; environment values remain the higher-priority override. API keys are
accepted only through HADES_PROVIDER_API_KEY and are never persisted.

The CLI worker translates the local SSE response into typed reducer events and
renders the assistant response. Without HADES_PROVIDER_BASE_URL or a saved
local setup, a fresh launch stays on the reference-backed starting agent…
boundary and does not start a provider worker or deliver prompts; the bounded
clone still accepts a visible draft during startup. Hermes also remains on
that boundary for a bounded 15-second window after /setup or /model, so those
commands are not yet a configuration escape in Hades. /help is the observed
exception: after submission it remains visible for the bounded 8000 ms route
deadline, then opens Setup Required with /model, /setup, and Ctrl+C.
just replay-unconfigured-help proves that transition against both launch forms,
and just verify also refreshes and replays the installed hades and Hades
launchers. Use hades setup for the separate first-run entry; its current
bounded slice reaches the observed Full setup continuation, accepts the local
terminal backend into the unconfigured platform picker, and carries platform
cancellation through the plain Hermes Tool Configuration boundary. The bounded
reference probe also records the first checklist navigation key and the
first-install provider handoff without selecting a tool. Provider credentials,
OAuth, platform selection, backend alternatives, and later setup remain outside
the clone contract. The local setup command is an explicit Hades vertical-slice
extension; it does not claim Hermes provider-persistence parity or reproduce
Hermes failure cases.

The next configured journey is covered by `just replay-configured-surfaces`.
It starts from that saved sidecar and proves the useful interaction loop around
the first answer: `/he` completion, `/model`, Ctrl+X sessions, persisted input
history across a fresh process, and a synthetic native clipboard paste before a
final streamed request. The replay uses only a local fixture server and never
touches the host clipboard or Hermes config.

Configured `/help` is covered separately by `just replay-configured-help`. It
replays the OBS-0098 stable bordered command row in a fresh configured process,
keeps the session ready without a provider request, preserves the `/help`
composer, and verifies clean Ctrl+C terminal restoration. The complete command
catalog and dynamic inventory remain explicitly unknown.

The matching lifecycle replay is `just replay-configured-help-lifecycle`. It
proves the OBS-0100 Escape boundary: the Help overlay and `/help` composer stay
visible while Hades remains alive, then Ctrl+C restores the terminal and exits.

Model selection is covered by the focused model-selection replay. It selects
palette-model in one configured process, proves that the next explicit request
uses it, then launches a fresh process against the unchanged sidecar and
proves vertical-model is used again. The selection is deliberately
session-scoped; Hermes retries, failures, and repeated metadata requests are
not copied into Hades.

The Hermes distinct-model boundary is captured by
`just probe-distinct-model-selection`. It exposes deterministic
`palette-model` and `alternate-model` rows, proves the visible selection and a
streamed request using the alternate model, then checks the provider-stage
current marker and config readback in a fresh process. The observed extra
metadata or chat requests are retained as diagnostics only; Hades does not
inherit an inferred retry or persistence policy.

The stable Hermes `/help` panel is captured by `just probe-help-catalog`. It
proves the bordered `/help Show available commands` row, the returned `❯ /help`
composer, the ready state, and clean Ctrl+C cleanup without executing another
command or contacting a provider. Dynamic counts and the complete command
catalog remain explicitly unknown.

The safe configured `/help` lifecycle is captured by `just probe-help-lifecycle`.
It proves that one Escape preserves the stable help panel and `/help` composer
while Hermes remains alive; Ctrl+C remains the bounded cleanup route. Other
focus, navigation, close, and repeated-help behavior remains unknown.

The installed command path is covered by just replay-installed-model-selection.
It resolves both hades and Hades in clean Bash and Fish shells, then runs the
same model-selection vertical slice through the release artifact behind each
alias.

The empty-platform reference boundary has an explicit reconciliation record.
The historical OBS-0058 capture stayed on the platform picker, while the
current pinned-runtime probe can reach a stable later Tool Configuration
surface. Both outcomes are retained as evidence; Hades keeps the safer typed
no-op and does not inherit implicit setup, installer, or network behavior.

Provider failures are covered by `just replay-provider-recovery`. Its local
HTTP 500, malformed-SSE, and incomplete-stream cases return to a visible Ready
state without automatic retries; a new user prompt clears the notice and sends
one explicit follow-up that can recover. This is an intentional safer Hades
boundary, not a reproduction of Hermes' ambiguous failure behavior.

Successful multi-turn context is covered by `just replay-conversation-context`.
Completed user/assistant turns become typed provider context, while failed or
partial turns remain visible for diagnosis but are excluded from the next
explicit follow-up. The direct-PTY replay proves the exact request sequence,
clean terminal restoration, and the absence of bootstrap or credential data in
the loopback payload.
