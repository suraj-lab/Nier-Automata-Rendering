#!/usr/bin/env bash
# Unattended plan runner: restarts pi in print mode with a FRESH session each iteration, so neither a model that
# ends its turn to "report progress" nor auto-compaction can stall the night. The plan's Handoff section is the memory.
#
#   analysis/tools/overnight.sh [MAX_ITERATIONS=12]
#   env: PI_AUTO_MODEL=provider/id (default: pi's default)   PROMPT_FILE=...   ITER_TIMEOUT=3h   MAX_HOURS=10
#   stop: touch analysis/runtime/auto/STOP      (the agent creates BLOCKED itself when no ready work is left)
# Live actions: allowed only through checks/unattended_guard.py and the user's ~/.config/nier-auto/authorization.json.
set -u
export NIER_UNATTENDED=1
repo=$(git -C "$(dirname "$0")" rev-parse --show-toplevel) || exit 2
cd "$repo" || exit 2
auto=analysis/runtime/auto
run=$auto/$(date -u +%Y%m%dT%H%M%SZ)
plan=analysis/PLAN_2026-11-14.md
prompt=${PROMPT_FILE:-analysis/tools/OVERNIGHT_PROMPT.md}
max=${1:-12}
mkdir -p "$run"
exec 9>"$auto/lock"; flock -n 9 || { echo "another overnight loop holds $auto/lock" >&2; exit 3; }
rm -f "$auto/BLOCKED"
[ -f "$prompt" ] || { echo "missing $prompt" >&2; exit 2; }

state() { { sha256sum "$plan"; git status --porcelain; git diff | sha256sum; } | sha256sum; }
# The guard, its call sites and the user's authorization are pinned at launch; any change stops the loop.
guarded="analysis/checks/unattended_guard.py analysis/runtime/game-runs/game_run.py analysis/checks/install_live_dll.py analysis/deploy/laptop_port.py analysis/tools/overnight.sh"
auth="$HOME/.config/nier-auto/authorization.json"
pins() { sha256sum $guarded 2>&1; sha256sum "$auth" 2>&1; }
pinned=$(pins)
printf '%s\n' "$pinned" >"$run/pins.txt"
idle=0
for i in $(seq 1 "$max"); do
    [ -e "$auto/STOP" ] && { echo "STOP file present" | tee -a "$run/loop.log"; break; }
    # No new iteration after MAX_HOURS: the user works in this same worktree in the morning (one writer at a time).
    [ "$SECONDS" -ge $(( ${MAX_HOURS:-10} * 3600 )) ] && { echo "MAX_HOURS reached" | tee -a "$run/loop.log"; break; }
    [ "$(pins)" = "$pinned" ] || { echo "guard or authorization changed since launch; stopping" | tee -a "$run/loop.log"; break; }
    python3 analysis/tools/prune_scratch.py --delete >>"$run/loop.log" 2>&1
    [ -e "$auto/BLOCKED" ] && { echo "agent reported BLOCKED: $(head -c 400 "$auto/BLOCKED")" | tee -a "$run/loop.log"; break; }
    # Safety net for the uncommitted worktree: restore with  tar -xzf <file> -C <repo>
    git ls-files -m -o --exclude-standard -z | tar --null -czf "$run/pre-iter-$i.tar.gz" -T - 2>>"$run/loop.log"
    before=$(state)
    echo "$(date -u +%FT%TZ) iteration $i start" >>"$run/loop.log"
    timeout "${ITER_TIMEOUT:-3h}" pi --print ${PI_AUTO_MODEL:+--model "$PI_AUTO_MODEL"} "$(cat "$prompt")" \
        >"$run/iter-$i.out" 2>"$run/iter-$i.err" </dev/null
    code=$?
    echo "$(date -u +%FT%TZ) iteration $i exit=$code" >>"$run/loop.log"
    # Two iterations in a row that change nothing in the repo = the model is stuck or out of quota; stop spending.
    if [ "$(state)" = "$before" ]; then idle=$((idle + 1)); else idle=0; fi
    [ "$idle" -ge 2 ] && { echo "no repository change in 2 iterations; stopping" | tee -a "$run/loop.log"; break; }
    sleep 5
done
echo "loop finished; logs in $run"
