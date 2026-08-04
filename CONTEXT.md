# Hades Agent project context

Status date: 2026-08-01

## Mission

Build Hades Agent, an exact Hermes TUI clone rewritten in Rust, with a
development loop that lets bounded AI agents make independently verifiable
progress from August 1, 2026 through 2027.

## Confirmed current state

- The repository began as an empty workspace on 2026-08-01.
- Rust 1.97.1 is available and pinned by `rust-toolchain.toml`.
- The initial scaffold is a Cargo workspace with core state, application
  transitions, a Ratatui view, and a CLI entry point.
- The autonomous development control plane lives in `.hades/` and `.agents/`.
- The Hermes reference is pinned to commit
  `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`; the provenance and sanitized
  startup/lifecycle artifacts are in `docs/parity/observations/OBS-0001*`.
- HAD-003 established a real-PTY lifecycle oracle in
  `scripts/probe_tui_lifecycle.py`.
- HAD-004 implements the first reference-backed core transition:
  submit text, enter a typed busy state, interrupt with Ctrl+C, then exit with
  Ctrl+C from ready.
- HAD-007 aligns the 120x40 busy and interrupted projection with the observed
  Hermes markers and drives those PTY assertions from the OBS-0006 visual
  contract; exact face-state timing remains intentionally unclaimed.
- HAD-008 adds typed session-overlay state, Ctrl+X open/Esc close transitions,
  and a deterministic 120x40 session switcher projection; session creation,
  switching, refresh, and persistence remain unknown.
- HAD-009 adds the observed `/help` setup-required path with retained-input
  rendering, first-Ctrl+C clearing, and second-Ctrl+C clean exit; provider setup
  and model selection remain unimplemented.
- HAD-010 captures the pinned Hermes input-editing/keymap subset: persistent
  history recall, cursor editing, multiline fallback, slash completion, Ctrl+G
  editor return, bracketed paste, and the empty-clipboard miss path. HAD-020
  separately captures native modified Enter through a direct PTY; HAD-021
  verifies the Hades Shift/Alt mapping, while mouse input, successful
  clipboard flows, and persistence across process restart remain explicit
  unknowns.
- HAD-011 implements the reference-backed composer subset with a dedicated
  Unicode-safe cursor model, session-local history recall, backslash-plus-Enter
  multiline input, terminal Home/End mapping, focused tests, and isolated PTY
  replay. Disk history, completion, paste, editor handoff, mouse, and other
  unobserved keymap behavior remain outside the claim.
- HAD-012 implements the observed slash-completion slice: exact `/he` items,
  deterministic rendering, and Tab application of `/help` before the fallback
  surface cycle. Completion gateway timing, other prefixes, multiline/busy
  behavior, and selection semantics remain unknown.
- HAD-013 implements the observed bracketed-paste path with crossterm paste
  events, cursor insertion, preserved newlines, and no implicit submission.
  Clipboard-provider reads, image/path paste, overlay/busy behavior, and mouse
  selection remain unknown.
- HAD-014 implements the observed unchanged-draft editor handoff with a typed
  Ctrl+G request, temporary draft file, configured EDITOR invocation, terminal
  suspension/restoration, and busy submission after a clean exit. HAD-018
  captures deterministic modified/multiline clean exits, trailing-newline
  trimming, empty output, and nonzero cancellation; interactive and
  unavailable-editor behavior remain unknown and unimplemented.
- HAD-015 implements the observed empty-clipboard Ctrl+V fallback with the
  exact miss message and unchanged draft. Successful clipboard reads, image or
  path paste, provider discovery, and overlay/busy behavior remain unknown.
- HAD-016 captures persistent Hermes input history against the exact pinned
  commit: restart recall, consecutive duplicate suppression, multiline `+`
  encoding, and the newest-1,000 load cap.
- HAD-017 implements the observed disk-history slice with injected core state,
  HERMES_HOME/HOME path resolution, fail-open file I/O, and a two-process PTY
  oracle. History clearing, malformed files, concurrent writers, and session
  recovery remain unimplemented.
- HAD-019 implements the deterministic editor outcome slice from OBS-0018:
  clean edited submission, multiline preservation, trailing-newline trimming,
  empty-output draft preservation, nonzero cancellation, and tokenized
  VISUAL/EDITOR replay. Interactive, unavailable-editor, and busy-turn cases
  remain unimplemented.
- HAD-020 captures the native Hermes modified-Enter contract through a direct
  120x40 PTY: CSI-u Shift+Enter and Alt+Enter insert a newline while plain
  Enter submits. Terminal emission support and alternate encodings remain
  outside this research-only claim; Hades mapping is verified by HAD-021.
- HAD-021 implements the stable modified-Enter slice: crossterm CSI-u Enter
  events with Shift or Alt insert a newline through the typed core transition,
  ordinary Enter still submits, and a direct-PTY replay proves both paths.
  xterm modifyOtherKeys, Ctrl+Enter, and universal terminal support remain
  unimplemented.
- HAD-022 captures Hermes successful Ctrl+V text clipboard behavior through a
  synthetic xclip provider: raw 0x16 invokes `xclip -selection clipboard -out`,
  preserves internal newlines and meaningful spaces, removes trailing newlines,
  and leaves the draft ready without submission. HAD-023 implements the native
  WSL/Wayland/xclip text path and preserves the empty-provider image-miss
  fallback; image attachments and path paste remain unknown. HAD-024 captures
  Hermes remote `SSH_TTY` OSC52-first precedence and the native-provider
  timeout fallback. HAD-025 implements the bare SSH_TTY OSC52 query/DA1 barrier
  path with bounded native fallback. HAD-026 captures Hermes empty, query-marker,
  invalid-base64, invalid-target, and unterminated OSC52 responses falling back
  to native xclip while remaining ready. HAD-027 verifies the same response
  boundaries in Hades through a dedicated direct-PTY replay; delayed/oversized
  responses, ST-terminated responses in Hades, tmux/STY wrapping, image
  attachments, and gateway behavior remain unknown. HAD-028 observes Hermes'
  ST-terminated behavior: usable text wins before native xclip, while empty and
  invalid-base64 responses fall back. HAD-029 verifies those three ST controls
  in Hades through a dedicated direct-PTY replay. HAD-030 observes Hermes'
  exact TMUX and STY OSC52 query wrappers plus direct-response/native-fallback
  boundaries in a synthetic direct PTY. HAD-031 implements and replays those
  exact wrapper bytes in Hades. Live multiplexer/outer-terminal forwarding,
  delayed/oversized responses, image attachments, and gateway behavior remain
  unknown.
- HAD-032 observes the pinned Hermes 500 ms OSC52 race in direct PTY controls:
  a usable response at a 100 ms target wins, a response supplied after the
  timeout DA1 flush falls back to native xclip, and deterministic immediate
  256 KiB and 512 KiB decoded payloads are consumed. The probe records measured
  timing and hashes while deliberately avoiding universal timeout/size claims.
  Hades delayed/size behavior, larger payloads, live forwarding, image
  attachments, and gateway behavior remain separate unknowns.
- HAD-033 aligns Hades' remote OSC52 race with the observed 500 ms boundary and
  replays the four OBS-0032 controls in fresh 120x40 direct PTYs. Hades now
  consumes the 100 ms response and bounded 256 KiB/512 KiB payloads before
  native xclip, while a response supplied after the boundary falls back. The
  bounded replay does not claim a universal maximum-size limit; larger payloads,
  live forwarding, image attachments, gateway behavior, and concurrent input
  remain separate unknowns.
- HAD-034 captures the pinned Hermes terminal palette subset in fresh 120x40
  direct PTYs: raw SGR forms and modeled landmark cell styles for startup,
  ready composer, busy interruption, interrupted completion, and
  setup-required surfaces. It records indexed and truecolor forms while
  keeping animated face timing, successful responses, alternate themes and
  terminals, and Hades implementation styling parity as unknowns.
- HAD-035 implements the observed deterministic palette subset at the typed
  Ratatui renderer seam and verifies it in fresh 120x40 Hades PTYs. The replay
  proves the indexed/truecolor landmark cell styles, Ratatui's grouped SGR
  forms, color output even when `NO_COLOR=1` is inherited, and clean busy/setup
  cleanup. Complete theme coverage, redraw-stream identity, animation,
  successful responses, alternate themes and terminals remain unknown.
- HAD-036 adds the user-local `just install-user` release installer. It builds
  the locked `hades-cli` release binary and creates collision-safe `hades` and
  `Hades` symlinks in `~/.local/bin` without modifying shell configuration;
  command-resolution and version checks are verified in Fish and Bash.
- HAD-037 captures the configured Hermes slash-command subset in fresh direct
  PTYs: `/help` renders a help surface, `/model` opens a two-stage provider
  picker after the observed completion/submission sequence, `/setup` hands off
  to the external setup wizard, and an unknown slash command reports an error
  while remaining ready. Provider discovery, deeper setup behavior, and
  reachable-provider outcomes remain unknown; the sanitized contract is in
  OBS-0036.
- HAD-038 implements the observed unknown slash-command boundary: unrecognized
  slash input produces the exact two-line error, clears the composer, remains
  ready without entering Busy, and exits cleanly through the existing lifecycle
  path. `/model`, `/setup`, aliases, arguments, and reachable-provider command
  behavior remain unimplemented and explicitly separate.
- HAD-039 captures the pinned Hermes `/model` provider-to-model picker path in a
  fresh 120x40 direct PTY: the synthetic loopback provider is reached through
  the visible `palette` filter, the model stage exposes its title, provider,
  current model, filter, session persistence, and close landmarks, and Escape
  first clears the model filter before a second Escape returns to providers.
  The full ANSI stream is replayed through a screen model to account for
  incremental Ink redraws; the implementation seam is carried by HAD-040.
- HAD-040 implements the bounded model-picker seam with typed provider/model
  stages, deterministic `palette-loopback`/`palette-model` labels, filtering,
  the observed two-step `/model` entry, and the two Escape meanings. A fresh
  120x40 replay verifies the stable landmarks, ready-state close, and absence
  of Busy/network behavior; provider discovery and model switching remain
  unknown.
- HAD-098 captures the next Hermes model-picker boundary without promoting a
  redraw into persistence: Enter on the visible `palette-model` row produces
  the transient `model → palette-model` status marker, while a no-selection
  control and fresh-process readback show no distinct config or effective-model
  proof because that model was already current. The local observation records
  bounded metadata paths and repeated probes as diagnostic reference evidence;
  Hades must not reproduce any retry or failure behavior.
- HAD-099 carries that safe boundary into Hades as typed session-scoped model
  selection: selecting palette-model visibly closes the picker and changes the
  next explicit loopback request, while a fresh process with the unchanged
  sidecar uses vertical-model again. OBS-0094 proves the request boundary,
  byte-identical sidecar, clean streaming lifecycle, and terminal restoration;
  saved provider selection remains intentionally unimplemented.
- HAD-100 proves the shipped user-local command path for that vertical slice:
  clean Bash and Fish shells resolve both hades and Hades to target/release/hades,
  and each installed alias completes the OBS-0094 selection, streamed request,
  fresh-process reset, and terminal-cleanup oracle. PATH absence, system-wide
  installation, and shell-profile mutation remain explicit boundaries.
- HAD-101 captures the missing Hermes distinct-model boundary: a deterministic
  alternate-model row can be selected, a bounded streamed request uses that
  alternate model, and a fresh process returns to the default current-model
  marker. The probe records normalized request metadata, config equality,
  artifacts, and clean terminal state; repeated metadata or chat requests are
  diagnostic reference behavior only, and no Hermes retry, failure, or
  persistence defect is reproduced in Hades.
- HAD-041 captures the initial Hermes setup wizard in fresh direct PTYs: the
  title, explanation, Quick Setup/Full setup/Blank Slate radio list, initial
  Quick Setup selection, Down navigation to Full setup, and the observed
  Escape-to-numbered-fallback boundary. Ctrl+C cleanup is verified without
  submitting an option; later setup pages, OAuth/API configuration, persistence,
  and Hades setup-wizard behavior remain unknown.
- HAD-042 implements the bounded initial setup-wizard surface with typed choice
  cursor/selection state, the observed two-step `/setup` entry, the
  Escape-to-numbered-fallback result, and clean Ctrl+C exit. A fresh 120x40
  replay verifies the stable landmarks without Busy, provider, OAuth, or
  network behavior; later pages and choice submission remain unknown.
- HAD-043 captures the first reversible Hermes Full setup continuation: after
  the observed `j` + Enter branch, Configuration Location and Inference
  Provider landmarks appear, Ctrl+C exits cleanly, config.yaml content remains
  unchanged, no secrets file is created, and a normalized config-backup
  artifact is created. Provider selection, credentials, and later sections
  remain unknown.
- HAD-044 makes the CLI launch intent explicit: no arguments and the `tui`
  subcommand enter the same TUI path, with direct-PTY coverage for startup and
  terminal restoration. The user-local release artifact still requires an
  explicit `just install-user` refresh, and an existing shell must have
  `~/.local/bin` on `PATH`.
- HAD-093 closes the user-facing launcher proof gap: clean Bash and Fish shells
  resolve both `hades` and `Hades` to the current release artifact when
  `~/.local/bin` is on `PATH`, and fresh PTYs show the visible startup TUI,
  raw/alternate-screen ownership, explicit Ctrl+C exit, and terminal
  restoration. The replay uses synthetic HOME state and does not mutate shell
  configuration; a PATH that omits `~/.local/bin` remains a configuration
  boundary rather than a bug the launcher can solve itself.
- HAD-094 wires the first usable Hades-only vertical slice. hades setup --local
  <loopback-url> [model] validates a loopback endpoint and atomically writes
  only hades-local-provider.conf; a fresh process reads that sidecar, reaches
  a ready composer, sends the selected model and prompt to the local
  OpenAI-compatible stream, renders the first assistant delta before delayed
  completion, and returns to ready. Environment values override the sidecar,
  API keys remain environment-only, and the display-only Hermes setup overlays
  remain bounded parity surfaces rather than invented persistence claims.
- HAD-095 proves that the configured journey is usable beyond the first answer:
  `/he` completion, `/model`, Ctrl+X sessions, two streamed prompts, persisted
  history across a fresh process, and synthetic native clipboard insertion all
  work without provider requests during navigation. The replay validates the
  recalled history by submitting an appended sentinel and validates clipboard
  insertion by inspecting the resulting request body, while sparse redraw
  fragments remain terminal-capture noise rather than invented product claims.
- HAD-096 hardens the configured provider journey across HTTP 500, malformed
  SSE, and incomplete-stream failures. Hades shows a bounded provider error,
  returns to Ready without an automatic follow-up, preserves already-rendered
  partial text as diagnostic context, clears the notice when the user edits a
  new prompt, and sends exactly one explicit follow-up that can recover. The
  direct-PTY OBS-0091 replay proves two local requests per case, no
  authorization header, clean terminal restoration, and no Hermes config
  mutation. Hermes' observed repeated requests and stuck busy surface remain
  defects/unknowns rather than behavior Hades reproduces.
- HAD-097 carries only successful conversation turns into later local-provider
  requests through a typed app lifecycle. The direct-PTY OBS-0092 replay proves
  the second request contains the first completed user/assistant turn, while a
  failed partial turn remains visible as diagnostic text but is excluded from
  the explicit recovery follow-up. Bootstrap display text never enters the
  request, no automatic context refresh occurs, and the replay proves clean
  terminal restoration with no Hermes config mutation or credentials.
- HAD-045 captures the bounded Hermes Full setup provider menu before any
  provider selection: current model/active provider, visible loopback and
  custom rows, reversible Down navigation, clean Ctrl+C, unchanged config
  bytes, and normalized backup/history/update-check artifact classes. Provider
  selection, credentials, OAuth, model discovery, network behavior, and later
  setup sections remain unknown.
- HAD-046 implements the bounded Hades Full setup provider menu: selecting the
  typed Full setup row reaches sanitized Configuration Location and Inference
  Provider landmarks, preserves the active loopback/model marker while moving
  to the custom-endpoint row, and exits cleanly without provider submission,
  credentials, OAuth, persistence, model discovery, or network behavior. The
  120x40 replay and focused core/app/TUI tests are wired through `just verify`;
  later provider actions and setup sections remain unknown.
- HAD-047 captures the next Hermes boundary: submitting the active loopback
  provider row opens `Model name [palette-model]:` while retaining the provider
  menu viewport. Three fresh direct-PTY captures show a config-byte change,
  clean Ctrl+C, and a normalized config-backup artifact; model-name entry,
  credentials, OAuth, save, model discovery, network behavior, and later setup
  sections remain unknown.
- HAD-048 implements the bounded Hades model-name prompt boundary: Enter on the
  active loopback provider row retains sanitized provider/model context and
  renders `Model name [palette-model]:`, while Ctrl+C exits without model input,
  validation, persistence, credentials, OAuth, save, model requests, or
  network behavior. The 120x40 replay and focused core/app/TUI tests are wired
  through `just verify`; all post-prompt behavior remains unknown.
- HAD-049 captures Hermes default model acceptance: Enter on
  `Model name [palette-model]:` reaches a terminal-backend picker with Local,
  Docker, Modal, SSH, cloud, Singularity/Apptainer, and Keep current rows.
  Three fresh captures show a config-byte change, normalized config backup, and
  clean Ctrl+C before backend selection; backend-specific setup and later
  behavior remain unknown.
- HAD-050 hardens the Hermes Full setup direct-PTY continuation probe with a
  guarded retry only while Full remains visibly selected; it preserves the
  fresh synthetic-home, no-credential, no-network boundary and keeps the
  checked-in fixture semantics unchanged.
- HAD-051 implements the bounded Hades terminal-backend picker after accepting
  the displayed model default. It renders the OBS-0048 Local, Docker, Modal,
  SSH, Daytona, Vercel Sandbox, Singularity/Apptainer, and Keep current rows
  with their controls, preserves sanitized provider/model context, and exits
  cleanly on Ctrl+C; backend selection and later setup behavior remain unknown.
- HAD-052 captures the first Hermes local-provider request/stream boundary with
  a fresh direct PTY and a deterministic loopback HTTP/SSE fixture. Hermes sends
  an authenticated streaming `POST /v1/chat/completions` with system/user
  messages and tools, renders the normalized response, returns to `ready`, and
  exits cleanly on Ctrl+C. Hades provider adapters, model responses, tool turns,
  and the purpose of subsequent chat requests remain unimplemented or unknown.
- HAD-053 adds the isolated `hades-provider` transport seam for that boundary.
  The loopback-only Rust transport serializes the normalized request, parses
  OpenAI-compatible SSE text deltas and `[DONE]`, and rejects HTTPS,
  non-loopback hosts, malformed streams, incomplete streams, and non-stream
  responses. It is tested against an in-process TCP fixture. HAD-054 adds the
  serializable core provider event lifecycle, reducer accumulation of assistant
  deltas, and bounded 120x40 rendering for streamed responses and provider
  terminal notices. The live CLI worker that translates transport output into
  those events is still separate and intentionally unimplemented.
- HAD-055 wires the loopback-only transport into the live CLI through a worker
  thread and channel. `HADES_PROVIDER_BASE_URL` is explicit, `HADES_MODEL`
  defaults to `palette-model`, and an optional API key is passed without being
  logged. A missing endpoint becomes a visible provider error; the local PTY
  replay verifies the request shape, response rendering, ready transition,
  active-turn Ctrl+C cleanup, and no external-network path.
- HAD-056 captures the next Hermes provider boundary with a delayed loopback
  SSE fixture: the first assistant delta becomes visible before a separated
  second delta, and Ctrl+C before that second release preserves the first
  delta, shows the interrupted surface, returns to `ready`, and closes the
  provider connection. The measured release gap is fixture-specific; later
  chat requests and the exact socket byte cutoff remain unknown.
- HAD-057 replaces the buffered Hades loopback response path with an
  incremental SSE reader and a CLI-owned cancellation token. Focused transport
  tests and the OBS-0053 direct-PTY replay verify first-delta visibility before
  the second release, partial-response preservation, no late second-delta
  rendering after Ctrl+C, provider socket closure, ready/interrupted state,
  and clean terminal restoration. The provider remains loopback-only.
- HAD-058 captures bounded Hermes failure fixtures: HTTP 500 and malformed SSE
  remain on the busy surface without a normalized provider-error or ready
  marker before cleanup, while an incomplete stream yields a partial marker and
  four observed chat requests with growing assistant/user role sequences before
  a ready marker. The follow-up purpose, retry policy, and exact error copy are
  intentionally unknown; Hades error/retry behavior remains unimplemented.
- HAD-059 captures a bounded Hermes Full setup persistence boundary in a
  synthetic home: accepting the displayed model default changes config before
  the terminal-backend picker, cancelling there adds no further config change,
  accepting the highlighted Keep current (local) row advances to platform
  selection and changes config again, and a fresh process returns to ready.
  Exact config contents, one non-contract artifact class, platform/provider
  configuration, and Hades persistence remain unimplemented or unknown.
- HAD-060 captures the normalized shape of that Hermes config without recording
  values: the initial model/custom-provider paths, `_config_version` after the
  model-default boundary, and `agent.max_turns`, `display.tool_progress`, and
  `session_reset.mode` after Keep current (local). The next surface is the
  platform picker; cancellation preserves the shape and a fresh process is
  ready. Hades config-file persistence, credential handling, and platform
  implementation remain unclaimed.
- HAD-061 implements the bounded Hades in-memory platform-picker continuation:
  accepting the displayed Keep current (local) backend reaches the observed
  platform title, controls, and unconfigured platform rows, while Ctrl+C exits
  cleanly. Platform toggling/confirmation, config writes, credentials, and
  later setup behavior remain unimplemented.
- HAD-062 captures the next Hermes boundary with no platform selected: Enter
  leaves the same platform picker stable during the bounded observation window,
  without a ready/error surface, config change, or new artifact class. Ctrl+C
  exits cleanly and a fresh process remains ready. Hades empty-platform
  confirmation remains unimplemented.
- HAD-063 captures Hermes with a fresh synthetic home and no config: the normal
  startup shell displays `glm-5.2 · Nous Research` but remains on `starting
  agent` without a ready footer during the bounded eight-second window. No
  config file is created, normalized runtime artifact classes are recorded,
  Ctrl+C cleanup is clean, and a fresh process repeats the same boundary. HAD-
  064 implements this captured boundary in Hades.
- HAD-064 carries that bounded boundary into the real Hades CLI: no provider
  endpoint selects a typed unconfigured startup state, blocks prompt/provider
  input, renders `glm-5.2 · Nous Research` with `starting agent…` and no ready
  prompt, and exits/restores the terminal cleanly on Ctrl+C. Both `hades` and
  `hades tui` direct-PTY replays pass; provider setup, persistence, credentials,
  and eventual startup resolution remain unimplemented.
- HAD-065 captures the next Hermes boundary: in two fresh no-config processes,
  sanitized input becomes visible in the composer while `starting agent…`
  remains active, with no ready/provider-error/assistant transition or config
  change. The first Ctrl+C clears the draft and the second exits cleanly.
  Whether the draft is queued, how startup eventually resolves, and Hades input
  queue delivery remain unimplemented or unknown.
- HAD-066 implements the bounded Hades side of that input boundary: the typed
  unconfigured state renders `❯ queued hello`, keeps the startup footer, does
  not start a provider request or add a user message, clears the draft on the
  first Ctrl+C, and exits on the second. Empty startup still exits on one
  Ctrl+C; provider setup, persistence, and actual queue delivery remain out of
  scope.
- HAD-067 captures the next Hermes boundary: submitting `/setup` or `/model`
  during fresh no-provider startup leaves the command visible on the stable
  `starting agent` surface for the bounded window, opens neither setup wizard
  nor model picker, changes no config, and exits cleanly on two Ctrl+C presses.
  Whether either command is eventually dispatched after startup resolves remains
  unknown; Hades has no setup/model escape from this startup state yet.
- HAD-068 extends that Hermes observation to a 15-second window across fresh
  no-input, `/setup`, and `/model` cases. All remain on `starting agent` with no
  ready surface, setup/model surface, provider error, or config change. The
  no-input case exits on one Ctrl+C; command cases exit on two. Behavior beyond
  the window and any configured startup route remain unknown.
- HAD-070 reconciles the older setup-required observation with the current
  no-provider captures: `/help` is distinct. In fresh direct-PTY and tmux
  cases, `/help` transitions from `starting agent` to `setup required` within
  the 15-second window, exposing `/model`, `/setup`, and Ctrl+C without changing
  config. Direct `/setup` and `/model` remain bounded startup input under
  OBS-0063/0064; Hades' delayed `/help` setup-required route is not yet wired.
- HAD-071 times that Hermes `/help` transition in two fresh direct PTYs. The
  starting-agent surface became stable at 2188 ms and 2084 ms after process
  start; Setup Required appeared at 10550 ms and 10336 ms, or 8344 ms and
  8236 ms after submission. The runs retained `/model`, `/setup`, and Ctrl+C,
  changed no config, and restored the terminal after two Ctrl+C presses. These
  are bounded samples, not a universal timeout contract.
- HAD-072 implements the delayed Hades `/help` route with a typed tick and
  injected deadline: the draft remains on `starting agent` for 8000 ms after
  submission, then opens the existing Setup Required overlay with `/model`,
  `/setup`, and Ctrl+C. Focused tests advance time without sleeping, and the
  direct PTY replay covers both launch forms, first-Ctrl+C draft clearing,
  second-Ctrl+C exit, no config/provider activity, and terminal restoration.
  The refreshed user-local `hades` and `Hades` release launchers pass the same
  replay; configured setup and provider behavior remain outside this slice.
- HAD-073 probes what Hermes does after that delayed overlay is visible. In
  separate fresh no-provider PTYs, typing `/model` or `/setup` and pressing
  Enter twice leaves Setup Required visible, opens neither picker nor wizard,
  changes no config, and starts no provider request. The first Ctrl+C keeps the
  overlay alive and the second exits cleanly. A ready-marker redraw appeared
  beneath the retained overlay after the follow-up Enter presses; its meaning
  remains unknown and no Hades action route is inferred from it.
- HAD-074 captures the standalone `hermes setup` entry boundary in a fresh
  synthetic home: Hermes opens a curses setup choice surface, Escape returns
  to the numbered fallback prompt, and Ctrl+C exits with status 1 while
  restoring the terminal and leaving config absent. Selected setup paths,
  persistence, and the Hades standalone setup command remain unimplemented.
- HAD-075 adds the standalone `hades setup` route at that bounded boundary:
  the observed banner and choices render on the alternate screen, Escape
  leaves it for the numbered fallback, and Ctrl+C exits with status 1 after
  terminal restoration without config or provider activity. Selected setup
  paths, persistence, credentials, OAuth, and direct initial-surface Ctrl+C
  remain outside the implementation claim.
- HAD-076 captures the standalone Hermes Full setup continuation in a fresh
  synthetic home. Choosing Full setup reaches Configuration Location and
  Inference Provider, creates a normalized config without a secrets file, and
  then follows the observed three-Ctrl+C chain: provider skip, Terminal Backend
  fallback, and status-1 exit. Backend selection, later setup pages, and Hades
  standalone continuation remain unimplemented.
- HAD-077 carries that bounded standalone Full branch into Hades. The `j`,
  Enter path writes only a non-secret baseline config marker and renders the
  observed Configuration Location/Inference Provider surface; Ctrl+C then
  traverses Terminal Backend and its numbered fallback before status-1 exit.
  Provider values, credentials, OAuth, backend selection, and later setup remain
  outside the claim.
- HAD-078 captures the next standalone Hermes boundary. After skipping the
  unconfigured provider with Ctrl+C, accepting the highlighted Keep current
  (local) backend reaches the platform picker with unconfigured Mattermost,
  Signal, and other rows. The first platform Ctrl+C leaves the alternate screen,
  restores canonical input and echo, and advances to No platforms selected and
  Hermes Tool Configuration while the process remains alive; the second exits
  with status 130. Normalized config shape is unchanged by platform
  cancellation, and platform selection, platform-specific setup, and later
  tool configuration remain unimplemented.
- HAD-079 carries that boundary into Hades. Accepting the highlighted local
  backend renders the unconfigured platform picker without selecting a
  platform or starting provider behavior. The first platform Ctrl+C leaves the
  alternate screen, restores canonical input and echo, and prints the bounded
  No platforms selected and Hermes Tool Configuration landmarks while keeping
  setup alive; the second Ctrl+C exits with status 130. Platform selection,
  platform-specific setup, tool enablement, credentials, OAuth, networking, and
  successful save behavior remain unimplemented.
- HAD-080 extends the Hermes evidence one safe action beyond that handoff. The
  plain Tool Configuration surface is followed by Escape into a raw `Tools for
  CLI` checklist with Space/Enter/Escape controls and stable Web Search,
  Browser, Terminal, and File rows. No row or provider is submitted; bounded
  repeated Ctrl+C cleanup exits with status 130 and leaves the normalized
  config unchanged. Hades must not claim later tool/provider configuration
  until it is separately observed.
- HAD-081 captures one more bounded Hermes navigation step from that raw
  checklist. The first visible cursor styling is on Web Search & Scraping; a
  single `j` key produced no changed screen-model snapshot within 100 ms, so
  delayed cursor semantics remain unknown. The first Ctrl+C restores canonical
  input and echo while leaving setup alive, then exposes the first-install
  `Configuring 6 tool(s)` / Browser Automation provider boundary. The probe
  stops before provider selection and uses harness-only forced teardown; later
  cancellation, tool toggling, and provider/key behavior remain unknown.
- HAD-082 records that first-install continuation directly. Within a bounded
  200 ms window after checklist Ctrl+C, Hermes prints `Configuring 6 tool(s)`
  and reaches the `Browser Automation - Choose a provider` boundary while
  keeping canonical input and echo restored. No provider choice or key is
  entered; the provider list, discovery subprocess behavior, network/OAuth
  activity, and later cancellation remain unknown. The probe teardown is
  harness-only and does not claim a Hermes product exit.
- HAD-083 carries that bounded route into Hades. Escape opens the raw
  `Tools for 🖥️  CLI` checklist with the observed controls and four stable rows;
  one `j` remains navigation-only, and the first checklist Ctrl+C restores
  canonical input and echo while keeping setup alive at the
  `Configuring 6 tool(s)` / Browser Automation provider boundary. The local
  checklist enable state is typed and ephemeral until persistence is observed;
  provider inventories, credentials, OAuth, networking, successful save
  behavior, later cancellation, and cursor-redraw timing remain outside the
  claim. This evidence boundary does not cap Hades performance or existing
  capabilities.
- HAD-084 observes the next Hermes-only provider surface without submitting a
  provider, credential, OAuth action, or network-bearing input. Within a
  bounded one-second read window Hermes exposes Local Browser, Nous
  Subscription, Camofox, Browser Use, Browserbase, Firecrawl, and Skip, with
  `↑↓ navigate`, `ENTER/SPACE select`, and `ESC cancel`. The inventory arrives
  during a redraw, so the labels are observed but stable frame identity,
  provider completeness, selection semantics, network behavior, persistence,
  and later cancellation remain unknown. The evidence boundary does not cap
  Hades performance or capabilities.
- HAD-085 carries that inventory into Hades as a bounded display-only surface.
  The restored canonical/echo boundary renders the seven observed options and
  controls with Local Browser selected as the recommended default. The direct
  PTY replay confirms the process remains alive, config is unchanged after the
  Tool Configuration boundary, and no new artifact or `.env` file appears.
  Provider selection, credentials, OAuth, networking, discovery timing, and
  later cancellation remain unknown. Hermes defects and failure cases are not
  compatibility requirements; Hades fixes them rather than intentionally
  reproducing them, and the evidence boundary does not cap Rust performance.
- HAD-086 observes three fresh Hermes provider-inventory interactions. A Down
  sequence moves the cursor to Nous Subscription without submitting it; Escape
  shows no visible transition during the bounded 750 ms window; Ctrl+C keeps
  Hermes alive but redraws a second FAL/image-generation provider surface.
  That cross-tool redraw is an explicit ambiguous reference transition, not a
  Hades requirement. Provider submission, credentials, OAuth, networking,
  persistence, delayed cancellation, and later behavior remain unknown. Hades
  must define safe typed semantics and fix defects rather than reproducing
  Hermes failures, and this observation does not cap Rust performance.
- HAD-087 carries the observed safe Down navigation into the Hades provider
  inventory. The provider surface now runs in raw mode, moves its cursor from
  Local Browser to Nous Subscription on the exact `ESC [ B` sequence, keeps
  Local Browser selected, and remains alive without changing config or creating
  artifacts. Enter/Space/Escape/Ctrl+C provider semantics and later setup remain
  unknown; the ambiguous Hermes Ctrl+C cross-tool redraw is not reproduced.
- HAD-088 observes cyclic Hermes provider cursor edges without submitting a
  provider. Up at Local Browser wraps to Skip; seven Down inputs walk through
  the observed rows and wrap from Skip to Local Browser; Down then Up returns
  to Local Browser. HAD-089 carries that safe edge contract into Hades with
  typed cyclic state, fresh three-case PTY replay evidence, unchanged Local
  Browser selection, stable raw terminal/process state, and unchanged config
  and artifacts. Hades must not inherit any unrelated Hermes defect or failure
  case from this observation.
- HAD-090 captures four fresh Hermes provider-action cases. Enter and Space on
  Local Browser leave the inventory with local-mode/no-configuration output;
  six Down inputs followed by Enter on Skip leave it with a skip message; and
  Escape leaves no stable transition marker in the bounded delta. All restore
  canonical input and echo while the process remains alive. Each first action
  also exposes an unrequested background Computer Use installer with `bash` and
  `curl` descendants plus a `.cua-driver` artifact, while the normalized config
  shape remains unchanged. Hades must not reproduce that implicit network or
  installation side effect; it is a Hermes defect/safety finding, not a parity
  requirement, and later installer/provider behavior remains unknown.
- HAD-091 implements the safe Hades side of that boundary. Typed Local Browser,
  Skip, and cancellation actions leave the raw provider surface, restore
  canonical input and echo, keep the process alive for bounded readback, and
  emit explicit status without starting a provider adapter, installer,
  subprocess, network request, or persistence write. A clean Ctrl+C exits with
  status 130. Paid/provider-specific actions remain unknown and are not guessed;
  Hermes' implicit installer/network behavior is fixed rather than reproduced.
- HAD-092 makes the OBS-0058 empty-platform boundary explicit in Hades. Enter
  with every platform unselected is a typed safe no-op: the same picker remains
  visible in raw mode, the process stays alive, the alternate screen remains
  active, and config/artifacts/provider activity do not change. The existing
  Ctrl+C handoff to Tool Configuration and status-130 cleanup remain verified;
  Space, platform toggling, and confirmation with selected platforms remain
  unknown rather than guessed.
- HAD-102 re-observes the same pinned Hermes source and preserves a reference
  disagreement: the earlier OBS-0058 run stayed on the empty platform picker,
  while the current frozen-runtime run reaches a stable Tool Configuration
  surface without changing config or artifacts. The probe records either
  bounded outcome, and Hades keeps the safer explicit no-op until the
  reference variation and later continuation are resolved.
- HAD-103 captures the stable configured Hermes `/help` panel in a fresh direct
  PTY: the bordered `/help Show available commands` row, returned `❯ /help`
  composer, ready state, and clean Ctrl+C cleanup. Dynamic inventories, the
  complete slash-command catalog, aliases, and arguments remain unknown; no
  side-effecting command or provider behavior is inferred or executed.
- HAD-104 implements the configured Hades `/help` boundary as a typed Help
  overlay and replays OBS-0098 at 120x40. It preserves the ready state and
  `/help` composer, renders the exact stable double-border landmarks, performs
  no provider request, and restores the terminal on Ctrl+C. The unconfigured
  delayed `/help` Setup Required route remains separately covered; Escape is a
  safe convenience, not a claimed Hermes observation.
- HAD-105 captures the missing configured Hermes `/help` Escape boundary in
  OBS-0100: one Escape preserves the double-bordered help panel and `/help`
  composer while the process remains alive, followed by bounded Ctrl+C cleanup.
  Hermes does not retain the normalized ready-footer marker in that redraw;
  this is recorded as an unresolved state detail, not provider readiness.
- HAD-106 makes configured Hades preserve its typed Help overlay and `/help`
  composer on Escape, matching the stable OBS-0100 lifecycle boundary. Ctrl+C
  remains the proven cleanup path; the unconfigured delayed Setup Required
  route and all other help focus/catalog behavior remain unchanged or unknown.
- HAD-107 captures OBS-0102 and matches the configured Help resize boundary.
  Hermes keeps the three-row double-bordered panel one cell from each
  horizontal edge and immediately above the composer at 120x40, 100x30, and
  160x50. Hades now uses the responsive Hermes startup surface at those sizes,
  preserves the typed ready state and `/help` composer, and keeps the bounded
  no-provider/Ctrl+C lifecycle; smaller-terminal clipping and other Help
  interactions remain unknown.
- HAD-108 revalidates OBS-0104 against the pinned Hermes checkout. After delayed
  Setup Required, `/model` and `/setup` remain on the explanatory overlay through
  two Enter presses with no provider request or config change; the first Ctrl+C
  keeps the overlay alive and the second exits cleanly. The ready-marker redraw
  is retained as an unresolved underlying detail, not provider readiness. Hades
  action replay remains the next implementation boundary.
- HAD-109 matches that safe boundary in Hades. Fresh no-provider 120x40 replays
  leave Setup Required visible through `/model` and `/setup` plus two Enter
  presses, open no picker or wizard, create no config, and start no provider
  request. Focused state coverage and the latest-frame PTY oracle prove the first
  Ctrl+C clears the retained `/help` draft while the overlay stays alive; the
  second restores the terminal and exits. An actionable route remains unknown.
- HAD-110 revalidates OBS-0106 for the next persistence seam. Hermes changes
  config after the displayed Full setup provider/model defaults, does not add a
  change when cancelling at Keep current (local), changes it again when that
  backend is accepted, and returns ready in a fresh process. The normalized
  shape includes `_config_version`, model/custom-provider paths, and bounded
  agent/display/session-reset additions; values, secrets, OAuth, and later
  platform behavior remain unknown.
- HAD-111 adds an explicit Hades-owned setup boundary sidecar after accepting
  the displayed local backend. It preserves the existing non-secret baseline,
  writes only normalized structural markers atomically, does not mutate on
  backend cancellation, and remains unchanged through platform cancellation.
  The sidecar is not read by provider startup detection, so it cannot imply a
  ready provider; credentials, API keys, OAuth, endpoint secrets, and selected
  platforms remain outside the claim. OBS-0107 is the direct-PTY oracle.
- HAD-112 captures the next Hermes provider boundary in a fresh configured
  loopback process. Two ordinary prompts produce two streaming requests: the
  second contains the completed first user/assistant turn, and both requests
  include the same 31-tool structural schema. Hermes also emits one
  protocol-correct auxiliary non-stream request with a `temperature` field;
  its purpose remains unclassified and is not a Hades requirement. No tool
  action, credential, external network, retry policy, or failure behavior was
  exercised. OBS-0108 is research evidence for a future safe provider/tool
  implementation task.

  OBS-0109 extends that evidence without entering tool execution. A fresh
  synthetic Hermes process sends the same stable 31-tool inventory on both
  ordinary streaming turns; the normalized fixture records names, parameter
  property names/types, required fields, nested shape markers, and description
  digests while omitting description text and arbitrary values. The auxiliary
  non-stream request remains purpose-unknown, and Hades does not advertise or
  execute these tools until a separate task defines safe approval, validation,
  and failure semantics.

  OBS-0110 captures the next transport boundary with one ordinary prompt and a
  valid fragmented `clarify` tool call. The probe records the registered tool,
  call-id/name fields, argument-fragment lengths and digests, and
  `finish_reason: "tool_calls"`, then withholds `[DONE]` and stops the live
  synthetic process before tool processing. No tool response, follow-up chat
  request, external network, OAuth, browser, or tool-specific filesystem
  result was observed. Complete-stream handoff, approval, execution, and
  failure behavior remain unknown; this is not a Hades tool implementation.

- HAD-115 implements the safe Hades side of that transport boundary: the
  provider SSE seam now parses `delta.tool_calls` into typed
  `ToolCallDelta` events, tool-call-only streams complete without a
  missing-data error, and the typed core/app seam accumulates argument
  fragments per call index into a bounded record (name, argument length,
  stable FNV-1a digest) on the completed turn. A fresh 120x40 direct-PTY
  replay (OBS-0111) proves the assistant text renders, the process returns to
  ready with no busy marker or invented tool overlay, no follow-up chat or
  tool-response request follows completion, and Ctrl+C exits cleanly. Hades
  never executes, approves, or forwards tool calls in this slice; tool
  registration, approval policy, execution, results, retries, and multiple
  calls per turn remain explicit unknowns.

  OBS-0112 captures the exact Hermes tool inventory with description text: a
  fresh synthetic process's streaming request carries the same stable 31-tool
  array from OBS-0109 (normalized marker digest matches), now recorded in
  full — names, descriptions, parameter names/types, required fields, enums,
  and nested structure. Tool definitions are public API schemas from the
  pinned commit, so the fixture keeps them verbatim with no execution or
  side effect; the fixture validator's `sk-` scan was refined to require a
  credential-shaped token boundary so hyphenated prose like "task-specific"
  no longer false-positives.

- HAD-117 closes the loop on the tool arc: Hades now advertises the observed
  OBS-0112 31-tool inventory on every streaming chat request (embedded as a
  typed static in the provider crate), with the canonical sort-keys digest
  matching the captured wire contract exactly. The OBS-0113 replay proves the
  advertised inventory (31 tools, digest `b2cbd3f2…`, `clarify` present),
  unchanged safe tool-call parse/accumulate behavior, ready return with no
  busy marker or tool overlay, one request with zero follow-ups, and clean
  Ctrl+C exit. Tool approval, execution, results, retries, and follow-up
  requests remain explicit unknowns; advertising is wire parity, not
  capability.

  OBS-0114 observes the post-completion handoff OBS-0110 deliberately
  withheld: with `[DONE]` sent, Hermes renders the interactive-only
  `clarify` question surface (question + choices markers), then sends the
  tool result back to the model in a follow-up request with
  `system, user, assistant, tool` roles (assistant message carries the tool
  call), plus the purpose-unknown auxiliary non-stream request, then returns
  to ready and exits cleanly with no external side effect. Hades still does
  not reproduce the tool-result follow-up or question surface; they remain
  the next implementation frontier after safe parse/advertise.

- HAD-119 implements the bounded tool-result follow-up observed in OBS-0114:
  after a completed turn with tool calls, Hades sends exactly one follow-up
  streaming request whose history matches the observed shape (system, user,
  assistant with the tool-call name/arguments, and a tool role message with a
  Hades-owned synthetic result marker), stays in the typed busy state across
  the follow-up, renders the second answer, and returns to ready. The follow-up
  is one hop: a follow-up response that itself requests tool calls is recorded
  and stopped (no unbounded loop), arguments are capped at 64 KiB, and nothing
  is executed, approved, or forwarded. The OBS-0115 replay proves the two
  requests, the observed follow-up shape, ready return, and clean exit; the
  fix also repaired a live-path parser gap where deltas carrying both content
  and tool_calls dropped the tool call (unit tests had fed events directly).
  The clarify question surface and the real Hermes tool-result content remain
  unobserved and are not reproduced.
- HAD-120 observes the clarify question surface interaction in OBS-0116: the
  surface renders question and choice markers after [DONE], ArrowDown/ArrowUp
  navigation keeps the surface alive without submitting, and Enter on the
  first choice closes it and produces the follow-up answer. The real Hermes
  tool-result content is a 158-byte JSON string with top-level keys
  `question`, `choices_offered`, `user_response` (digest `7336fd6d…`, stable
  across fresh runs and unaffected by the harness environment fix). The
  follow-up request shape (system, user, assistant with tool call, tool role)
  and the auxiliary non-stream request match OBS-0114. The observation also
  fixed a probe-harness environment leak: running from inside the Hermes
  desktop app leaked `HERMES_DESKTOP` and `PYTHONPATH` into the reference
  child, drifting the advertised tool inventory from the anchored 31 to 35
  tools and shadowing pinned module schemas; `safe_environment` now strips
  both so observations match the plain-CLI reference environment. The Hades
  question surface and the real tool-result shape remain unimplemented; the
  observation establishes the interaction and content contract without
  turning it into execution, approval, or forwarding behavior.
- HAD-122 gives the Hades startup surface its own owner-directed identity and
  fixes a tall-terminal rendering bug. The product-owned startup frame now
  renders a HADES AGENT logo, the `☠ Hades · Lord of the Digital Underworld`
  tagline, `Hades Agent v0.1.0 (2026.8.3)` title, and `mock-model · Hades`
  provider line, replacing the Hermes branding; the unconfigured model line
  reads `glm-5.2 · Hades`. This is a deliberate, documented deviation from the
  OBS-0001 reference frame (layout/geometry parity is preserved; Hades-facing
  replay markers and the differential golden were updated to the product-owned
  Hades frame). The bug fix stops the startup body copy before the template's
  own footer/composer rows, so terminals taller than 40 rows no longer show a
  duplicated footer and prompt mid-screen; the standalone setup wizard
  surfaces keep their captured Hermes reference text and fixtures. A
  follow-up owner-directed visual pass (2026-08-04) replaced the in-box
  skull braille glyph with a Baphomet-style goat-head-with-horns braille
  logo and realigned every box row to exactly 117 characters so the right
  border lands at column 116 on all rows (rows 11/26/27 were short, row 28
  overflowed the box — the latter inherited from the Hermes template);
  the unconfigured model line constant was realigned to match. A further
  owner-directed pass replaced the ANSI Shadow text logo with the
  heavy-metal dripping-gothic `sblood` figlet font for the HADES AGENT
  wordmark (rows 1–5), keeping the layout and style-marker rows stable.
  A further owner-directed pass (same day) made the in-box logo an
  ANIMATED demon-skeleton-with-pitchfork: four braille frames cycle with
  the TUI tick (frame 0 equals the static asset, so snapshots and the
  golden test stay deterministic), and swapped the bottom rows so the
  composer sits ABOVE the information line (composer at height-2, info
  line at height-1) — a deliberate deviation from the Hermes reference
  layout, documented in MATRIX.md. Because the animation interleaves
  sparse-redraw cells into the raw PTY stream (fragmenting typed text),
  the replay harnesses now wait on the RENDERED screen (Screen emulator)
  instead of raw-byte markers.
- ADR-0008 records the owner direction that Hades Agent is entirely Rust,
  including development tooling, and HAD-123 begins the migration: a new
  `hades-dev` workspace crate hosts the shared harness primitives that every
  probe and replay depends on. The Rust ANSI screen emulator (`Screen`,
  `Cell`, `Style`, SGR parsing) and PTY spawn/control harness are faithful
  ports of the Python harness, verified by a differential parity check
  (`scripts/check_screen_parity.py`, wired into `verify-fast`) that feeds
  live Hades PTY output through both the Python and Rust screen models and
  requires identical lines, style inventory, and marker styles. The
  differential check caught two real semantic differences during the port
  (braille is narrow per Unicode East Asian Width, and marker lookup must
  convert byte indices to char indices), fixing them before the Rust harness
  was wired into the gate. Fixture validation (HAD-124) and the control
  plane (HAD-125) migrate in subsequent phases.
- HAD-124 ports the reference fixture validator to Rust as the
  `hades-dev validate-fixture` subcommand. It enforces the identical
  contracts as `scripts/validate_reference_fixture.py` — schema_version,
  provenance (40-char lowercase source_commit, positive terminal geometry),
  normalization/unknowns string lists, non-empty steps with unique ids,
  input-event shapes (wait vs bytes_hex), and the credential scan including
  the `sk-` token-boundary regex. A differential check
  (`scripts/check_fixture_parity.py`) proves both validators agree on all
  111 checked-in fixtures (identical exit codes and JSON summaries), then
  the gate validates every fixture through the Rust binary; the Python
  validator remains in the gate until the migration's final phase retires
  it.
- HAD-125 ports the development control plane to Rust as the
  `hades-dev control-plane` subcommand, replacing `scripts/agent/control_plane.py`
  for `just agent` and the gate. It reproduces all seven commands
  (validate, next, show, claim, complete, block, cancel) with identical JSON
  output and validation errors, flock-based exclusive locking with an
  atomic temp-file replace, dependency promotion of queued tasks, and
  eligibility ordering by priority then id. A parity check
  (`scripts/check_control_plane_parity.py`) proves identical
  validate/next/show output and identical error paths on the live ledger;
  `just agent` and `verify.sh` now delegate to the Rust binary. 8 focused
  unit tests cover validation rules, promotion, cycle detection, and the
  UTC timestamp format.
- HAD-126 ports the shared replay runtime to Rust
  (`hades-dev::replay`): the helpers every Python replay imports from
  `probe_tui_lifecycle` — spawn-with-arguments on a 120x40 PTY with the
  standard environment, slave-path resolution via /proc, retained slave
  descriptors for termios inspection, terminal flags (canonical/echo),
  ANSI-stripped clean output, compact marker matching, wait_for with
  early-exit detection, wait_for_exit with describe_status-shaped exit
  values, output tails, and send. A differential parity check
  (`scripts/check_replay_runtime_parity.py`, wired into `verify-fast`) proves
  the Rust runtime agrees with the Python helpers on clean output, marker
  matching, and real-subprocess exit shapes; 8 focused unit tests cover the
  same behaviors against live subprocesses.
- HAD-127 ports the first replay to Rust: `hades-dev replay-cli-launch`
  reproduces `replay_cli_launch.py` — no-argument and explicit-tui launch
  forms, startup landmarks, raw-mode flags, alternate-screen enter/leave
  sequences, Ctrl+C exit status, and terminal restoration, with the same
  report JSON shape (`probe`, `binary`, `dimensions`, `cases`, `passed`).
  A differential check (`scripts/check_cli_launch_parity.py`, wired into
  `verify.sh` and `just replay-cli-launch`) proves the Rust and Python
  replays produce identical reports on the same binary; the Rust binary is
  now the gate replay.
- HAD-128 ports the unconfigured startup replay to Rust:
  `hades-dev replay-unconfigured-startup` reproduces
  `replay_unconfigured_startup.py` — provider-env stripping, unconfigured
  markers (`glm-5.2 · Hades`, `starting agent`), absent ready footer and
  prompt placeholder, raw mode, alternate-screen sequences, and Ctrl+C
  exit, with the same report JSON shape. A differential check
  (`scripts/check_replay_parity.py`) proves the Rust and Python replays
  produce identical reports on the same binary; the Rust binary is now the
  gate replay.
- HAD-129 ports the unconfigured input replay to Rust:
  `hades-dev replay-unconfigured-input` reproduces
  `replay_unconfigured_input.py` — queued input during unconfigured
  startup with the `❯ queued hello` composer marker, first Ctrl+C clearing
  the draft while keeping the process alive, second Ctrl+C exiting
  cleanly, and the empty-startup exit case, with the same report JSON
  shape (schema_version/probe/binary/dimensions/cases/passed). A
  differential check (`scripts/check_replay_parity.py`) proves the Rust and
  Python replays produce identical reports on the same binary; the Rust
  binary is now the gate replay.
- HAD-130 ports the delayed unconfigured /help route to Rust:
  `hades-dev replay-unconfigured-help` reproduces
  `replay_unconfigured_help.py` — /help retained during the 8000ms
  pre-delay window, the delayed Setup Required overlay with
  /model//setup/Ctrl+C, bounded transition timing (7000–11000ms), first
  Ctrl+C clearing the overlay without exiting, second Ctrl+C exiting
  cleanly, and the stable-terminal-flags retry on the post-exec ioctl race
  (errno 25). The report matches the Python shape; the differential check
  normalizes the two run-to-run timing fields (`pre_delay_ms`,
  `observed_transition_ms`) while both replays assert the same bounds. The
  Rust binary is now the gate replay for the debug binary and both
  installed launchers.
- HAD-131 ports the configured vertical-slice replay to Rust:
  `hades-dev replay-vertical-slice` reproduces
  `replay_vertical_slice.py` — `hades setup --local <loopback-url>
  vertical-model` persisting a sanitized local-provider sidecar (no
  config.yaml, no persisted credential), a fresh TUI process reaching
  ready without re-running setup, one streamed provider request to the
  in-process loopback SSE server (first delta visible before completion,
  final answer held until release), the sanitized-boundary request
  assertions (no Authorization header, exact path/content-type, persisted
  model, system/user roles, delivered prompt), and a clean Ctrl+C exit
  with terminal restoration. The report matches the Python shape; the
  differential check proves identical reports on the same binary. The Rust
  binary is now the gate replay (verify.sh + justfile); the Python replay
  stays until the final migration phase retires it.
- HAD-132 ports the configured-family runtime extensions to Rust:
  `hades_dev::hold_provider` (loopback server holding an accepted provider
  request until release, with the `HADES_PROVIDER_BASE_URL`/`HADES_MODEL`/
  `HADES_PROVIDER_API_KEY` environment helper) and `hades_dev::tmux`
  (new-session/send-keys/capture-pane/has-session/kill-session lifecycle,
  `wait_for_screen`, and the LOWERCASE `contains_marker` variant distinct
  from `replay::marker_present`). A differential check
  (`scripts/check_tmux_hold_parity.py` + `hades-dev tmux_hold_diff`) proves
  the Rust helpers agree with `replay_composer.py` on marker matching, key
  payloads, real tmux session lifecycle, and hold-provider request gating;
  wired into `just verify`.
- HAD-133 ports the composer replay to Rust:
  `hades-dev replay-composer` reproduces `replay_composer.py` — contract
  loading and validation (OBS-0011 editing/history/multiline, OBS-0037
  unknown slash command), hold-provider-backed tmux sessions per case,
  text/key/paste input, pty_markers/pty_absent_markers screen assertions,
  and the same report JSON shape (checks with per-step observed/absent).
  The differential check proves identical reports on the default contract
  and the OBS-0037 reports match byte-for-byte; the Rust binary is now the
  gate replay for both verify.sh invocations.
- HAD-134 ports the input-history replay to Rust:
  `hades-dev replay-history` reproduces `replay_history.py` — restart
  recall (history written by one process recalled by a fresh one),
  duplicate suppression (consecutive duplicate drafts leave the file
  unchanged), multiline readback (paste persists as one record per line),
  and the newest-1,000 load cap against a seeded history file, with the
  same report JSON shape (checks with per-step observed records). The
  differential check proves identical reports on the same binary; the Rust
  binary is now the gate replay.
- HAD-135 ports the terminal-palette replay to Rust:
  `hades-dev replay-terminal-palette` reproduces
  `replay_terminal_palette.py` — the OBS-0035 step contract (startup /
  composer / busy / interrupted / setup-required) against a direct-PTY
  Hades process behind the hold provider, landmark marker styles and
  required SGR sequences per surface, raw-delta sha256/byte-length/SGR
  sequence inventory, and the same report JSON shape. The palette's
  `normalized` (with charset-sequence stripping) and case-insensitive
  `contains_marker` variants are ported alongside the Screen model; the
  wait loop uses poll-based reads (like Python's select) so the raw-delta
  boundary matches exactly. The differential check proves identical
  reports; the Rust binary is now the gate replay.
- HAD-136..HAD-139 port the composer-family wrapper replays to Rust:
  `hades-dev replay-completion` (OBS-0012 slash completion),
  `replay-clipboard` (OBS-0015 empty clipboard), `replay-paste`
  (OBS-0013 bracketed paste), and `replay-editor` (OBS-0014 editor
  handoff, with the deterministic `EDITOR=/bin/true` the Python replay
  injects). The shared composer machinery moved into
  `hades_dev::composer` (load_contract / run_case with an environment
  override / emit_report / arg parsing), so each wrapper is a thin main.
  Differential checks prove identical reports on the same binary; the
  Rust binaries are now the gate replays.
- HAD-140..HAD-143 port the setup-family replays to Rust:
  `hades-dev replay-setup-wizard` (OBS-0041), `replay-setup-provider`
  (OBS-0045, emitting the Python's exact `replay-setup-provider` command
  name), `replay-setup-provider-model-prompt` (OBS-0047), and
  `replay-setup-terminal-backend` (OBS-0049 + OBS-0057). The shared
  machinery lives in `hades_dev::setup`: fixed loopback provider base
  URL (no hold provider), the small setup key set, sanitized
  `<hades-binary>` report field, and required `--contract`.
  `check_replay_parity.py` now forwards extra args (e.g. `--contract`)
  to both replays. Differential checks prove identical reports on the
  same contracts; the Rust binaries are now the gate replays.
- HAD-145 ports replay_modified_enter to Rust: `hades-dev
  replay-modified-enter` reproduces the OBS-0021 contract in a direct
  120x40 PTY with the hold-provider loopback — hex byte input sequences
  (whitespace-tolerant like Python's bytes.fromhex), shift-Enter /
  alt-Enter submit from ready while plain Enter does not, Ctrl+C
  interrupt/exit waits on the child. The differential check proves
  identical reports; the Rust binary is now the gate replay.
- HAD-144 ports replay_editor_outcomes to Rust: `hades-dev
  replay-editor-outcomes` reproduces the OBS-0019 contract in tmux with a
  per-case deterministic `EDITOR` (perl edits submit the modified draft,
  empty/cancelled editor results keep the original), asserts screen
  markers, reads `.hermes_history` back, and interrupts/exits. The
  differential check proves identical reports (5 cases); the Rust binary
  is now the gate replay.
- HAD-146 ports replay_model_picker to Rust: `hades-dev replay-model-picker`
  reproduces the OBS-0039 model-stage contract through `hades_dev::setup`
  (the setup-family key set already covers Escape). The differential check
  proves identical reports; the Rust binary is now the gate replay.
- HAD-154 ports replay_installed_model_selection to Rust: `hades-dev
  replay-installed-model-selection` reproduces the installed-launcher
  model-selection wrapper (both ~/.local/bin spellings resolve to
  target/release/hades; each alias runs the model-selection replay and
  must stay inside the persisted sidecar boundary — palette-model
  selected, vertical-model on a fresh process, 2 requests, sidecar
  unchanged, no Hermes config.yaml; accepts an ignored `--binary` for
  parity compatibility). The differential check proves identical reports
  (6 cases); the Rust binary is now the gate replay.
- HAD-153 ports replay_fresh_shell_launch to Rust: `hades-dev
  replay-fresh-shell-launch` reproduces the fresh Bash/Fish resolution
  and installed-TUI lifecycle replay (command -v/--version/--help
  through the installed launcher symlinks, raw-mode startup, Ctrl+C
  clean exit, alternate-screen and terminal restoration; accepts an
  ignored `--binary` so the parity checker can compare both sides). The
  differential check proves identical reports; the Rust binary is now
  the gate replay.
- HAD-151 ports replay_configured_surfaces to Rust: `hades-dev
  replay-configured-surfaces` reproduces the OBS-0090 configured primary
  surfaces replay (4 steps through the hold-provider loopback: setup,
  slash-completion/model-overlay/sessions-overlay without provider
  requests, history up/down and persistence, history recall after
  restart verified by request, Ctrl+V clipboard insertion through a
  synthetic xclip, config.yaml boundary). The differential check proves
  identical reports (4 cases); the Rust binary is now the gate replay.
- HAD-152 ports replay_conversation_context to Rust: `hades-dev
  replay-conversation-context` reproduces the OBS-0092 conversation
  lifecycle contract (multi-turn request shape, failed-turn isolation)
  through the hold-provider loopback; the differential check proves
  identical reports (2 cases); the Rust binary is now the gate replay.
- HAD-170 ports replay_tool_call_deltas to Rust: `hades-dev
  replay-tool-call-deltas` reproduces the synthetic tool-call stream
  contract (assistant role delta, tool-call fragments with JSON-encoded
  arguments, finish_reason tool_calls, DONE, then a bounded follow-up
  answer; no tool execution) through the loopback provider. The
  differential check proves identical reports (1 case); the Rust binary
  is now the gate replay.
- HAD-156 ports replay_local_provider_timing to Rust: `hades-dev
  replay-local-provider-timing` reproduces the OBS-0053 delayed-delta and
  cancellation contract with a release-gated loopback server (first delta
  held until release): delayed-delta-order renders both deltas in order
  with a clean exit; interrupt-before-completion cancels the socket
  (server observes connection close, the second delta never renders, a
  second Ctrl+C exits). The differential check proves identical reports
  (2 cases); the Rust binary is now the gate replay.
- HAD-155 ports replay_local_provider to Rust: `hades-dev
  replay-local-provider` reproduces the OBS-0051 local-provider stream
  contract (3 cases) through the hold-provider loopback; the differential
  check proves identical reports; the Rust binary is now the gate replay.
- HAD-158 ports replay_osc52_clipboard to Rust: `hades-dev
  replay-osc52-clipboard` reproduces the bare-SSH OSC52-first clipboard
  contract (OBS-0025 legacy pair and the OBS-0027 response-boundary
  family) in a direct PTY: Ctrl+V emits the OSC52 query then a DA1
  barrier; a usable OSC52 response wins before the native xclip provider
  while malformed/empty responses and DA1-acknowledged timeouts fall
  back to it. The differential checks prove identical reports on both
  contracts (2 and 5 cases); the Rust binary is now the gate replay.
- HAD-157 ports replay_model_selection to Rust: `hades-dev
  replay-model-selection` reproduces the Python live loopback replay of
  session-scoped model selection (picker request boundary, fresh-process
  nonpersistence, no fixture contract — a direct behavioral replay); the
  differential check proves identical reports (3 cases); the Rust binary
  is now the gate replay.
- HAD-150 ports replay_configured_help_resize to Rust:
  `hades-dev replay-configured-help-resize` reproduces the OBS-0102
  configured /help geometry contract at 120x40, 100x30, and 160x50
  (PTY master+slave resize with SIGWINCH): the bordered panel floats
  above the composer (composer at rows-2, panel top at rows-5 — the
  owner-directed layout), the composer draft survives each resize, and a
  clean Ctrl+C exit restores the terminal. A shared `pty::resize_pty`
  helper was added. The differential check proves identical reports
  (1 case); the Rust binary is now the gate replay.
- HAD-149 ports replay_configured_help_lifecycle to Rust:
  `hades-dev replay-configured-help-lifecycle` reproduces the OBS-0100
  configured /help Escape lifecycle: /help opening the stable bordered
  panel, Escape preserving the panel and the /help composer with the
  process alive, and a clean Ctrl+C exit with terminal restoration. The
  differential check proves identical reports (1 case); the Rust binary
  is now the gate replay.
- HAD-148 ports replay_configured_help to Rust: `hades-dev replay-configured-help`
  reproduces the OBS-0098 configured /help panel contract in a direct
  120x40 PTY against an absent loopback endpoint: /help opening the stable
  bordered command row (3 consecutive identical samples), main-surface
  landmarks still rendered, no setup-required state, and a clean Ctrl+C
  exit with terminal restoration. The differential check proves identical
  reports (1 case); the Rust binary is now the gate replay.
- HAD-147 ports replay_clipboard_text to Rust: `hades-dev replay-clipboard-text`
  reproduces the OBS-0023 successful-text clipboard contract in a direct
  120x40 PTY with a synthetic xclip provider (records argv to a log, echoes
  the fixture payload): seed text typed into the composer, Ctrl+V (raw 0x16)
  pasting the payload, rendered-screen marker waits (clip-one/clip-two and
  the empty-provider control's `No image found in clipboard`), the provider
  argument log matching `-selection clipboard -out`, and a clean Ctrl+C exit
  from ready. The differential check proves identical reports (2 cases); the
  Rust binary is now the gate replay in verify.sh and the justfile.
- The provider transport now decodes HTTP `Transfer-Encoding: chunked`
  streams (local providers like Ollama frame SSE bodies in chunks; the
  parser previously surfaced chunk-size lines as `malformed provider SSE`)
  and waits up to 120s for response headers (cold local model loads take
  tens of seconds before the first byte). Regression oracle:
  `local_transport_parses_chunked_transfer_encoding_streams`.

Parity policy: Hermes observations establish the intended compatibility
contract, not bugs to preserve. Hades must not intentionally rebuild Hermes
defects, unsafe behavior, or failure cases; fix them and record any deliberate
evidence-backed deviation.

## Unknown until observed

- Hermes TUI typography, the unobserved keymap/focus surfaces, copy, error
  states, timing, history write failures/clearing, and the remaining
  interaction surfaces. Hades styling parity remains limited to the named
  deterministic palette subset.
- Which Hermes behaviors are stable contracts versus implementation details;
  session recovery remains unobserved beyond input-history persistence.
- Hades provider/model streaming and tool calls beyond the bounded HAD-053 /
  HAD-054 / HAD-055 / HAD-057 / HAD-115 / HAD-117 seams; tool approval,
  execution, results, retries, non-loopback providers, HTTPS, and
  provider discovery remain unimplemented. Hermes
  subsequent chat-request purpose, exact provider-error copy, retry/backoff
  policy, and terminal-dependent surfaces beyond the captured observations
  remain unknown.
- The complete slash-command catalog and argument semantics, provider/model
  discovery details, setup wizard continuation, numbered-fallback choices,
  terminal-backend selection and cancellation after deeper navigation, provider
  configuration beyond the bounded OBS-0055/OBS-0056 readbacks, backup
  semantics, Hades successful provider-config persistence, credential handling,
  platform setup beyond the bounded picker, standalone platform continuation,
  configured command
  behavior with a reachable provider, and model-picker behavior beyond the
  bounded deterministic provider/model seam.
- OSC52 behavior outside the OBS-0032 timing controls and bounded payload
  sizes, including a universal timeout or maximum-size contract.

Unknowns are deliberate. The first product task is to capture the reference
contract rather than let the scaffold become an accidental specification.

## Working vocabulary

- **Reference** — the Hermes TUI build and environment used for a specific
  observation.
- **Observation** — a provenance-bearing record of one reference interaction.
- **Trace** — ordered inputs and observable outputs that can be replayed.
- **Golden frame** — a normalized terminal buffer snapshot used as a visual
  oracle.
- **Parity claim** — a statement backed by an observation and an executable
  Hades oracle.
- **Unknown** — a behavior not yet observed or not stable enough to claim.

## Non-goals for the scaffold

The bootstrap application still does not pretend to implement Hermes behavior
that has not been captured. It provides the seams needed to add that behavior
safely: typed events, a reducer, deterministic rendering, snapshot output, task
dependencies, and proof-required task completion.
