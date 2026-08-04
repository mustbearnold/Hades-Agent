# Constitution

The highest authority in this repository. Conflicts resolve in this order:
constitution → conventions → specs → code comments.

## Principles

1. Specs are the source of truth; code exists to satisfy them. A behavior
   may move from unknown to implemented only when the four-link parity chain
   exists (observation, contract, oracle, verification record).
2. The SDD loop is mandatory for all changes: no code without a spec; a
   merged change with a stale spec is a defect; a bug is a failing
   acceptance criterion — fix both.
3. Exactness over approximation: Hades reproduces Hermes TUI within a
   documented normalization boundary; reference unknowns stay unknown until
   observed, and `blocked`/`unknown` is a valid terminal outcome — fake
   completion is not.
4. Delete freely — git remembers. Never keep dead code or stale docs "just
   in case." Structure, content, and formatting change in separate commits.
5. Secrets never enter the repo, specs, or reports. Captured evidence is
   sanitized (credentials normalized out); credentials and private runtime
   state are never read as part of orientation.
6. Work on the current branch; no PR ceremony unless the team adopts it
   explicitly. One terminal outcome per run: `complete`, `blocked`, or
   `cancelled`.
7. The project owner is the constitutional authority. An agent stops and
   reports before touching credentials, external side effects, destructive
   operations, quality-gate weakening, or the authority model itself.

## The SDD loop

1. No code without a spec. New capability → write `specs/NNN-<slug>/spec.md`
   first.
2. Spec agreed → `plan.md` (design) → `tasks.md` (checklist) → implement,
   ticking tasks.
3. If implementation diverges from the spec, update the spec in the same
   change. A merged change with a stale spec is a defect, not a chore.
4. When a capability ships and stabilizes, delete its `plan.md` and
   `tasks.md` (git remembers). `spec.md` remains as living truth.
5. A bug is a failing acceptance criterion. If the spec didn't cover it, the
   spec was wrong — fix both.
6. New document decision tree: required behavior or intent → **spec**. A
   choice among alternatives → **ADR**. How to operate it → **runbook**.
   System shape → **architecture.md**. None of these → don't write it.

## Definition of done

Tests pass · acceptance criteria met · spec updated to match reality ·
conventions followed.
