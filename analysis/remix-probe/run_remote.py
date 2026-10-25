#!/usr/bin/env python3
"""Run the built probe once on spaghetti with a watchdog.
Usage: run_remote.py <label> [--sample | --mesh]   (--sample runs NVIDIA's RemixAPI_C control build for 16 frames;
--mesh runs the captured-mesh build from `build.py --mesh`)
Copies the exe into a fresh folder under the existing Downloads probe folder, runs --render with the
Toolkit's x64 runtime, kills ONLY that process after 90s, records thread states if it hung, and copies
back stdout/stderr and Remix's own screenshot (never a desktop capture). No game, no models."""
import argparse
import base64
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'analysis/runtime/remix-probe'
BASE = r'C:\Users\suraj\Downloads\NieR-Remix-Probe-20261025T144235Z'
DLL = r'C:\Program Files\NVIDIA Corporation\RTX Remix\deps\remix_runtime\runtime\.trex\d3d9.dll'
OPTS = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10']


def ps(script):
    enc = base64.b64encode(script.encode('utf-16le')).decode()
    p = subprocess.run(['ssh', *OPTS, 'spaghetti', 'powershell -NoProfile -NonInteractive -EncodedCommand ' + enc],
                       capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError((p.stdout + p.stderr)[-2000:])
    return p.stdout.strip().lstrip('\ufeff')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('label')
    ap.add_argument('--sample', action='store_true')
    ap.add_argument('--mesh', action='store_true')
    ap.add_argument('--hold', action='store_true', help='keep rendering until the 90 s watchdog (probe --hold mode)')
    ap.add_argument('--shot-frame', type=int, default=10, help='DXVK_DUMP_SCREENSHOT_FRAME (default 10)')
    ap.add_argument('--scene', type=Path, help='scene.bin for the remix-scene.exe build (copied next to it)')
    ap.add_argument('--conf', type=Path, help='copied into the run folder as rtx.conf (process working dir only)')
    a = ap.parse_args()
    label = a.label
    assert label.replace('-', '').isalnum(), 'label must be alphanumeric/dashes'
    if a.sample:
        v = json.loads((OUT / 'sample/validation.json').read_text())
        local_exe, exe_name, argv = OUT / 'sample/remixapi_example_c.exe', 'remixapi_example_c.exe', "'16'"
    else:
        variant = 'mesh' if a.mesh else 'scene' if a.scene else None
        v = json.loads((OUT / (f'validation-{variant}.json' if variant else 'validation.json')).read_text())
        assert v['passed']
        exe_name = f'remix-{variant}.exe' if variant else 'remix-triangle.exe'
        local_exe, argv = OUT / exe_name, "('--render \"'+$dll+'\"" + (' --hold' if a.hold else '') + "')"
    proc_name = exe_name[:-4]
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    name = f'{label}-{stamp}'
    remote = json.loads(ps(rf'''$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$p=Join-Path '{BASE}' '{name}'
if(Test-Path -LiteralPath $p){{throw 'Refusing existing folder'}}
New-Item -ItemType Directory -Path (Join-Path $p 'Screenshots') -Force | Out-Null
$p | ConvertTo-Json -Compress'''))
    p = subprocess.run(['scp', *OPTS, str(local_exe), 'spaghetti:' + remote.replace('\\', '/') + '/'],
                       capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError('transfer failed: ' + p.stderr)
    if a.scene:
        p = subprocess.run(['scp', *OPTS, str(a.scene), 'spaghetti:' + remote.replace('\\', '/') + '/scene.bin'],
                           capture_output=True, text=True)
        if p.returncode:
            raise RuntimeError('scene transfer failed: ' + p.stderr)
    if a.conf:
        p = subprocess.run(['scp', *OPTS, str(a.conf), 'spaghetti:' + remote.replace('\\', '/') + '/rtx.conf'],
                           capture_output=True, text=True)
        if p.returncode:
            raise RuntimeError('conf transfer failed: ' + p.stderr)
    run = remote.replace("'", "''")
    result = json.loads(ps(rf'''$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$run='{run}';$exe=Join-Path $run '{exe_name}';$dll='{DLL}'
if((Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant() -ne '{v['exe_sha256']}'){{throw 'Hash mismatch'}}
if(Get-Process -Name remix-triangle,remixapi_example_c -ErrorAction SilentlyContinue){{throw 'Another probe is running'}}
$env:DXVK_DUMP_SCREENSHOT_FRAME='{int(a.shot_frame)}';$env:DXVK_SCREENSHOT_PATH=Join-Path $run 'Screenshots';$env:REMIX_DLL=$dll
$t=[Diagnostics.Stopwatch]::StartNew()
$p=Start-Process -FilePath $exe -ArgumentList {argv} -WorkingDirectory $run -PassThru -RedirectStandardOutput (Join-Path $run 'stdout.txt') -RedirectStandardError (Join-Path $run 'stderr.txt')
$handle=$p.Handle;$done=$p.WaitForExit(90000);$threads=@()
if(-not $done){{
 $p.Refresh()
 $threads=@($p.Threads | ForEach-Object {{ [PSCustomObject]@{{id=$_.Id;state=[string]$_.ThreadState;wait=$(if($_.ThreadState -eq 'Wait'){{[string]$_.WaitReason}}else{{''}});cpu_ms=[int]$_.TotalProcessorTime.TotalMilliseconds}} }})
 $p.Kill();$p.WaitForExit()
}}
$t.Stop();$p.Refresh()
[ordered]@{{run_folder=$run;timed_out=(-not $done);exit_code=$p.ExitCode;elapsed_seconds=$t.Elapsed.TotalSeconds;threads_at_timeout=$threads;stdout=[string](Get-Content -LiteralPath (Join-Path $run 'stdout.txt') -Raw);stderr=[string](Get-Content -LiteralPath (Join-Path $run 'stderr.txt') -Raw);captures=@(Get-ChildItem -LiteralPath (Join-Path $run 'Screenshots') -File | Select-Object Name,Length);remaining=@(Get-Process -Name {proc_name} -ErrorAction SilentlyContinue | Select-Object Id)}} | ConvertTo-Json -Depth 4 -Compress'''))
    result['exe_sha256'] = v['exe_sha256']
    (OUT / f'windows-{name}.json').write_text(json.dumps(result, indent=2) + '\n')
    for item in result['captures']:
        n = item['Name']
        assert Path(n).name == n and item['Length'] <= 32 * 1024 * 1024
        folder = OUT / f'captures-{name}'
        folder.mkdir(exist_ok=True)
        subprocess.run(['scp', *OPTS, 'spaghetti:' + (remote + '\\Screenshots\\' + n).replace('\\', '/'), str(folder / n)],
                       check=True, capture_output=True)
    print(json.dumps({k: result[k] for k in ('run_folder', 'timed_out', 'exit_code', 'elapsed_seconds', 'remaining')}))
    print('captures:', [c['Name'] for c in result['captures']])
    err = result['stderr'] or ''
    print('rtx.conf parsed:', [l[:140] for l in err.splitlines() if 'rtx.conf' in l][:3])
    print('NGX/DLSS log lines:', [l[:140] for l in err.splitlines() if re.search(r'NGX|DLSS|DLFG|upscal', l, re.I)][:8])
    print('tail stages:\n' + '\n'.join((result['stdout'] or '').splitlines()[-8:]))
    if result['threads_at_timeout']:
        states = {}
        for t in result['threads_at_timeout']:
            key = t['state'] + ('/' + t['wait'] if t['wait'] else '')
            states[key] = states.get(key, 0) + 1
        print('threads at timeout:', len(result['threads_at_timeout']), states)
        busy = [t for t in result['threads_at_timeout'] if t['state'] != 'Wait']
        print('non-waiting threads:', busy[:6])
    print('receipt:', OUT / f'windows-{name}.json')


if __name__ == '__main__':
    main()
