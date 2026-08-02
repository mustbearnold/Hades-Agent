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
  HAD-054 / HAD-055 / HAD-057 seams; retries, tool execution, non-loopback
  providers, HTTPS, and provider discovery remain unimplemented. Hermes
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
