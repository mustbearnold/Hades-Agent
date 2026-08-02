# Hades implementation observation: OBS-0095

- Subject: installed hades/Hades aliases through the model-selection vertical slice
- Reference boundary: OBS-0094 (OBS-0094-hades-model-picker-selection-2026-08-02.md)
- Hades source baseline: aebdf8381e24c9a8695f8c8b6aecd427a036d8f7
- Terminal: clean Bash and Fish shells plus fresh 120x40 direct PTYs
- Capture: user-local release install, command resolution, and deterministic loopback HTTP/SSE replay
- Fixture: tests/fixtures/parity/OBS-0095-hades-installed-model-selection.json
- Replay: scripts/replay_installed_model_selection.py
- Task: HAD-100

## Verified behavior

The release binary is installed through the existing user-local launcher
contract. Fresh Bash and Fish shells, without profiles or configuration files,
resolve both hades and Hades to target/release/hades and return the expected
version/help markers.

The wrapper then runs the complete OBS-0094 replay through each installed alias.
Both aliases configure vertical-model, visibly select palette-model without a
selection-time request, use palette-model for the next streamed request, and
use vertical-model again in a fresh process against the unchanged sidecar.
Each alias records exactly two loopback requests, no authorization header, no
Hermes config creation, and clean terminal restoration.

## Boundary

This proves the shipped user-local command path, not system-wide installation.
The installer still refuses to replace an unrelated existing path, and a
shell without ~/.local/bin on PATH remains outside the command-resolution
contract. External providers, credentials, OAuth, tools, and unobserved Hermes
surfaces remain separate work.

## Linked artifacts

- Sanitized fixture: tests/fixtures/parity/OBS-0095-hades-installed-model-selection.json
- Installed-alias replay: scripts/replay_installed_model_selection.py
- Session selection replay: scripts/replay_model_selection.py
- Launcher installer: scripts/install_user_launcher.sh
- Task ledger: .hades/tasks.json
