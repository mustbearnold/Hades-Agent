# Golden-frame surface: OBS-0004

- Subject: Hades normalized Hermes startup surface
- Reference: OBS-0001 startup frame at 120x40
- Product surface: hades-tui startup rendering
- Render path: Ratatui TestBackend through snapshot
- Implementation asset: crates/hades-tui/assets/hermes-startup-120x40.txt
- Executable oracle: hades-tui test hermes_startup_surface_matches_normalized_golden_frame

## Contract

At exactly 120 columns by 40 rows, Hades renders the captured Hermes startup surface: the Hermes banner, Nous Research tagline, boxed tools and skills panel, model/session placeholders, ready footer, and composer placeholder.

The renderer uses a product-owned startup asset and overlays the typed application state when input or a busy turn is present. It does not read the tests fixture at runtime. The 120x40 snapshot is compared against the checked-in reference using normalized cell rows.

## Normalization

The comparator keeps the row order and visible cell symbols, limits comparison to 120 columns by 40 rows, and removes trailing ASCII spaces from each row. The reference capture already removed ANSI control sequences, cursor placement, elapsed timing, session identity, and temporary path details. The comparison is therefore a cell-level text/geometry oracle, not a screenshot or color oracle.

## Intentional differences

| Difference | Reason |
| --- | --- |
| Colors and exact ANSI styling are not asserted | OBS-0001 normalized control sequences away; the styling contract remains unknown. |
| Session ID, elapsed seconds, working directory, and empty prompt are placeholders | The captured reference values were dynamic and were normalized in OBS-0001. |
| Tool and skill lists are captured startup content, not live discovery | Provider/tool integration is outside this first visual slice. |
| The exact Hermes surface is selected only at 120x40 | No normalized reference frame exists yet for other terminal sizes; smaller sizes retain the bootstrap fallback. |
| Busy state uses a deterministic Hades interrupt prompt | The reference busy face/timing stream is not yet implemented. |

## Linked artifacts

- Reference frame: [tests/fixtures/parity/OBS-0001-startup-120x40.txt](../../../tests/fixtures/parity/OBS-0001-startup-120x40.txt)
- Product asset: [crates/hades-tui/assets/hermes-startup-120x40.txt](../../../crates/hades-tui/assets/hermes-startup-120x40.txt)
- Cell comparator and renderer: [crates/hades-tui/src/lib.rs](../../../crates/hades-tui/src/lib.rs)
- Replay trace: [tests/fixtures/parity/OBS-0001-lifecycle.json](../../../tests/fixtures/parity/OBS-0001-lifecycle.json)
- Task: HAD-005
