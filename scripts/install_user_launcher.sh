#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
INSTALL_DIR="${HADES_INSTALL_DIR:-${HOME:?HOME must be set}/.local/bin}"
BINARY_PATH="${HADES_BINARY_PATH:-$ROOT_DIR/target/release/hades}"

if [[ ! -x "$BINARY_PATH" ]]; then
    printf 'release binary is missing: %s\nrun `just install-user` from the repository root\n' "$BINARY_PATH" >&2
    exit 1
fi

mkdir -p -- "$INSTALL_DIR"

install_launcher() {
    local launcher_name="$1"
    local launcher_path="$INSTALL_DIR/$launcher_name"

    if [[ -e "$launcher_path" || -L "$launcher_path" ]]; then
        if [[ -L "$launcher_path" && "$(readlink -f -- "$launcher_path")" == "$BINARY_PATH" ]]; then
            printf 'already installed: %s -> %s\n' "$launcher_path" "$BINARY_PATH"
            return
        fi
        printf 'refusing to replace an existing path: %s\n' "$launcher_path" >&2
        exit 1
    fi

    ln -s -- "$BINARY_PATH" "$launcher_path"
    printf 'installed: %s -> %s\n' "$launcher_path" "$BINARY_PATH"
}

install_launcher hades
install_launcher Hades

printf 'launch with `hades` or `Hades` once %s is on PATH\n' "$INSTALL_DIR"
