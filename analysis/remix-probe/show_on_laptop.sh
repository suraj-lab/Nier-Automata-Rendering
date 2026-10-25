#!/bin/bash
# show_on_laptop.sh <label> [mesh|scene] [scene.bin]: copy runtime/remix-probe/remix-<variant>.exe (+ scene.bin)
# to the laptop and run it --hold in the user's desktop session (closes on window close or after 5 min).
set -e
VARIANT=${2:-mesh}; SCENE=${3:+$(realpath "$3")}
cd /home/suraj/Projects/Nier-Automata-Rendering/analysis
EXE=remix-$VARIANT
STAMP=$(date -u +%Y%m%dT%H%M%SZ); R="C:/Users/suraj/Downloads/NieR-Remix-Probe-20261025T144235Z/view-$1-$STAMP"; SHA=$(sha256sum runtime/remix-probe/$EXE.exe | cut -d' ' -f1)
run_ps() { timeout 90 ssh -o BatchMode=yes -o ConnectTimeout=10 spaghetti "powershell -NoProfile -EncodedCommand $(printf '%s' "$1" | iconv -t UTF-16LE | base64 -w0)" 2>&1 | grep -av CLIXML | grep -av '^<Objs' | grep -av 'progress' || true; }
run_ps "Get-Process remix-mesh,remix-scene -ErrorAction SilentlyContinue | Stop-Process -Force; New-Item -ItemType Directory -Path '$R' | Out-Null"
scp -q -o BatchMode=yes runtime/remix-probe/$EXE.exe "spaghetti:$R/"; scp -q -o BatchMode=yes remix-probe/rtx.no-ngx.conf "spaghetti:$R/rtx.conf"
[ -n "$SCENE" ] && scp -q -o BatchMode=yes "$SCENE" "spaghetti:$R/scene.bin"
run_ps "\$r='$R'.Replace('/','\\'); \$exe=Join-Path \$r '$EXE.exe'
if ((Get-FileHash -LiteralPath \$exe -Algorithm SHA256).Hash.ToLowerInvariant() -ne '$SHA') { throw 'hash mismatch' }
\$dll='C:\Program Files\NVIDIA Corporation\RTX Remix\deps\remix_runtime\runtime\.trex\d3d9.dll'
\$a=New-ScheduledTaskAction -Execute \$exe -Argument ('--render \"'+\$dll+'\" --hold') -WorkingDirectory \$r
\$pr=New-ScheduledTaskPrincipal -UserId (whoami) -LogonType Interactive -RunLevel Limited
\$st=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName NieRRemixView -Action \$a -Principal \$pr -Settings \$st -Force | Out-Null
Start-ScheduledTask NieRRemixView; Start-Sleep 20; Unregister-ScheduledTask NieRRemixView -Confirm:\$false
\$p=Get-Process remix-mesh,remix-scene -ErrorAction SilentlyContinue; if (\$p) { 'running pid=' + \$p.Id + ' session=' + \$p.SessionId } else { 'NOT running' }"
