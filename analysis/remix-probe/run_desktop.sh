#!/bin/sh
# Render a converted scene with the standalone probe under Proton. No game is involved.
# The probe window is moved to a hidden workspace (default 10) so it never covers the user's session,
# and the frame is captured with DXVK's own screenshot rather than a screen grab.
# usage: WS=10 SHOT_FRAME=60 ./run_desktop.sh <scene.bin> [seconds]
set -u   # no set -e: a failing hyprctl probe must not abort the run before teardown
PROTON=${PROTON:-/usr/share/steam/compatibilitytools.d/proton-cachyos-slr/proton}
RUNTIME=${RUNTIME:-/mnt/second/SteamLibrary/steamapps/common/PortalRTX/bin/.trex/d3d9.dll}
WS=${WS:-10}; SHOT_FRAME=${SHOT_FRAME:-60}; HEIGHT=${HEIGHT:-540}
[ -f "$RUNTIME" ] || { echo "missing Remix runtime: $RUNTIME" >&2; exit 2; }
here=$(cd "$(dirname "$0")" && pwd); A=$(cd "$here/.." && pwd)
run=$A/runtime/remix-probe/desktop-run
scene=$1; hold=${2:-40}
rm -rf "$run"; mkdir -p "$run/Screenshots"
cp "$A/runtime/remix-probe/remix-scene.exe" "$run/"; cp "$scene" "$run/scene.bin"
[ -d "${scene%.bin}_textures" ] && cp -r "${scene%.bin}_textures" "$run/scene_textures"
echo "run dir: $run ($(find "$run/scene_textures" -name '*.dds' 2>/dev/null | wc -l) textures)"
cd "$run"
win=$(printf 'Z:%s' "$RUNTIME" | sed 's|/|\\\\|g')
export STEAM_COMPAT_CLIENT_INSTALL_PATH=$HOME/.local/share/Steam
export STEAM_COMPAT_DATA_PATH=$A/runtime/remix-probe/desktop-prefix
export DXVK_DUMP_SCREENSHOT_FRAME=$SHOT_FRAME DXVK_SCREENSHOT_PATH=$run/Screenshots
export REPROBE_HEIGHT=$HEIGHT REPROBE_SUN=${SUN:-2}  # smaller window = less load on the card driving the desktop
mkdir -p "$STEAM_COMPAT_DATA_PATH"
setsid "$PROTON" run ./remix-scene.exe --render "$win" --hold > probe.log 2>&1 &
pid=$!
# Hide the window the moment it exists. The wine window class is steam_proton, so match the title.
addr=""
for i in $(seq 1 90); do
  addr=$(hyprctl clients -j 2>/dev/null | python3 -c '
import json,sys
try: clients=json.load(sys.stdin)
except Exception: raise SystemExit
for w in clients:
    if "Remix triangle" in w.get("title","") or "remix-scene" in w.get("title",""):
        print(w["address"]); break' 2>/dev/null)
  [ -n "$addr" ] && break
  sleep 1
done
if [ -n "$addr" ]; then
  moved=0
  for i in $(seq 1 10); do
    hyprctl dispatch movetoworkspacesilent "$WS,address:$addr" >/dev/null 2>&1
    now=$(hyprctl clients -j 2>/dev/null | python3 -c "
import json,sys
a='$addr'
try: cs=json.load(sys.stdin)
except Exception: raise SystemExit
print(next((w['workspace']['name'] for w in cs if w['address']==a), ''))" 2>/dev/null)
    if [ "$now" = "$WS" ]; then echo "window on workspace $WS"; moved=1; break; fi
    sleep 1
  done
  [ "$moved" = 1 ] || echo "WARNING: could not move the window off the active workspace"
  W=$((HEIGHT * 239 / 100))
  hyprctl dispatch setfloating "address:$addr" >/dev/null 2>&1
  hyprctl dispatch resizewindowpixel "exact $W $HEIGHT,address:$addr" >/dev/null 2>&1
  echo "window set floating at ${W}x${HEIGHT}"
fi
sleep "$hold"
kill -- -"$pid" 2>/dev/null || true
sleep 2; kill -9 -- -"$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true
echo "--- probe stdout (last 12) ---"; grep -vE "radv is not|ProtonFixes|ntsync" probe.log | tail -12
echo "--- screenshots ---"; ls -1 Screenshots/ 2>/dev/null || echo "(none: DXVK screenshot did not fire)"
