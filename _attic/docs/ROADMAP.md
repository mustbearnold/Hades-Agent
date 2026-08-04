# Roadmap

This is a behavior-led roadmap. A stage is complete only when its evidence is
recorded and its gates are green; elapsed time or code volume is not completion.

## Stage 0 — Evidence substrate

- establish the reference build and capture environment;
- define sanitized trace and terminal-frame formats;
- record unknowns and normalization rules;
- keep the control plane self-validating.

## Stage 1 — Lifecycle parity

- terminal ownership and restoration;
- startup and exit behavior;
- interrupt and resize handling;
- deterministic lifecycle probes.

## Stage 2 — Interaction parity

- keymap and focus model;
- navigation and command routing;
- input editing and submission;
- errors, cancellation, and retry semantics.

## Stage 3 — Visual parity

- frame geometry and responsive layout;
- typography, colors, borders, and cursor state;
- streaming and transient states;
- golden-frame differential reports.

## Stage 4 — Integration parity

- persistence and configuration;
- model/provider/tool boundaries;
- recovery and background work;
- performance and resource budgets.

## Stage 5 — Release readiness

- supported environment matrix;
- reproducible packaging;
- upgrade and rollback behavior;
- release evidence and owner approval for publication.
