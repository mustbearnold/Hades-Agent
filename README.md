# Hades Agent

A native Rust terminal interface that reproduces Hermes TUI with exact
behavioral and visual parity, developed by bounded autonomous AI agents with
a human prompter. The product promise is exactness: the same user action in
the same supported environment produces the same observable result as the
reference, within a documented normalization boundary.

## Quickstart

```bash
cargo build --locked
# unconfigured TUI:
./target/debug/hades
# configure a local OpenAI-compatible provider (e.g. Ollama), then run:
hades setup --local http://127.0.0.1:11434/v1 qwen3.5:9b
./target/debug/hades
```

## Specs

This repository is spec-driven. Read the constitution first, then the
capability specs:

- [specs/constitution.md](specs/constitution.md) — principles and the SDD loop (highest authority)
- [specs/conventions.md](specs/conventions.md) — formatting and style law
- [specs/001-parity-contract/spec.md](specs/001-parity-contract/spec.md) — evidence-first parity, trace format, roadmap
- [specs/002-lifecycle-and-terminal/spec.md](specs/002-lifecycle-and-terminal/spec.md)
- [specs/003-composer-and-input/spec.md](specs/003-composer-and-input/spec.md)
- [specs/004-sessions-and-transcript/spec.md](specs/004-sessions-and-transcript/spec.md)
- [specs/005-provider-transport/spec.md](specs/005-provider-transport/spec.md)
- [specs/006-setup-and-configuration/spec.md](specs/006-setup-and-configuration/spec.md)
- [specs/007-help-and-overlays/spec.md](specs/007-help-and-overlays/spec.md)
- [specs/008-autonomous-development/spec.md](specs/008-autonomous-development/spec.md)
- [specs/009-rust-migration/spec.md](specs/009-rust-migration/spec.md)
- [specs/010-hades-branding/spec.md](specs/010-hades-branding/spec.md)
- [specs/BACKLOG.md](specs/BACKLOG.md) — known-but-unspecced capabilities

For agents: read [AGENTS.md](AGENTS.md) and the constitution before any work.
