#!/usr/bin/env bash
# Measure a development action in wall-clock milliseconds and append it to the
# local timing ledger. Usage:
#   scripts/time_action.sh <label> -- <command...>
# The ledger is local-only (.hades/runtime/, gitignored) and append-only.
set -euo pipefail

label="${1:?usage: time_action.sh <label> -- <command...>}"
shift
[ "${1:-}" = "--" ] && shift

ledger="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/.hades/runtime/dev-timing.log"
mkdir -p "$(dirname "$ledger")"

start_ms=$(date +%s%3N)
"$@"
rc=$?
end_ms=$(date +%s%3N)
elapsed_ms=$((end_ms - start_ms))

printf '%s\t%s\t%s ms\texit=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$label" "$elapsed_ms" "$rc" >> "$ledger"
printf '[dev-timing] %s: %s ms (exit %s)\n' "$label" "$elapsed_ms" "$rc"
exit "$rc"
