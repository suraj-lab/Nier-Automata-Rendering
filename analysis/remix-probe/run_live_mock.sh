#!/bin/sh
# Real-GPU check of the in-game Remix host, before NieR: the menu gate's mock game runs under Proton (DXVK d3d11),
# loads our proxy d3d11.dll (built by analysis/checks/build_menu_dll.py) and the stub mod layer, and the proxy
# hosts the REAL Remix runtime with a converted F9 scene. The stub layer captures the backbuffer our hook passed
# down at frames 25/45/70 (capture-*.raw), and NIER_SCALE.log carries the remix: lines (start, first frame, fps).
# A window is shown on the focused monitor for the run. Never touches the game folder.
# usage: ./run_live_mock.sh [frame_ms]       (80 frames; default 500 ms each = 40 s, room for Remix start-up)
set -u
frame_ms=${1:-500}
here=$(cd "$(dirname "$0")" && pwd)
checks=$here/../checks
ART=$(cd "$here/../runtime/remix-probe" && pwd)
PROTON=${PROTON:-/usr/share/steam/compatibilitytools.d/proton-cachyos-slr/proton}
RUNTIME=${RUNTIME:-/mnt/second/SteamLibrary/steamapps/common/PortalRTX/bin/.trex/d3d9.dll}
SCENE=${SCENE:-$ART/textured-scene/scene.bin}
CONF=${CONF:-$here/rtx.enhanced.conf}
DLL=$here/../runtime/menu-dll
for f in "$PROTON" "$RUNTIME" "$SCENE" "$CONF" "$DLL/d3d11.dll"; do [ -e "$f" ] || { echo "missing: $f" >&2; exit 2; }; done
run=$ART/live-mock-run; rm -rf "$run"; mkdir -p "$run"
gpp="x86_64-w64-mingw32-g++ -std=c++17 -O2 -static -static-libgcc -static-libstdc++"
$gpp -shared "$checks/menu_overlay_stub_dlaa.cpp" -o "$run/d3d11_dlaa.dll" || exit 2
$gpp -municode "$checks/menu_overlay_mock_game.cpp" -ldinput8 -ldxguid -o "$run/mock.exe" || exit 2
cp "$DLL/d3d11.dll" "$run/"; cp -r "$DLL/nier_render_fonts" "$run/"; cp "$CONF" "$run/rtx.conf"
printf '[Rendering]\r\nPreset=Custom75\r\n' > "$run/NIER_RENDER.ini"
winpath() { printf 'Z:%s' "$1" | sed 's|/|\\|g'; }
export DISPLAY="${DISPLAY:-:1}" XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"
export STEAM_COMPAT_CLIENT_INSTALL_PATH=$HOME/.local/share/Steam STEAM_COMPAT_DATA_PATH=${COMPAT:-$ART/desktop-prefix}
export WINEDLLOVERRIDES="d3d11=n,b" DXVK_LOG_LEVEL=${DXVK_LOG_LEVEL:-info}
export NIER_REMIX=${NIER_REMIX:-1} NIER_REMIX_RUNTIME="$(winpath "$RUNTIME")" NIER_REMIX_SCENE="$(winpath "$SCENE")"
export DXVK_CONFIG_FILE="$(winpath "$run/rtx.conf")" MOCK_FRAME_MS=$frame_ms
cd "$run" || exit 2
# Wine games take their resolution list from the Xwayland primary output; on 2026-10-28 it was found cleared after a day
# of runs (NieR then offered 900p max). Record it so a run that changes it is caught.
primary_before=$(xrandr 2>/dev/null | awk '/ connected primary/{print $1}')
setsid "$PROTON" run ./mock.exe 0 0 > proton.log 2>&1 &
pid=$!
limit=$(( frame_ms * 80 / 1000 + 60 ))
# What actually reaches the screen (the stub's capture only proves the backbuffer): grab the mock window's own
# rectangle with grim at SHOTS seconds. Only that window's area is captured, never the rest of the desktop.
SHOTS=${SHOTS:-15 30}
HYPRLAND_INSTANCE_SIGNATURE=${HYPRLAND_INSTANCE_SIGNATURE:-$(ls -t /run/user/$(id -u)/hypr/ | head -1)}; export HYPRLAND_INSTANCE_SIGNATURE
i=0; while kill -0 "$pid" 2>/dev/null && [ $i -lt $limit ]; do
  for t in $SHOTS; do
    if [ $i -eq "$t" ]; then
      geo=$(hyprctl clients -j | python3 -c 'import json,sys
for c in json.load(sys.stdin):
    if c["title"] == "mock" or "mock.exe" in c["class"]: print("%d,%d %dx%d" % (*c["at"], *c["size"])); break')
      [ -n "$geo" ] && WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-wayland-1} grim -g "$geo" "screen-${t}s.png" && echo "screenshot ${t}s: $geo"
      [ -z "$geo" ] && echo "screenshot ${t}s: no mock window found"
      hyprctl clients -j | python3 -c 'import json,sys
for c in json.load(sys.stdin):
    if c["xwayland"] or ".exe" in c["class"]: print("  window:", repr(c["title"]), c["class"], c["at"], c["size"], "mapped", c["mapped"], "hidden", c["hidden"], "focus", c["focusHistoryID"])' 
    fi
  done
  sleep 1; i=$((i+1)); done
if kill -0 "$pid" 2>/dev/null; then echo "EXIT: still running after ${i}s, killed (frames end at $((frame_ms * 80 / 1000))s)"; else echo "EXIT: process ended by ${i}s (frames end at $((frame_ms * 80 / 1000))s)"; fi
kill -- -"$pid" 2>/dev/null; sleep 2; kill -9 -- -"$pid" 2>/dev/null
WSB="$(dirname "$PROTON")/files/bin/wineserver"
[ -x "$WSB" ] && WINEPREFIX="$STEAM_COMPAT_DATA_PATH/pfx" "$WSB" -k 2>/dev/null
pgrep -fa 'mock.exe' >/dev/null && echo "WARNING: mock.exe survived teardown"
primary_after=$(xrandr 2>/dev/null | awk '/ connected primary/{print $1}')
[ "$primary_before" = "$primary_after" ] || echo "WARNING: Xwayland primary changed during the run: '$primary_before' -> '$primary_after' (fix: xrandr --output DP-2 --primary)"
echo "--- mock-result.txt"; cat mock-result.txt 2>/dev/null
echo "--- remix lines"; grep 'remix:' NIER_SCALE.log 2>/dev/null
echo "--- pixels at (100,100)"
python3 - <<'EOF'
import struct, pathlib
for n in ('capture-closed.raw', 'capture-open.raw', 'capture-after.raw'):
    p = pathlib.Path(n)
    if not p.exists(): print(n, 'missing'); continue
    b = p.read_bytes(); w, h, f = struct.unpack_from('<3I', b); o = 12 + (100 * w + 100) * 4
    print(n, f'{w}x{h} fmt={f}', tuple(b[o:o + 3]))
EOF
