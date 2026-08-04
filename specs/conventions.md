# Conventions

## Documents (Markdown)

- ATX headings (`#`), exactly one H1 per file (the title), sentence case.
- Blank line before and after headings, lists, and code fences.
- Code fences always declare a language.
- No hard line-wrapping inside paragraphs; let editors soft-wrap.
- Tables only for genuinely tabular data; otherwise lists or prose.
- Relative links only within the repo. Kebab-case filenames:
  `spec-extraction.md`.
- Specs live at `specs/NNN-<slug>/spec.md` with the template in
  `specs/constitution.md`'s source protocol; docs live in `docs/` as
  architecture, decisions (ADRs), or runbooks — no fourth category.

## Code

Formatter output is law. Never hand-format; never argue with the formatter.

| Language | Formatter  | Linter   |
| -------- | ---------- | -------- |
| Rust     | cargo fmt  | clippy (workspace, `-D warnings`) |
| Python   | (harness; migrated to Rust per spec 009) | — |
| Shell    | —          | bash -n  |
| JSON/YAML | —        | —        |

Configs are committed. `.editorconfig` at root sets charset/indent/EOL for
everything else.

## Commits

`type(scope): imperative summary` — types: feat, fix, refactor, docs, test,
chore, sdd. One logical change per commit. Formatting commits contain no
logic.

## Naming

Docs and spec slugs: kebab-case. Code identifiers: the language's standard.
Spec/ADR numbers: zero-padded, never reused.

## Gate

The single complete local gate is `just verify`: control plane validation →
formatting → compilation → clippy (`-D warnings`) → tests → parity replays →
reference probes. Never hide failures with skips, weakened assertions, or an
unrecorded environment exception.
