#!/bin/sh
# Run the D3D11 bridge probe under Proton. No window is shown (the probe creates a hidden popup).
# usage: ./run_bridge.sh [seconds]
set -u
hold=${1:-75}
PROTON=${PROTON:-/usr/share/steam/compatibilitytools.d/proton-cachyos-slr/proton}
RUNTIME=${RUNTIME:-/mnt/second/SteamLibrary/steamapps/common/PortalRTX/bin/.trex/d3d9.dll}
ART=$(cd "$(dirname "$0")/../runtime/remix-probe" && pwd)
export DISPLAY="${DISPLAY:-:1}" XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"
export STEAM_COMPAT_CLIENT_INSTALL_PATH=$HOME/.local/share/Steam
export STEAM_COMPAT_DATA_PATH=$ART/desktop-prefix
export DXVK_LOG_LEVEL=${DXVK_LOG_LEVEL:-info}
[ -f "$RUNTIME" ] || { echo "missing runtime: $RUNTIME" >&2; exit 2; }
run=$ART/bridge-run; rm -rf "$run"; mkdir -p "$run"; cp "$ART/d3d11-bridge.exe" "$run/"
cd "$run" || exit 2
win=$(printf 'Z:%s' "$RUNTIME" | sed 's|/|\\\\|g')
if [ -n "${BENCH:-}" ]; then
  set -- --bench "$BENCH" --frames "${FRAMES:-60}"
else
  set -- --render "$win" --frames "${FRAMES:-60}"
fi
setsid "$PROTON" run ./d3d11-bridge.exe "$@" > bridge.log 2>&1 &
pid=$!
sleep "$hold"
kill -- -"$pid" 2>/dev/null || true; sleep 2; kill -9 -- -"$pid" 2>/dev/null || true
WSB="$(dirname "$PROTON")/files/bin/wineserver"
[ -x "$WSB" ] && WINEPREFIX="$STEAM_COMPAT_DATA_PATH/pfx" "$WSB" -k 2>/dev/null
echo "--- bridge.txt ---"; cat bridge.txt 2>/dev/null || echo '(no bridge.txt)'
