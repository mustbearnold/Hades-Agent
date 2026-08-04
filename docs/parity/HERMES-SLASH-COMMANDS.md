# Hermes Agent — Slash Commands

Every real command in Hermes Agent v0.19.0, from `hermes_cli/commands.py:COMMAND_REGISTRY`
and `ui-tui/src/app/slash/registry.ts`.

## Session

| Command | Does |
|---|---|
| `/new [name]` (`/reset`) | New session — fresh session ID, cleared history, optional title |
| `/clear` | Clear screen + start new session. In the TUI `/new` is an alias of this |
| `/resume [name]` | Load a previously-named session |
| `/sessions` | Browse/switch sessions. `new` = extra live session (current keeps running); `<id>` = load cold session and close current |
| `/branch [name]` (`/fork`) | Fork the session to explore another path |
| `/title [name]` | Set or show the session title |
| `/history [N]` | Print the conversation transcript |
| `/save` | Write the conversation to JSON |
| `/compress [here [N] \| <topic> \| --preview]` (`/compact`) | Compress context. `--preview`/`--dry-run` shows what would happen without doing it |
| `/rollback [n \| list \| diff <hash> \| <hash> [file]]` | List, diff, or restore **filesystem** checkpoints |
| `/snapshot [create\|restore <id>\|prune]` (`/snap`) | Snapshot Hermes **config/state** — different thing from `/rollback` |
| `/undo [N]` | Back up N user turns and re-prompt (default 1) |
| `/retry` | Undo the last exchange and resend your last message |
| `/queue <prompt>` (`/q`) | Queue a prompt for the next turn, no interrupt |
| `/steer <prompt>` | Inject a message after the next tool call, no interrupt |
| `/background <prompt>` (`/bg`, `/btw`) | Run a prompt in an isolated background session; result prints when done |
| `/stop` | Kill all running background processes |
| `/agents [pause\|resume\|status]` (`/tasks`) | Spawn-tree dashboard; pause/resume delegation |
| `/journey [list\|delete <id>\|edit <id>]` (`/learning`, `/memory-graph`) | Skills + memories on a timeline |
| `/goal …` | Standing goal loop (see below) |
| `/subgoal [text \| remove N \| clear]` | Extra criteria on the active goal |
| `/moa <prompt>` | Run one prompt through the Mixture-of-Agents preset, then restore your model |
| `/handoff <platform>` | Hand this session to Telegram/Discord/etc. |
| `/prompt [text]` (`/compose`) | Compose your next prompt in `$EDITOR`, then send. Same as Ctrl+G |
| `/redraw` | Force a full UI repaint |
| `/status` | Session, model, token, and context info |

**`/goal` subcommands:** bare or `status` (state line) · `show` (+ completion contract) ·
`draft <objective>` (LLM expands plain text into outcome/verification/constraints/boundaries/stop_when) ·
`pause` · `resume` · `clear`/`stop`/`done` · `wait <pid> [reason]` (park the loop until that
process exits) · `unwait`. Anything else is the goal text; inline `verify:` / `constraints:` /
`boundaries:` / `stop when:` lines get parsed into a contract. After each turn a judge model
checks completion; it keeps working until done, paused, cleared, or the turn budget runs out.

## Model & reasoning

| Command | Does |
|---|---|
| `/model [name] [--provider p] [--global\|--session] [--refresh]` | Switch model. Session-scoped by default. Bare opens a 2-stage provider→model picker. Expensive models raise a confirm dialog |
| `/reasoning [none\|minimal\|low\|medium\|high\|xhigh\|max\|ultra \| show\|hide\|full\|clamp] [--global]` | Reasoning effort and whether thinking is displayed |
| `/fast [normal\|fast\|status] [--global]` | OpenAI Priority Processing / Anthropic Fast Mode |
| `/codex-runtime [auto\|codex_app_server]` | Toggle the codex app-server runtime for OpenAI/Codex models |
| `/personality [name]` | Switch personality — may clear the transcript |

## Tools, skills, plugins

| Command | Does |
|---|---|
| `/tools [list\|enable\|disable] [name…]` | Enable/disable toolsets and MCP tools (`github:create_issue`). **Resets session history on change** |
| `/toolsets` | List available toolsets |
| `/skills [browse\|search\|inspect\|install\|list\|audit\|pending\|approve\|reject\|diff\|approval]` | Bare opens the Skills Hub. `browse` scans 6 community sources (~15s), paginated |
| `/learn <what to learn from>` | Distill a reusable skill from a directory, URL, this conversation, or pasted notes — the agent gathers material with its own tools and authors the skill |
| `/bundles` | List skill bundles (one `/name` aliasing several skills) |
| `/memory [pending\|approve\|reject\|approval] [id\|on\|off]` | Review pending memory writes; toggle the approval gate |
| `/curator [status\|run\|pause\|resume\|pin\|unpin\|restore\|list-archived]` | Background skill maintenance |
| `/plugins [enable\|disable\|list\|install] [name]` | Bare opens the Plugins Hub |
| `/reload-mcp [now\|always]` | Reload MCP servers. Confirmation-gated; `always` stops asking. Invalidates the prompt cache |
| `/reload-skills` | Re-scan `~/.hermes/skills/` and refresh the command catalog |
| `/reload` | Re-read `~/.hermes/.env` into the running gateway |
| `/browser [connect\|disconnect\|status] [url]` | Attach browser tools to a live Chromium via CDP (default `127.0.0.1:9222`) |
| `/cron [list\|add\|create\|edit\|pause\|resume\|run\|remove]` | Scheduled tasks |
| `/suggestions [accept\|dismiss N\|catalog\|clear]` (`/suggest`) | Review suggested automations |
| `/blueprint [name] [slot=value]` (`/bp`) | Set up an automation from a template |
| `/kanban <40+ subcommands>` | Multi-profile collaboration board — tasks, links, comments, dispatch |

## Display & interface

| Command | Does |
|---|---|
| `/skin [name]` | Switch theme skin |
| `/theme [auto\|light\|dark]` | Pin light/dark or trust OSC-11 auto-detection (TUI only) |
| `/indicator [kaomoji\|emoji\|unicode\|ascii]` | Busy-indicator style |
| `/details [hidden\|collapsed\|expanded\|cycle]` or `/details <section> […\|reset]` (`/detail`) | Agent detail visibility, globally or per section (`thinking`, `tools`, `subagents`, `activity`) |
| `/density [on\|off\|toggle]` | Compact display |
| `/verbose` | Cycle tool progress: off → new → all → verbose → log |
| `/statusbar [on\|off\|top\|bottom]` (`/sb`) | Status bar position |
| `/battery [on\|off\|status]` | Battery indicator in the status bar |
| `/timestamps [on\|off\|status]` (`/ts`) | `[HH:MM]` stamps on messages and `/history` |
| `/footer [on\|off\|status]` | Gateway runtime-metadata footer on final replies |
| `/mouse [on\|off\|toggle\|wheel\|buttons\|all]` (`/scroll`) | Mouse tracking preset — `wheel`/`buttons` are the tmux-friendly hover-free subsets |
| `/busy [queue\|steer\|interrupt\|status]` | What Enter does while Hermes is working. Default `interrupt` |
| `/pet [toggle\|list\|scale <n>\|<slug>]` | Animated mascot; `list` opens a picker |
| `/hatch [description]` (`/generate-pet`) | Generate a new pet from a description |
| `/fortune [random\|daily]` | Local fortune; `daily` is seeded by session ID |

## Input/output

| Command | Does |
|---|---|
| `/copy [n]` | Copy the nth assistant reply to clipboard (default last); falls back to OSC52 |
| `/paste` | Attach an image from the clipboard |
| `/image <path>` | Attach a local image for the next prompt |
| `/voice [on\|off\|tts\|status]` | Voice mode. `on`/`off` toggles recording, `tts` toggles spoken replies, `status` shows mode + record key + STT requirements. Unrecognized args fall back to `status` |
| `/terminal-setup [auto\|vscode\|cursor\|windsurf]` | Write IDE terminal keybindings for multiline + undo/redo |

## Info & account

| Command | Does |
|---|---|
| `/help` | Command catalog by category + skill count + TUI section + hotkeys. In the TUI, **Escape does not close it** |
| `/status` | Live session info |
| `/usage [reset [--force]]` | Token usage, rate limits, Nous balance. `reset` redeems a banked Codex limit reset |
| `/insights [days]` | Usage analytics |
| `/topup` | Balance and billing overlay. **No subcommands** — args ignored |
| `/subscription` (`/upgrade`) | View/change your Nous plan. **No subcommands** — args ignored |
| `/whoami` | Your platform, scope (DM vs group), tier (admin/user/unrestricted), and which slash commands you can actually run |
| `/profile` | Active profile name and home directory |
| `/config` | Show current configuration |
| `/platforms` (`/gateway`) | Gateway/messaging platform status |
| `/version` (`/v`) | Version string |
| `/debug [nous\|local]` | Upload a debug report (system info + logs), return shareable links |
| `/logs [N]` | Gateway log tail (1–80 lines, default 20) |
| `/setup` | Suspends the TUI and runs the external `hermes setup` wizard (Quick / Full / Blank Slate) |
| `/update` | Update Hermes and exit the TUI (exit code 42 tells the wrapper to run the updater) |
| `/quit` (`/exit`) `[--delete]` | Exit. `--delete` also removes session history |

## Messaging-platform only

| Command | Does |
|---|---|
| `/start` | Acknowledge a platform start ping without replying — deliberately silent |
| `/topic [off\|help\|session-id]` | Telegram DM topic-scoped sessions |
| `/approve [session\|always]` | Approve a pending dangerous command |
| `/deny [all] [reason]` | Deny a pending dangerous command |
| `/sethome` (`/set-home`) | Mark this chat as the home channel |
| `/platform <pause\|resume\|list> [name]` | Control a failing gateway platform |
| `/commands [page]` | Paginated browse of all commands and skills |
| `/restart` | Graceful gateway restart after draining active runs |

## Debug / developer (TUI)

| Command | Does |
|---|---|
| `/replay [N\|last\|list\|load <path>]` | Replay a completed spawn tree; `list` reads archived trees from disk |
| `/replay-diff <a> <b>` | Diff two spawn trees by history index |
| `/theme-info` | Dump the theme-detection chain: OSC-11 probe, env vars, detected mode, palette |
| `/mem` | Live V8 heap, rss, uptime |
| `/heapdump` | Write a V8 heap snapshot + diagnostics to `HERMES_HEAPDUMP_DIR` |
| `/widgets-reload` | Rescan `$HERMES_HOME/tui-widgets` and re-register user widget apps |
| `/grid-test [cols]x[rows]`, `/dialog-test [zone]` | Widget-grid and dialog-overlay demos |

## Not commands

`/plan` — does not exist. No definition, no handler.
`/context` — not in the CLI or TUI; exists only in the ACP adapter, where it shows message counts by role.
`/sw` — not an alias for `/sessions`. The real aliases are `switch`, `session`, `resume`.

Beyond this list, every installed skill and every widget app in `$HERMES_HOME/tui-widgets`
registers its own `/name`, and `config.yaml → quick_commands` adds user-defined ones under
"User commands" — the live catalog is always a superset of the built-ins above.
