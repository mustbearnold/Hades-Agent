# ADR-0003: Bounded autonomous development

- Status: accepted
- Date: 2026-08-01

## Context

The project is intended to be developed by AI agents across a long horizon.
Autonomy needs durable state, dependency-aware work selection, and a reliable
way to distinguish completion from a blocked external dependency.

## Decision

Keep a checked-in task ledger at `.hades/tasks.json`. Tasks have typed lanes,
dependencies, required oracle kinds, explicit owners, and evidence paths. The
control-plane script validates the graph, claims work with an agent lease, and
refuses completion without existing evidence.

Agent roles are narrow and documented under `.agents/roles/`. The project gate
is a single deterministic command (`just verify`) that every role can invoke.
No background daemon, network service, or credential is required for the local
development loop.

## Consequences

Task state changes are part of the development history and should be committed
with the work they describe. Stale leases and blocked tasks are visible rather
than silently lost. External orchestration can call the same control-plane
commands without granting the repository a broader authority model.
