# Trace and golden-frame format

Reference traces are sanitized, deterministic JSON documents. They describe
observable inputs and outputs; they do not embed credentials, raw private
transcripts, or model payloads.

```json
{
  "schema_version": 1,
  "observation_id": "OBS-0001",
  "reference": {
    "product": "Hermes TUI",
    "version": "<exact version or unknown>",
    "terminal": {"columns": 120, "rows": 40}
  },
  "steps": [
    {
      "input": {"kind": "key", "value": "<sanitized key>"},
      "output": {
        "frame": "<fixture path>",
        "status": "<normalized observable status>"
      }
    }
  ]
}
```

Golden frames are UTF-8 text files with one normalized terminal row per line.
The capture contract must state whether trailing spaces, ANSI escapes, cursor
position, and timing are retained or normalized. A normalizer is part of the
oracle, not an undocumented cleanup step.
