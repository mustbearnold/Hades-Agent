# Hades implementation contract: OBS-0012

- Subject: Hades slash-completion implementation slice
- Reference evidence: Hermes OBS-0010 at commit `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Terminal: tmux-backed PTY at 120x40
- Task: HAD-012
- Contract fixture: `tests/fixtures/parity/OBS-0012-hades-slash-completion.json`
- Executable oracle: `scripts/replay_completion.py`

OBS-0010 observed Hermes showing `/help`, `/hermes-agent`, and
`/hermes-agent-skill-authoring` after typing `/he`, followed by Tab applying
`/help`. This Hades contract keeps that slice deliberately narrow and
deterministic: the panel is derived only for the exact ready-state `/he` draft,
and the first item is applied by Tab.

The panel is rendered as stable text landmarks at the captured 120x40 size.
The replay also proves that Tab is consumed by completion before the existing
surface-cycle fallback, that the applied composer line is `❯ /help`, and that
the remaining completion item disappears.

This task does not claim an asynchronous completion gateway, debounce timing,
completion ordering outside the captured list, completion in multiline or
busy contexts, path or skill completion, or arrow-key selection. Those remain
unknown until separately observed.

## Linked artifacts

- [Reference observation](OBS-0010-hermes-input-editing-keymap-2026-08-01.md)
- [Hades completion contract](../../../tests/fixtures/parity/OBS-0012-hades-slash-completion.json)
- [Completion replay](../../../scripts/replay_completion.py)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
