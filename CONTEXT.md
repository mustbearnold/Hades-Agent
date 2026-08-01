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

## Unknown until observed

- Hermes TUI typography, the unobserved keymap/focus surfaces, copy, error
  states, timing, history write failures/clearing, and the remaining
  interaction surfaces. Hades styling parity remains limited to the named
  deterministic palette subset.
- Which Hermes behaviors are stable contracts versus implementation details;
  session recovery remains unobserved beyond input-history persistence.
- Successful provider/model streaming, tool calls, and the exact behavior of
  terminal-dependent surfaces beyond the captured observations.
- The complete slash-command catalog and argument semantics, provider/model
  discovery details, setup wizard continuation, numbered-fallback choices,
  cancellation after deeper navigation, provider configuration, backup
  semantics, and persistence, configured command
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
