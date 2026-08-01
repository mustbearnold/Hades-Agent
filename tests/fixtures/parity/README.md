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
