# Parity fixtures

Only sanitized, provenance-bearing reference fixtures belong here. Do not add
credentials, private transcripts, model payloads, or unreviewed screenshots.

Each fixture should link back to an observation under `docs/parity/`, name its
normalization rules, and be consumed by an executable test or replay command.
The first captured Hermes startup frame is OBS-0001; the Hades startup surface
and its cell-level comparison are covered by HAD-005. The normalized busy and
interrupt visual contract is OBS-0006, and the session switcher contract is
OBS-0007. The setup-required contract is OBS-0008. All three are consumed by
the differential replay command. OBS-0010 records the reference-only input
editing and keymap contract; its provenance and sanitization are checked by
`scripts/validate_reference_fixture.py`. OBS-0011 is the Hades implementation
contract derived from OBS-0010 and is consumed by `scripts/replay_composer.py`.
OBS-0012 is the Hades slash-completion implementation contract derived from
OBS-0010 and is consumed by `scripts/replay_completion.py`.
OBS-0013 is the Hades bracketed-paste implementation contract derived from
OBS-0010 and is consumed by `scripts/replay_paste.py`.
OBS-0014 is the Hades unchanged-draft editor implementation contract derived
from OBS-0010 and is consumed by `scripts/replay_editor.py`.
OBS-0015 is the Hades empty-clipboard fallback contract derived from OBS-0010
and is consumed by `scripts/replay_clipboard.py`.
OBS-0016 is the reference-only persistent input-history contract derived from
the pinned Hermes executable and is consumed by the fixture validator. It does
not imply that Hades has implemented disk history yet.
OBS-0017 is the Hades implementation contract derived from OBS-0016 and is
consumed by `scripts/replay_history.py`.
