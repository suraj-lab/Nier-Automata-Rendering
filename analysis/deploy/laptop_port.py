#!/usr/bin/env python3
"""Laptop port, stages 1-3 (analysis/LAPTOP_PORT.md): install our proxy into NieR on `spaghetti`, launch, restore.

  laptop_port.py install            back up the game's d3d11.dll (the NIER_DLAA proxy) and chain it as d3d11_dlaa.dll
                                    behind our hash-checked d3d11.dll; add NIER_RENDER.ini, fonts, steam_appid.txt
                                    (so a direct launch keeps the environment), and the static camp scene
  laptop_port.py run <label> [--remix] [--seconds N] [--no-ec-hooks] [--steam] [--live]
                                    start NieRAutomata.exe in the user's session with the NIER_* environment, stop ONLY
                                    that process after N seconds (default 90), copy back NIER_SCALE.log and a receipt
                                    --live enables the draw stream instead of the static scene; load a save manually
  laptop_port.py restore            put the original files back exactly (hash-checked) and remove what install added

Logs only: no desktop screenshots. Every file this writes into the game folder is listed in ADDED and removed by
restore; the original d3d11.dll is kept in BACKUP until restore has verified its hash.
"""
import base64
import datetime
import hashlib
import json
import subprocess
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[1]
OUT = A / 'runtime/laptop-port'
DLL = A / 'runtime/menu-dll/d3d11.dll'
FONTS = A / 'runtime/menu-dll/nier_render_fonts'
SCENE = A / 'runtime/remix-probe/textured-scene'
GAME = r'C:\Program Files (x86)\Steam\steamapps\common\NieRAutomata'
WORK = r'C:\Users\suraj\Downloads\NieR-Laptop-Port'          # scene, backup, launch scripts: outside the game folder
BACKUP = WORK + r'\backup'
RUNTIME = r'C:\Program Files\NVIDIA Corporation\RTX Remix\deps\remix_runtime\runtime\.trex\d3d9.dll'
ORIGINAL_D3D11 = '6ba266d64a8f6776'                           # NIER_DLAA proxy found in the game folder 2026-10-30
ADDED = ['d3d11_dlaa.dll', 'NIER_RENDER.ini', 'steam_appid.txt', 'nier_render_fonts', 'NIER_SCALE.log', 'NIER_ENV.ini',
         'NIER_CAPTURE', r'data\rtx-remix', r'data\metrics.txt']  # last three: written by our runs (shader capture, Remix)
OPTS = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10']


def ps(script, timeout=600):
    # cmd.exe on the SSH server limits command lines to 8191 characters. Keep the command fixed and carry the
    # (possibly long, Unicode) script on stdin instead. Base64 also avoids the remote console's code-page conversion.
    bootstrap = "$s=[Text.Encoding]::Unicode.GetString([Convert]::FromBase64String([Console]::In.ReadToEnd())); & ([scriptblock]::Create($s))"
    enc = base64.b64encode(bootstrap.encode('utf-16le')).decode()
    payload = base64.b64encode(script.encode('utf-16le')).decode()
    p = subprocess.run(['ssh', *OPTS, 'spaghetti', 'powershell -NoProfile -NonInteractive -EncodedCommand ' + enc],
                       input=payload, capture_output=True, text=True, errors='replace', timeout=timeout)
    out = '\n'.join(l for l in p.stdout.splitlines() if not l.startswith(('#< CLIXML', '<Objs')))
    if p.returncode:
        import re
        errors = re.findall(r'<S S="Error">(.*?)</S>', p.stdout + p.stderr)
        raise RuntimeError(''.join(errors).replace('_x000D__x000A_', '\n')[-2000:] or (out + p.stderr)[-2000:])
    return out.strip().lstrip('\ufeff')


def scp(local, remote, recursive=False):
    p = subprocess.run(['scp', *OPTS, *(['-r'] if recursive else []), str(local), 'spaghetti:' + remote.replace('\\', '/')],
                       capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f'scp {local}: {p.stderr}')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def install():
    dll = sha(DLL)
    print(ps(rf'''$ErrorActionPreference='Stop'
$g='{GAME}'
if (Get-Process NieRAutomata -ErrorAction SilentlyContinue) {{ throw 'NieR is running' }}
if (Test-Path -LiteralPath (Join-Path $g 'd3d11_dlaa.dll')) {{ throw 'd3d11_dlaa.dll already present: installed already?' }}
$h=(Get-FileHash -LiteralPath (Join-Path $g 'd3d11.dll') -Algorithm SHA256).Hash.ToLowerInvariant()
if (-not $h.StartsWith('{ORIGINAL_D3D11}')) {{ throw "unexpected d3d11.dll $h" }}
New-Item -ItemType Directory -Force -Path '{BACKUP}','{WORK}\scene' | Out-Null
Copy-Item -LiteralPath (Join-Path $g 'd3d11.dll') -Destination '{BACKUP}\d3d11.dll' -Force
if ((Get-FileHash -LiteralPath '{BACKUP}\d3d11.dll' -Algorithm SHA256).Hash.ToLowerInvariant() -ne $h) {{ throw 'backup mismatch' }}
foreach ($f in {', '.join(repr(x) for x in ADDED)}) {{ if (Test-Path -LiteralPath (Join-Path $g $f)) {{ throw "$f already in the game folder" }} }}
'backup ok ' + $h'''))
    scp(DLL, WORK + r'\d3d11.dll')
    scp(FONTS, WORK + r'\nier_render_fonts', recursive=True)
    for f in ('scene.bin', 'scene_sky.dds', 'nier_sky_hdr.dds'):
        scp(SCENE / f, WORK + r'\scene\\' + f)
    scp(SCENE / 'scene_textures', WORK + r'\scene\scene_textures', recursive=True)
    print(ps(rf'''$ErrorActionPreference='Stop'
$g='{GAME}'
if ((Get-FileHash -LiteralPath '{WORK}\d3d11.dll' -Algorithm SHA256).Hash.ToLowerInvariant() -ne '{dll}') {{ throw 'transfer hash mismatch' }}
Move-Item -LiteralPath (Join-Path $g 'd3d11.dll') -Destination (Join-Path $g 'd3d11_dlaa.dll')
Copy-Item -LiteralPath '{WORK}\d3d11.dll' -Destination (Join-Path $g 'd3d11.dll')
Copy-Item -LiteralPath '{WORK}\nier_render_fonts' -Destination (Join-Path $g 'nier_render_fonts') -Recurse
Set-Content -LiteralPath (Join-Path $g 'NIER_RENDER.ini') -Value "[Rendering]`r`nPreset=Native" -NoNewline -Encoding ascii
Set-Content -LiteralPath (Join-Path $g 'steam_appid.txt') -Value '524220' -NoNewline -Encoding ascii
if ((Get-FileHash -LiteralPath (Join-Path $g 'd3d11.dll') -Algorithm SHA256).Hash.ToLowerInvariant() -ne '{dll}') {{ throw 'installed hash mismatch' }}
'installed {dll[:16]}' '''))


def run(label, remix, seconds, no_ec_hooks=False, steam=False, live=False):
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    remix = remix or live
    env = {'NIER_REMIX': '1' if remix else '0'}
    if remix:
        env.update(NIER_REMIX_RUNTIME=RUNTIME, NIER_REMIX_SCENE=WORK + r'\scene\scene.bin')
    if live:
        env.update(NIER_REMIX_LIVE='1', NIER_REMIX_LIVE_TEX=WORK + r'\live-textures', NIER_REMIX_LIVE_STATS_EVERY='60')
    # --steam: settings go into NIER_ENV.ini and Steam starts the game, so per-game Steam settings (overlay) apply.
    env_ini = base64.b64encode(''.join(f'{k}={v}\r\n' for k, v in env.items()).encode('utf-8')).decode()
    launch = ('@echo off\r\n"C:\\Program Files (x86)\\Steam\\steam.exe" -applaunch 524220\r\n' if steam else
              '@echo off\r\n' + ''.join(f'set "{k}={v}"\r\n' for k, v in env.items()) +
              f'cd /d "{GAME}"\r\nstart "" NieRAutomata.exe\r\n')
    launch_b64 = base64.b64encode(launch.encode('ascii')).decode()
    receipt = json.loads(ps(rf'''$ErrorActionPreference='Stop'
$g='{GAME}'
if (Get-Process NieRAutomata -ErrorAction SilentlyContinue) {{ throw 'NieR is already running' }}
$log=Join-Path $g 'NIER_SCALE.log'; $before=if (Test-Path -LiteralPath $log) {{ (Get-Item -LiteralPath $log).Length }} else {{ 0 }}
$ec=Join-Path $g 'ec_hooks.dll'
if ({'$true' if no_ec_hooks else '$false'}) {{ Rename-Item -LiteralPath $ec -NewName 'ec_hooks.dll.off' }}  # the DLAA's hook library writes into "the d3d11 module": ours
$envfile=Join-Path $g 'NIER_ENV.ini'
if ({'$true' if steam else '$false'}) {{ [IO.File]::WriteAllBytes($envfile,[Convert]::FromBase64String('{env_ini}')) }} elseif (Test-Path -LiteralPath $envfile) {{ Remove-Item -LiteralPath $envfile }}
$cmd='{WORK}\launch-{label}.cmd'
[IO.File]::WriteAllBytes($cmd, [Convert]::FromBase64String('{launch_b64}'))
$a=New-ScheduledTaskAction -Execute 'cmd.exe' -Argument ('/c "'+$cmd+'"')
$pr=New-ScheduledTaskPrincipal -UserId (whoami) -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName NieRPort -Action $a -Principal $pr -Settings $settings -Force | Out-Null
$start=Get-Date; Start-ScheduledTask NieRPort; Start-Sleep 5
$taskResult=(Get-ScheduledTaskInfo NieRPort).LastTaskResult
Unregister-ScheduledTask NieRPort -Confirm:$false
Start-Sleep {20 if steam else 0}  # Steam needs a moment to hand the launch to the game
$seen=@(); $t=[Diagnostics.Stopwatch]::StartNew()
while ($t.Elapsed.TotalSeconds -lt {seconds}) {{ $p=Get-Process NieRAutomata -ErrorAction SilentlyContinue; if ($p) {{ $seen+=$p.Id }}; Start-Sleep 2 }}
$alive=Get-Process NieRAutomata -ErrorAction SilentlyContinue
$ids=@($seen | Sort-Object -Unique)
if ($alive) {{ $alive | Stop-Process -Force; Start-Sleep 3 }}
if (Test-Path -LiteralPath "$ec.off") {{ Rename-Item -LiteralPath "$ec.off" -NewName 'ec_hooks.dll' }}
$text=if (Test-Path -LiteralPath $log) {{ $b=[IO.File]::ReadAllBytes($log); [Text.Encoding]::UTF8.GetString($b, $before, $b.Length-$before) }} else {{ '' }}
$wer=@(try {{ Get-WinEvent -FilterHashtable @{{LogName='Application'; ProviderName='Application Error'; StartTime=$start}} -ErrorAction Stop | Where-Object {{ $_.Message -like '*NieRAutomata*' }} | Select-Object -First 2 | ForEach-Object {{ $_.Message.Substring(0,[Math]::Min(600,$_.Message.Length)) }} }} catch {{ }})
[ordered]@{{label='{label}'; remix=${str(remix).lower()}; pids=$ids; task_result=$taskResult; alive_at_end=[bool]$alive; log=$text; crash=@($wer)}} | ConvertTo-Json -Depth 3 -Compress''', timeout=seconds + 240))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f'{label}-{stamp}.json').write_text(json.dumps(receipt, indent=2) + '\n')
    lines = [l for l in (receipt.get('log') or '').splitlines() if l.strip()]
    print(f"{label}: pids={receipt['pids']} task_result={receipt['task_result']} alive_at_end={receipt['alive_at_end']} log_lines={len(lines)} crash={bool(receipt['crash'])}")
    if not receipt['pids'] and not lines:
        print('NO LAUNCH OBSERVED: this run did not test the proxy.')
    for l in lines[-25:]:
        print('  ' + l[:220])


def restore():
    print(ps(rf'''$ErrorActionPreference='Stop'
$g='{GAME}'
if (Get-Process NieRAutomata -ErrorAction SilentlyContinue) {{ throw 'NieR is running' }}
$h=(Get-FileHash -LiteralPath '{BACKUP}\d3d11.dll' -Algorithm SHA256).Hash.ToLowerInvariant()
if (-not $h.StartsWith('{ORIGINAL_D3D11}')) {{ throw "backup is not the original: $h" }}
Copy-Item -LiteralPath '{BACKUP}\d3d11.dll' -Destination (Join-Path $g 'd3d11.dll') -Force
foreach ($f in {', '.join(repr(x) for x in ADDED)}) {{ $p=Join-Path $g $f; if (Test-Path -LiteralPath $p) {{ Remove-Item -LiteralPath $p -Recurse -Force }} }}
if (Test-Path -LiteralPath (Join-Path $g 'ec_hooks.dll.off')) {{ Rename-Item -LiteralPath (Join-Path $g 'ec_hooks.dll.off') -NewName 'ec_hooks.dll' }}
$now=(Get-FileHash -LiteralPath (Join-Path $g 'd3d11.dll') -Algorithm SHA256).Hash.ToLowerInvariant()
if ($now -ne $h) {{ throw 'restore hash mismatch' }}
'restored ' + $now.Substring(0,16) + '; game folder: ' + ((Get-ChildItem -LiteralPath $g -File -Name | Where-Object {{ $_ -match '\.(dll|ini|txt)$' }}) -join ', ')'''))


if __name__ == '__main__':
    cmd = sys.argv[1:] or ['']
    if cmd[0] == 'install':
        install()
    elif cmd[0] == 'restore':
        restore()
    elif cmd[0] == 'run' and len(cmd) >= 2:
        seconds = int(cmd[cmd.index('--seconds') + 1]) if '--seconds' in cmd else 90
        run(cmd[1], '--remix' in cmd, seconds, '--no-ec-hooks' in cmd, '--steam' in cmd, '--live' in cmd)
    else:
        sys.exit(__doc__)
