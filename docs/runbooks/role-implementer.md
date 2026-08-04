# Implementer role

The implementer changes the smallest product seam covered by the current
contract. State transitions belong in `hades-app`; terminal drawing belongs in
`hades-tui`; terminal ownership belongs in `hades-cli`; shared vocabulary
belongs in `hades-core`.

Every behavior change gets a focused regression oracle. Do not add speculative
Hermes behavior to make a screen look complete. Keep external effects behind
adapters or replayable seams.
