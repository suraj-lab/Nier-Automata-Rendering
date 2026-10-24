#!/usr/bin/env bash
# Test for nier_upscale.sh against a throw-away game dir holding real copies (real hashes).
# Needs the local, untracked baseline (backups/native-aa-baseline) and the v3 setter copy from test 3.
set -euo pipefail
D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; REPO="$(cd "$D/../.." && pwd)"
S="$D/nier_upscale.sh"; BASE="$REPO/backups/native-aa-baseline"
V3="$REPO/backups/upscale-test-20261024T132205Z/setter-d3d11.v3.dll"
for f in "$BASE/NIER_DLAA_d3d11.dll" "$BASE/NIER_DLAA.ini" "$V3"; do [ -f "$f" ] || { echo "SKIP: missing $f"; exit 0; }; done

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
export NIER_GAME_DIR="$T/game" NIER_SKIP_PROC_CHECK=1
fail() { echo "FAIL: $*"; exit 1; }
fresh() { rm -rf "$T/game"; mkdir "$T/game"; cp "$BASE/NIER_DLAA_d3d11.dll" "$T/game/d3d11.dll"
          { cat "$BASE/NIER_DLAA.ini"; echo "; debug on"; } > "$T/game/NIER_DLAA.ini"; echo keep > "$T/game/Other.dll"; }
snap() { (cd "$T/game" && sha256sum * | sort); }
st() { "$S" status | sed -n 's/^state *: //p'; }

# 1. fresh native -> install -> idempotent install -> restore -> idempotent restore
fresh
[ "$(st)" = native ] || fail "fresh state: $(st)"
grep -q 'modified' <<<"$("$S" status)" || fail "status should flag the debug ini"
"$S" install >/dev/null
[ "$(st)" = "upscale:v4 (current)" ] || fail "after install: $(st)"
grep -q 'baseline (debug off)' <<<"$("$S" status)" || fail "install must restore the baseline ini"
cmp -s "$T/game/d3d11_dlaa.dll" "$BASE/NIER_DLAA_d3d11.dll" || fail "mod not renamed to d3d11_dlaa.dll"
a=$(snap); "$S" install >/dev/null; [ "$a" = "$(snap)" ] || fail "second install changed files"
"$S" restore >/dev/null
[ "$(st)" = native ] || fail "after restore: $(st)"
[ ! -e "$T/game/d3d11_dlaa.dll" ] || fail "restore left d3d11_dlaa.dll"
a=$(snap); "$S" restore >/dev/null; [ "$a" = "$(snap)" ] || fail "second restore changed files"
[ "$(cat "$T/game/Other.dll")" = keep ] || fail "unrelated file touched"

# 2. upgrade from v3 (test-3 state)
fresh; mv "$T/game/d3d11.dll" "$T/game/d3d11_dlaa.dll"; cp "$V3" "$T/game/d3d11.dll"
[ "$(st)" = upscale:v3 ] || fail "v3 state: $(st)"
grep -q 'was upscale:v3' <<<"$("$S" install)" || fail "upgrade message"
[ "$(st)" = "upscale:v4 (current)" ] || fail "after upgrade: $(st)"

# 3. refusals change nothing
fresh; echo junk > "$T/game/d3d11.dll"; a=$(snap)
if "$S" install 2>/dev/null; then fail "install accepted an unknown d3d11.dll"; fi
if "$S" restore 2>/dev/null; then fail "restore accepted an unknown d3d11.dll"; fi
[ "$a" = "$(snap)" ] || fail "refused run changed files"
fresh; cp "$BASE/NIER_DLAA_d3d11.dll" "$T/game/d3d11_dlaa.dll"; a=$(snap)   # mod present twice: ambiguous
if "$S" install 2>/dev/null; then fail "install accepted mod+mod"; fi
[ "$a" = "$(snap)" ] || fail "refused run changed files (mod+mod)"
fresh; a=$(snap)
if NIER_SETTER_DLL="$T/game/Other.dll" "$S" install 2>/dev/null; then fail "install accepted a wrong setter build"; fi
[ "$a" = "$(snap)" ] || fail "refused run changed files (wrong setter)"
if NIER_BASELINE_DIR="$T/nope" "$S" install 2>/dev/null; then fail "install ran without a baseline"; fi
[ "$a" = "$(snap)" ] || fail "refused run changed files (no baseline)"

echo "nier_upscale tests: all passed"
