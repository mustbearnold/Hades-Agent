# Product specification

## Product identity

Hades Agent is a native Rust terminal interface that reproduces Hermes TUI.
The primary product promise is exactness: the same user action in the same
supported environment should produce the same observable result, within a
documented normalization boundary.

"Exact" means parity across the surfaces users can observe:

- process startup, terminal initialization, and cleanup;
- layout, colors, text, cursor/focus, and responsive behavior;
- keyboard and mouse input, command routing, and navigation;
- transcript rendering, streaming, errors, retries, and cancellation;
- persistence, configuration, and recovery where Hermes exposes them;
- timing and resource behavior when it changes what a user can observe.

The exact set of supported surfaces is discovered from the reference contract,
not guessed from the product name.

## Product boundary

The product plane contains Rust application state, deterministic transitions,
terminal rendering, provider/tool adapters, and user-facing configuration. The
development plane contains agent contracts, task ledgers, reference captures,
verification scripts, and evidence. Development instructions must not leak into
the runtime product.

The bootstrap application is intentionally a shell. It proves that the seams
exist without claiming that the shell is Hermes-compatible.

## Parity contract

A behavior may move from unknown to implemented only when all four links exist:

1. a provenance-bearing reference observation;
2. an explicit normalized contract or trace;
3. a Hades implementation and executable oracle;
4. a verification record naming the exact artifacts used.

If a reference behavior cannot be safely captured, the correct state is
`blocked` or `unknown`, not an approximation presented as parity.

## Quality bar

Every product change must have a narrow regression oracle and pass the complete
local gate:

```bash
just verify
```

Visual behavior requires deterministic terminal snapshots or an equivalent
cell-level comparison. Interactive manual inspection is useful exploratory
evidence but never the only acceptance proof.

## Initial milestones

1. Capture the reference contract and fixture format.
2. Lock down lifecycle and terminal ownership.
3. Build the deterministic application/replay seam.
4. Reproduce the first reference-backed surface.
5. Expand parity one observable contract at a time.
