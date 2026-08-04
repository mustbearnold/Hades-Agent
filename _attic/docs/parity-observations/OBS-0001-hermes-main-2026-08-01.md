# Reference observation: OBS-0001

- Reference product: Hermes TUI
- Reference version/commit: Hermes Agent 0.19.1 / `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Displayed build: `v0.19.1 (2026.7.30)`
- Host/OS: CachyOS Linux, kernel `6.18.40-1-cachyos-lts`
- Terminal emulator: tmux-backed PTY
- Terminal dimensions: 120x40 startup capture; resized to 100x30
- Capture method: live TTY execution with `tmux capture-pane -p`
- Captured at: 2026-08-01T01:01:18+00:00
- Sanitization: ANSI control sequences, trailing spaces, dynamic elapsed seconds, the session ID, the temporary checkout path, and the rotating prompt placeholder were normalized. No transcript payload, credential, or private Hermes state was copied.
- Source artifact: official Hermes repository at [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent), pinned to the commit above; the temporary checkout used for this run was outside the Hades repository.

## Preconditions

The reference checkout was built from the pinned commit with Node `v22.22.2`, npm `10.9.7`, Python `3.11.14`, and uv `0.12.1`. The TUI bundle was built with `npm install --ignore-scripts --no-audit --no-fund`, `npm run build:ink`, and `npm run build` from `ui-tui`. Python dependencies were installed with `uv sync --frozen --no-dev`.

The runtime command was:

```text
HERMES_HOME=<temporary synthetic home> HERMES_TUI_DIR=<temporary checkout>/ui-tui HERMES_TUI_THEME=dark HERMES_TUI_STARTUP_TIMEOUT_MS=8000 uv run hermes --tui
```

The ready-state run used a synthetic custom provider configured for `http://127.0.0.1:8765/v1`. No real provider, external network request, or user credential was used. The local endpoint was intentionally absent, so the submitted `hello` turn was observed through its busy and interrupt states rather than a model response. A separate fresh synthetic home without a provider was used for the setup-required observation.

The official [Hermes TUI guide](https://hermes-agent.nousresearch.com/docs/user-guide/tui) describes the same `hermes --tui` surface as a TTY-bound Ink/React terminal interface with a banner, composer, overlays, slash commands, and interrupt/exit keybindings. This observation records only behavior seen in the pinned executable.

## Steps

| Step | Input | Observable output | Timing/notes |
| --- | --- | --- | --- |
| 1 | Launch `hermes --tui` at 120x40 with the synthetic provider | ASCII Hermes banner; Nous Research tagline; boxed agent information panel; available tools and skills; model/provider line; working directory; session ID; `ready` status; composer prompt | Startup settled in approximately 10 seconds. See [startup golden frame](../../../tests/fixtures/parity/OBS-0001-startup-120x40.txt). |
| 2 | Type `hello` without submitting | Composer changed to `❯ hello` | Input remained in the composer. |
| 3 | Press Enter | Busy status showed face-state text including `musing…` and `mulling…`; the composer showed `Ctrl+C to interrupt…` | The intentionally absent local endpoint produced no assistant response during the observation window. |
| 4 | Press Ctrl+C during the busy turn | Transcript showed `interrupted`; status returned to `ready`; a completed elapsed marker was shown | Ctrl+C interrupted the active turn rather than exiting the TUI. |
| 5 | Press Ctrl+X | Modal `Sessions` overlay showed live/resumable counts, `+ new`, the current session, and controls for switching, creating, refreshing, and closing | The overlay was opened from the ready state. |
| 6 | Press Esc | Sessions overlay closed and the composer returned | No session switch occurred. |
| 7 | Resize the PTY from 120x40 to 100x30 | The boxed header reflowed/truncated to the narrower width while the transcript, status bar, and composer remained visible | The resize was performed with tmux and captured after one second. |
| 8 | In a fresh home without a provider, invoke `/help` | `Setup Required` overlay; message that a model provider is needed; actions `/model`, `/setup`, and Ctrl+C | The input remained `/help`; status changed to `setup required`. |
| 9 | Press Ctrl+C twice from setup-required | First press cleared the input and kept the setup-required panel; second press ended the TUI process and tmux reported the session exited | This is distinct from Ctrl+C during an active turn. |

## Contract

This observation proves the following reference behavior:

- Startup presents a branded banner, an information box, a status bar, and a composer before normal interaction.
- The ready state exposes the active model, elapsed/session status, voice state, session count, and a prompt placeholder.
- Submitting text enters an explicitly interruptible busy state.
- Ctrl+C interrupts a running turn and returns to ready; in setup-required mode, exit requires the observed two-press sequence.
- Ctrl+X opens a session-management overlay with current, new, resumable, refresh, and close affordances.
- Resizing changes the layout geometry while retaining the main interaction regions.
- A missing provider is surfaced as an actionable setup panel rather than an implicit crash.

These are observations, not implementation requirements for behaviors that were not exercised. The [official repository](https://github.com/NousResearch/hermes-agent) is the provenance anchor; the pinned commit and captured artifacts are the parity oracle inputs.

## Unknowns

- Exact truecolor values, ANSI sequences, cursor placement, and terminal-cell widths.
- Successful model streaming, partial-token rendering, tool calls, tool results, and long-running progress.
- Final error/retry rendering for provider failures and timeouts.
- The complete slash-command set and command completion behavior.
- History navigation, multiline editing, Tab completion, Ctrl+G editor behavior, mouse input, clipboard behavior, and paste handling.
- Ctrl+D, Ctrl+L, voice controls, live-session switching beyond the observed overlay, and other keybindings not exercised here.
- Session persistence and recovery across a fresh process launch.
- Behavior with real providers, other terminal emulators, non-dark themes, different fonts, and other terminal sizes.
- Setup wizard details beyond the observed setup-required actions.

## Linked artifacts

- Trace: [tests/fixtures/parity/OBS-0001-lifecycle.json](../../../tests/fixtures/parity/OBS-0001-lifecycle.json)
- Golden frame: [tests/fixtures/parity/OBS-0001-startup-120x40.txt](../../../tests/fixtures/parity/OBS-0001-startup-120x40.txt)
- Task: HAD-001
