# Agent operating system

This directory defines how autonomous development agents collaborate. It is a
development control plane, not a runtime prompt pack.

The agent run is a small state machine:

```text
orient -> select -> claim -> observe/specify -> implement -> verify -> review
   ^                                                               |
   └────────────── blocked / cancelled / complete ◄────────────────┘
```

Use the narrowest role that can produce the next piece of evidence. A role may
leave notes and artifacts for the next role, but it may not silently change the
authority boundary or declare another role's work complete.

## Result envelope

Every autonomous run should be representable by the result shape in
`protocol/result.schema.json`:

- `complete` names changed paths, tests, and evidence;
- `blocked` names the exact missing dependency or authority;
- `cancelled` names what was intentionally left unfinished.

The task ledger is authoritative for task state. Chat text is a handoff surface,
not durable evidence.
