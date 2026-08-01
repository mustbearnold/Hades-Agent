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
OBS-0018 captures deterministic Hermes editor outcomes that extend the
unchanged-draft editor probe: modified and multiline clean exits, trailing
newline trimming, empty output, and nonzero cancellation. It is consumed by
the reference fixture validator and does not imply Hades implementation parity.
OBS-0019 is the Hades implementation contract derived from OBS-0018 and is
consumed by `scripts/replay_editor_outcomes.py`.
OBS-0020 captures the reference-only native modified-Enter contract through a
direct PTY with raw CSI-u bytes. It is consumed by the fixture validator and
does not imply Hades implementation parity or universal terminal support.
OBS-0021 is the Hades implementation contract derived from OBS-0020. It is
consumed by the direct-PTY `scripts/replay_modified_enter.py` oracle and only
claims crossterm-decoded Shift/Alt Enter events.
OBS-0022 captures the reference-only successful text clipboard path with a
synthetic xclip provider, including provider arguments, newline trimming, and
the empty-provider control. OBS-0023 is the Hades implementation contract for
the native text path and is consumed by the direct-PTY
`scripts/replay_clipboard_text.py` oracle; image/path/OSC52 behavior remains
outside the contract.
OBS-0024 captures Hermes research-only remote `SSH_TTY` OSC52 precedence and
the native xclip timeout fallback with explicit query/DA1 bytes. It does not
imply tmux/STY passthrough coverage. OBS-0025 is the Hades implementation
contract derived from OBS-0024 and is consumed by the direct-PTY
`scripts/replay_osc52_clipboard.py` oracle; invalid/empty/oversized responses,
image/path/gateway behavior, and concurrent input during the bounded wait
remain outside the claim.
OBS-0026 captures Hermes fallback behavior for empty, query-marker,
invalid-base64, invalid-target, and unterminated OSC52 responses. It is
research-only, consumed by `scripts/validate_reference_fixture.py`, and keeps
delayed/oversized responses, ST termination, multiplexers, and attachments as
explicit unknowns.
OBS-0027 is the Hades implementation contract derived from OBS-0026 and is
consumed by the dedicated direct-PTY response-boundary replay; it proves the
same five controls fall back to native xclip without submission.
OBS-0028 captures Hermes ST-terminated OSC52 response handling in a direct PTY;
it proves a usable ST response wins before native xclip while empty and
invalid-base64 ST responses fall back. It is research-only and does not claim
Hades implementation parity.
