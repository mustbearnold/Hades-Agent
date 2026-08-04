# Reference reconciliation: OBS-0097

- Subject: Hermes empty-platform confirmation re-observation
- Reference: Hermes Agent 0.19.1 / `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Provenance: official [NousResearch/hermes-agent repository](https://github.com/NousResearch/hermes-agent), pinned to the source commit above
- Terminal: fresh 120x40 direct PTY with a redacted ANSI screen model and frozen dependency environment
- Historical boundary: [OBS-0058](OBS-0058-hermes-empty-platform-confirmation-2026-08-02.md)
- Fixture: `tests/fixtures/parity/OBS-0097-hermes-empty-platform-reconciliation.json`
- Probe: `scripts/probe_hermes_empty_platform_confirmation.py`
- Task: HAD-102

## Re-observed boundary

The same bounded setup route reached the platform picker with every platform
unselected. Pressing Enter changed neither the normalized config shape nor the
artifact classes, and the process remained alive. Unlike the earlier OBS-0058
capture, the current pinned-runtime run reached a stable later `Tools for`
configuration surface during the finite observation window instead of leaving
the platform picker unchanged.

The probe now records the first repeated stable outcome: either the historical
same-platform picker or a later setup surface. The later surface is retained
only through redacted stable markers such as `Tools for`, `ENTER confirm`,
`Web Search & Scraping`, and `Browser Automation`. A fresh process remains
loadable and clean terminal restoration is verified.

## Reconciliation and safety boundary

OBS-0058 remains checked in as the earlier evidence and is not silently
rewritten. OBS-0097 records the contradictory current observation explicitly;
the difference may be a timing-sensitive Hermes defect or an environment-level
variation and is not promoted into a Hades requirement without further work.

Hades keeps its typed empty-platform confirmation no-op. It does not start
implicit installers, provider adapters, credentials, OAuth, network activity,
or unobserved tool configuration merely to match this reference transition.

## Linked artifacts

- Sanitized fixture: `tests/fixtures/parity/OBS-0097-hermes-empty-platform-reconciliation.json`
- Reusable direct-PTY probe: `scripts/probe_hermes_empty_platform_confirmation.py`
- Historical fixture: `tests/fixtures/parity/OBS-0058-hermes-empty-platform-confirmation.json`
- Historical observation: `OBS-0058-hermes-empty-platform-confirmation-2026-08-02.md`
- Parity matrix: `docs/parity/MATRIX.md`
- Task ledger: `.hades/tasks.json`
