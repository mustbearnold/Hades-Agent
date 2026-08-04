# SDD Migration Report — Hades Agent

**Started:** 2026-08-05 (night session)
**Protocol:** `SDD_MIGRATION.md` (dropped into repo root by owner)
**Execution decision:** owner-directed **verbatim** execution, overriding
conflicts with the previous AGENTS.md constitution (recorded below).

---

## Stage assessment

**LATE** — mature Rust codebase (58 Rust files, 6 crates, ~237 workspace
tests), extensive parity evidence pipeline, and accumulated governance
documentation. The repo was already spec-driven under its own vocabulary
(PRODUCT_SPEC.md, ADR-*, .hades/tasks.json control plane, parity ledger);
this migration converts that vocabulary into the SDD canonical structure
(`specs/`, `docs/`).

## Toolchain findings

| Concern | Finding |
|---|---|
| Language | Rust (edition 2024), workspace of 6 crates (`hades-core`, `hades-app`, `hades-tui`, `hades-cli`, `hades-provider`, `hades-dev`) |
| Build | `cargo build --locked` (Cargo.lock committed) |
| Tests | `cargo test --workspace --all-targets` (237 tests) |
| Lint | `cargo clippy -- -D warnings` |
| Format | `cargo fmt` (rustfmt, edition 2024) |
| Task runner | `just` (justfile) |
| Gate | `just verify` (control plane validate → fmt → build → clippy → tests → parity replays → reference probes) |
| Python harness | 3.11, `scripts/` (probes/replays/parity oracles — being migrated to Rust, ADR-0008) |
| Editor | `.editorconfig` at root |

## Inventory (444 tracked files)

| Class | Count | Notes |
|---|---|---|
| CODE | 58 | Rust: crates/hades-*/src/** |
| TEST | 4 | Rust test modules inside crates |
| TEST-REPLAY | 45 | `scripts/replay_*.py` — migration frontier (HAD-147+) |
| TEST-ORACLE | 5 | `scripts/check_*_parity.py` — differential gate citizens |
| ASSET-FIXTURE | 111 | `tests/fixtures/parity/*.json` — frozen reference fixtures |
| DOC-FROZEN | 171 | `docs/parity/observations/*` (115) + `scripts/probe_hermes_*.py` (48+) — captured provenance, immutability law |
| DOC-ADR | 7 | `docs/decisions/ADR-*.md` |
| DOC | 17 | sentence-able docs (Phase 3) |
| CONFIG | 20 | Cargo.toml/Cargo.lock, .github, .editorconfig, .gitignore, .gitattributes, control plane |
| UNKNOWN→CONFIG | 6 | shell scripts (verify.sh, install_user_launcher.sh, etc.) — all config/tooling |

## Owner override (recorded per protocol)

The previous AGENTS.md constitution required stopping before broad cleanup
and before changing the authority model. The owner explicitly directed
**verbatim** execution, including:
- replacing `AGENTS.md` with the SDD entry-point (Phase 4);
- attic-ing or merging frozen-evidence docs (`docs/parity/observations/`,
  `scripts/probe_hermes_*.py`) per Phase 3's three-fates rule where they fit
  no doc category;
- applying the `sdd(phase-N)` commit convention.

Protocol invariants still honored: git checkpoint per phase, only committed
files deleted (untracked → `_attic/`), never touch secrets/credentials/
licenses/.git, don't break the build, attic-not-delete when uncertain.

## Phase checklist

- [ ] Phase 1 — snapshot + inventory + this report
- [ ] Phase 2 — purge junk, quarantine ambiguity, fortify .gitignore
- [ ] Phase 3 — extract specs, sentence docs, thin README, BACKLOG
- [ ] Phase 4 — constitution, conventions, AGENTS.md
- [ ] Phase 5 — mechanical formatting, no logic changes
- [ ] Phase 6 — verify checklist, finalize report, seal, delete protocol file
