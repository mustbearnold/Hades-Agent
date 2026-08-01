# Verifier role

The verifier treats the implementation as untrusted. It runs `just verify`,
replays the relevant trace or snapshot, checks that evidence paths exist, and
looks for skipped or weakened assertions.

For a visual claim, inspect normalized cells and report the first meaningful
divergence. For a lifecycle claim, check cleanup after success, error, and
interrupt paths. A verifier may mark work blocked when the oracle is missing;
it must not convert missing evidence into approval.
