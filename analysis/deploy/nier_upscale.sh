#!/usr/bin/env bash
# Permanent install of the FSR4 upscaling setter for NieR:Automata (Proton, NIER_DLAA 1.1 + FSR4 bridge).
#
#   nier_upscale.sh status    show what is installed (by hash), change nothing
#   nier_upscale.sh install   native AA -> upscaling, or upgrade an older setter build to the current one
#   nier_upscale.sh restore   upscaling -> native AA (original NIER_DLAA d3d11.dll + ini)
#
# Every mode refuses while the game runs and refuses (changing nothing) when a file is not recognised.
# The scale applies at game start; no in-game resolution re-apply is needed (test 3 log, 2026-10-24).
# Env overrides (tests): NIER_GAME_DIR, NIER_BASELINE_DIR, NIER_SETTER_DLL, NIER_SKIP_PROC_CHECK=1.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
G="${NIER_GAME_DIR:-/mnt/second/SteamLibrary/steamapps/common/NieRAutomata}"
BASE="${NIER_BASELINE_DIR:-$REPO/backups/native-aa-baseline}"
SETTER="${NIER_SETTER_DLL:-$REPO/analysis/build/scale-setter/d3d11.dll}"

MOD_SHA=3d628eb576b505180206653d72e4e4da6a4345334f19863256ab5b10e06b6915   # NIER_DLAA 1.1 d3d11.dll (FSR4-patched)
INI_SHA=3163360d28e7f12c04013b54a82900c160ac5a65cfc395d9272f293624fa8a64   # NIER_DLAA.ini, [Debug] Enabled=0
SETTER_SHA=3afafb606b38a30536ee8a89b93093e1971414e8f13cc89a8c796f011afc161f # setter v4 (current)
declare -A KNOWN_SETTER=(                                                     # older builds this may upgrade
  [545d82305541e3890a5533e28fa177d75f6ddb2aab70170e755193728d53c535]=v1
  [3aaf52fa95052c248fbfc356af9f121155a8b98c1fd20f81e631aaa8eb378b06]=v2
  [936602b315b66353ffddd8e6602e47bf61c9b2e9944e42dc93c10499a95aa77f]=v3
  [$SETTER_SHA]=v4
)

sha() { [ -f "$1" ] && sha256sum "$1" | cut -d' ' -f1 || echo none; }
die() { echo "refusing: $*" >&2; exit 1; }

state() {  # prints: native | upscale:<build> | unknown:<reason>
  local d3d dlaa
  d3d=$(sha "$G/d3d11.dll"); dlaa=$(sha "$G/d3d11_dlaa.dll")
  if [ "$d3d" = "$MOD_SHA" ] && [ "$dlaa" = none ]; then echo native
  elif [ "$dlaa" = "$MOD_SHA" ] && [ -n "${KNOWN_SETTER[$d3d]:-}" ]; then echo "upscale:${KNOWN_SETTER[$d3d]}"
  else echo "unknown:d3d11.dll=${d3d:0:12} d3d11_dlaa.dll=${dlaa:0:12}"; fi
}

preflight() {
  [ -d "$G" ] || die "game dir not found: $G"
  if [ "${NIER_SKIP_PROC_CHECK:-0}" != 1 ] && pgrep -i 'NieRAutomata[.]exe' >/dev/null; then die "game is running, close it first"; fi
  [ "$(sha "$BASE/NIER_DLAA_d3d11.dll")" = "$MOD_SHA" ] || die "baseline mod DLL missing/changed in $BASE"
  [ "$(sha "$BASE/NIER_DLAA.ini")" = "$INI_SHA" ] || die "baseline ini missing/changed in $BASE"
}

case "${1:-status}" in
  status)
    s=$(state); ini=$(sha "$G/NIER_DLAA.ini")
    echo "game dir : $G"
    echo "state    : $s$([ "$s" = upscale:v4 ] && echo ' (current)')"
    echo "ini      : $([ "$ini" = "$INI_SHA" ] && echo 'baseline (debug off)' || echo "modified ${ini:0:12} (e.g. debug keys on)")"
    pgrep -i 'NieRAutomata[.]exe' >/dev/null && echo "game     : RUNNING" || echo "game     : not running"
    ;;
  install)
    preflight
    [ "$(sha "$SETTER")" = "$SETTER_SHA" ] || die "setter build $SETTER does not match pinned v4 hash"
    s=$(state)
    case "$s" in
      native)    mv "$G/d3d11.dll" "$G/d3d11_dlaa.dll" ;;
      upscale:*) ;;                                   # upgrade in place; d3d11_dlaa.dll already the mod
      *)         die "unrecognised files ($s)" ;;
    esac
    cp "$SETTER" "$G/d3d11.dll"
    cp "$BASE/NIER_DLAA.ini" "$G/NIER_DLAA.ini"
    [ "$(state)" = upscale:v4 ] && [ "$(sha "$G/NIER_DLAA.ini")" = "$INI_SHA" ] || die "post-install verification failed"
    echo "installed: upscale v4 (was $s), debug keys off"
    ;;
  restore)
    preflight
    s=$(state)
    case "$s" in
      upscale:*) mv -f "$G/d3d11_dlaa.dll" "$G/d3d11.dll" ;;
      native)    ;;
      *)         die "unrecognised files ($s)" ;;
    esac
    cp "$BASE/NIER_DLAA.ini" "$G/NIER_DLAA.ini"
    [ "$(state)" = native ] && [ "$(sha "$G/NIER_DLAA.ini")" = "$INI_SHA" ] || die "post-restore verification failed"
    echo "restored: native AA (was $s)"
    ;;
  *) echo "usage: $0 status|install|restore" >&2; exit 2 ;;
esac
