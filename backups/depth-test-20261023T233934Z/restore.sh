#!/usr/bin/env bash
set -euo pipefail
B="$(cd "$(dirname "$0")" && pwd)"
G=/mnt/second/SteamLibrary/steamapps/common/NieRAutomata
M="/mnt/second/SteamLibrary/steamapps/compatdata/524220/pfx/drive_c/users/steamuser/Documents/My Games/NieR_Automata"
if pgrep -ai 'NieRAutomata[.]exe' >/dev/null; then echo "game running, close it first"; exit 1; fi
cp -p "$B/game/NIER_DLAA.ini" "$G/NIER_DLAA.ini"
cp -p "$B/game/d3d11.dll" "$G/d3d11.dll"
rm -f "$G/d3d11_dlaa.dll"
cp -p "$B/mygames/Graphic.ini" "$M/Graphic.ini"
(cd "$G" && sha256sum -c "$B/game.SHA256SUMS")
(cd "$M" && sha256sum -c "$B/mygames.SHA256SUMS" 2>&1 | grep -E 'Graphic.ini|FAILED' || true)
[ ! -e "$G/d3d11_dlaa.dll" ] && echo "restore OK"
