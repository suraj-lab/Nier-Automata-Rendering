#!/bin/bash
# Report-only guard. Callers MUST stop on nonzero status; historical backups are never restored.
set -eu
A="$(cd "$(dirname "$0")/../.." && pwd)"
: "${NIER_GUARD_STATE:?set a unique repository-local state directory for this run}"
exec python3 "$A/checks/game_run_safety.py" "$@" \
  --save "${NIER_GUARD_SAVE:-/mnt/second/SteamLibrary/steamapps/compatdata/524220/pfx/drive_c/users/steamuser/Documents/My Games/NieR_Automata}" \
  --prefix "${NIER_GUARD_PREFIX:-$A/runtime/game-runs/prefix-2026-11-13}" \
  --state "$NIER_GUARD_STATE"
