#!/usr/bin/env bash
# Provision the pinned Hermes reference for parity work, local-only.
#
# Creates/refreshes .hades/runtime/hermes-reference (gitignored) with the
# pinned commit's TUI bundle built from the workspace root (the runtime skips
# its own npm install only when the hidden lockfile covers the whole
# workspace), uv-synced, and symlinked at the probe-hardcoded
# /tmp/hades-hermes-ref-X3bLd0 path. Not product source.
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
reference_dir="$project_root/.hades/runtime/hermes-reference"
reference_link=/tmp/hades-hermes-ref-X3bLd0
commit=e444d165807f489b5c1ab8e4a612c8d09c2e67a2

log() { echo "[$(date +%H:%M:%S)] $*"; }

if [ ! -d "$reference_dir/.git" ]; then
    log "cloning hermes-agent at pinned commit"
    rm -rf "$reference_dir"
    git clone --filter=blob:none https://github.com/NousResearch/hermes-agent.git "$reference_dir"
    git -C "$reference_dir" checkout "$commit"
fi

log "npm install from the workspace root (matches the runtime lockfile check)"
cd "$reference_dir"
npm install --ignore-scripts --no-audit --no-fund

log "building the TUI bundle"
cd "$reference_dir/ui-tui"
npm run build:ink
npm run build

log "uv sync (no dev dependencies)"
cd "$reference_dir"
uv sync --frozen --no-dev

log "symlinking probe reference path"
ln -sfn "$reference_dir" "$reference_link"
git -C "$reference_dir" rev-parse HEAD
log "reference ready at $reference_dir"
