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
  boundaries in a synthetic direct PTY. Live multiplexer/outer-terminal
  forwarding, delayed/oversized responses, image attachments, and gateway
  behavior remain unknown; Hades wrapper parity is the next implementation task.

## Unknown until observed

- Hermes TUI color palette, typography, the unobserved keymap/focus surfaces,
  copy, error states, timing, history write failures/clearing, and the remaining
  interaction surfaces.
- Which Hermes behaviors are stable contracts versus implementation details;
  session recovery remains unobserved beyond input-history persistence.
- Successful provider/model streaming, tool calls, and the exact behavior of
  terminal-dependent surfaces beyond the captured observations.

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
