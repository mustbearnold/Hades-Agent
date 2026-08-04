# OBS-0100 — Hermes configured `/help` lifecycle

Date: 2026-08-03

Reference: pinned Hermes checkout at `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`,
version 0.19.1 (2026.7.30).

Probe: `scripts/probe_hermes_help_lifecycle.py`.

Fixture: `tests/fixtures/parity/OBS-0100-hermes-help-lifecycle.json`.

## Observation

In a fresh configured Hermes direct PTY at 120x40, `/help` renders the stable
OBS-0098 double-bordered command row and `❯ /help` composer. A single Escape
press preserves both the help panel and composer while the process remains
alive. The bounded cleanup Ctrl+C then exits cleanly.

The post-Escape screen did not retain the normalized ready-footer marker. That
is recorded as an observed redraw/state detail, not interpreted as provider
readiness or a resolved session.

## Boundary

Only `/help`, one Escape, and Ctrl+C cleanup were exercised. No provider
request, credential, OAuth flow, external network, side-effecting command, or
inferred catalog behavior is claimed. Other focus, navigation, close, and
repeated-help sequences remain unknown.

This observation means Hades’ Escape-to-close convenience is not exact parity;
the next implementation task should preserve the help overlay on Escape.
