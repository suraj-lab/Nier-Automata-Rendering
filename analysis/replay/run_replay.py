#!/usr/bin/env python3
"""Replay an F9 capture through the proxy's live Remix path, without the game and without a visible window.

  run_replay.py <label> <frame_dir> [<frame_dir2>] [options]

  --mode real   (default) the real Remix runtime under Proton, inside a headless gamescope, on --gpu
  --mode fake   Wine + Xvfb + the recording fake runtime (no GPU): what the proxy submits, as text
  --mode off    proxy loaded, NIER_REMIX unset: the replayer and hooks alone (cost baseline)

Output: analysis/runtime/replay/<label>/ with NIER_SCALE.log, replay-result.txt, replay-frames.txt, shot-<n>.png
(what the Present hook handed down: the path-traced frame as the player would see it) and summary.json.
Never touches the game folder, the laptop, or the monitors: the window lives in gamescope's headless output.
"""
import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import uuid
from pathlib import Path

R = Path(__file__).resolve().parent
A = R.parent
C = A / 'checks'
OUT = A / 'runtime' / 'replay'
DLL = A / 'runtime' / 'menu-dll'
PROTON = Path(os.environ.get('PROTON', '/usr/share/steam/compatibilitytools.d/proton-cachyos-slr/proton'))
RUNTIME = A / 'runtime' / 'remix-1.6.1' / 'rt' / 'd3d9.dll'
SCENE = A / 'runtime' / 'remix-probe' / 'textured-scene' / 'scene.bin'   # only its sky DDS is used by a live run
IDLE_GPU = '1002:73bf'   # RX 6800 XT: drives no monitor, so a render never disturbs the desktop
GPP = ['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-static', '-static-libgcc', '-static-libstdc++']
sys.path.insert(0, str(R))
import pack_capture  # noqa: E402
sys.path.insert(0, str(C))
from game_run_safety import cleanup, safe_label, prepare_private_prefix  # noqa: E402
from raw_image import decode_raw  # noqa: E402


def win(path):
    return 'Z:' + str(Path(path).resolve()).replace('/', '\\')


def build(bin_dir, fake):
    bin_dir.mkdir(parents=True, exist_ok=True)
    jobs = [(R / 'capture_replay.cpp', bin_dir / 'capture_replay.exe', []),
            (C / 'menu_overlay_stub_dlaa.cpp', bin_dir / 'd3d11_dlaa.dll', ['-shared']),
            (C / 'exit_monitor.cpp', bin_dir / 'exit_monitor.exe', [])]
    if fake:
        jobs.append((C / 'remix_live_fake_runtime.cpp', bin_dir / 'fake_remix.dll',
                     ['-shared', '-isystem', str(A / 'remix-probe/vendor'), '-ld3d9']))
    for src, dst, flags in jobs:
        if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
            libs = [f for f in flags if f.startswith('-l')]
            subprocess.run([*GPP, *[f for f in flags if not f.startswith('-l')], str(src), *libs, '-o', str(dst)], check=True)


def raw_to_png(raw, png):
    from PIL import Image
    data = raw.read_bytes()
    decode_raw(data)
    width, height, fmt = struct.unpack_from('<3I', data, 0)
    if fmt == 26:
        raise ValueError('HDR/float raw frames cannot be converted to PNG without tone mapping')
    image = Image.frombuffer('RGBA', (width, height), data[12:], 'raw',
                             'BGRA' if fmt in (87, 91) else 'RGBA', 0, 1).convert('RGB')
    image.save(png)
    return image


def read_target_report(path):
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return None
    if not lines or lines[-1] != 'done=1':   # a partial report (pid= only) is not usable yet
        return None
    return dict(line.split('=', 1) for line in lines if '=' in line)


def wait_for_target(p, report, limit, grace):
    """Poll the launcher; once the monitor reports done=1, stop waiting `grace` seconds after the target exited."""
    deadline = time.monotonic() + limit
    done_at = None
    while True:
        code = p.poll()
        if code is not None:
            return code, read_target_report(report)
        if time.monotonic() >= deadline:
            raise subprocess.TimeoutExpired('launcher', limit)
        if done_at is None:
            target = read_target_report(report)
            if target is not None and 'exit_code' in target:
                done_at = time.monotonic()
        elif time.monotonic() - done_at >= grace:
            return 'target-exited', read_target_report(report)
        time.sleep(0.15)


def summarise(run):
    log = (run / 'NIER_SCALE.log').read_text(errors='replace') if (run / 'NIER_SCALE.log').exists() else ''
    out = {'result': dict(line.split('=', 1) for line in (run / 'replay-result.txt').read_text().splitlines()
                          if '=' in line) if (run / 'replay-result.txt').exists() else {}}
    fps = [(float(m.group(1)), {k: float(v) for k, v in re.findall(r'(\w+) ([\d.]+)', m.group(2))})
           for m in re.finditer(r'remix: ([\d.]+) fps over the last \d+ frames \(ms/frame: ([^)]*)\)', log)]
    if fps:
        steady = fps[len(fps) // 2:]   # the first half includes start-up and first-sight builds
        out['remix_fps'] = [f for f, _ in fps]
        out['steady_fps_median'] = sorted(f for f, _ in steady)[len(steady) // 2]
        out['steady_ms'] = {k: round(sum(s[k] for _, s in steady) / len(steady), 2) for k in steady[-1][1]}
    last = lambda pattern: (re.findall(pattern, log) or [None])[-1]
    out['live'] = last(r'remix: (live draws=.*)')
    out['funnel'] = last(r'remix: (funnel .*)')
    out['rebuilds'] = last(r'remix: (live rebuilds .*)')
    out['decode_failures'] = last(r'remix: (decode_failures .*)')
    out['materials'] = len(set(re.findall(r'remix: material ps=(\w+)', log)))
    out['notes'] = sorted(set(re.findall(r'remix: ((?:failed|world gone|world back|live scene target|started|first frame)[^\r\n]*)', log)))[:20]
    rows = [[int(x) for x in line.split()] for line in (run / 'replay-frames.txt').read_text().splitlines()] \
        if (run / 'replay-frames.txt').exists() else []
    for name, column in (('game_frame_us', 0), ('game_draws_us', 1)):   # whole frame; the draw loop alone (rest: Present)
        tail = sorted(r[column] for r in rows[len(rows) // 2:] if len(r) > column)
        if tail:
            out[name] = {'p50': tail[len(tail) // 2], 'p90': tail[len(tail) * 9 // 10], 'p99': tail[len(tail) * 99 // 100],
                         'max': tail[-1]}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('label')
    ap.add_argument('frames_dirs', nargs='+')
    ap.add_argument('--mode', choices=('real', 'fake', 'off'), default='real')
    ap.add_argument('--frames', type=int, default=900)
    ap.add_argument('--frame-ms', type=int, default=16)
    ap.add_argument('--size', default=None, help='backbuffer WxH (default: the capture\'s scene size)')
    ap.add_argument('--shots', default=None, help='frames to dump, e.g. 300,600 (default: the last frame)')
    ap.add_argument('--switch', type=int, default=0, help='with two captures: alternate every N frames')
    ap.add_argument('--conf', default=str(A / 'deploy/rtx/desktop-replay.conf'))
    ap.add_argument('--env', action='append', default=[], help='KEY=VALUE for the run (NIER_*, rtx via --conf)')
    ap.add_argument('--gpu', default=IDLE_GPU)
    ap.add_argument('--runtime', default=str(RUNTIME))
    ap.add_argument('--timeout', type=int, default=0, help='seconds (default: from frames)')
    ap.add_argument('--exit-monitor', action='store_true', help='wrap the replayer in checks/exit_monitor.exe and track the target exit')
    ap.add_argument('--exit-grace', type=int, default=10, help='with --exit-monitor: seconds to wait for the launcher after the target exited')
    ap.add_argument('--min-indices', type=int, default=0, help='drop captured draws below this index count')
    ap.add_argument('--isolated-prefix', action='store_true', help='copy the Wine/Proton template into this run before launch')
    a = ap.parse_args()

    a.label = safe_label(a.label)
    run = OUT / a.label
    if run.exists():
        ap.error('output already exists; choose a fresh label to preserve evidence')
    run.mkdir(parents=True)
    build(OUT / 'bin', a.mode == 'fake')
    manifests = []
    for i, frame in enumerate(a.frames_dirs):
        info = pack_capture.pack(frame, run, f'scene{i}', a.min_indices)
        manifests.append(win(run / f'scene{i}.manifest'))
        if not a.size and i == 0 and info['scene_size'][0]:
            a.size = '%dx%d' % info['scene_size']   # the game presented at its scene size on the laptop
        print(f'packed {frame}: {info}', flush=True)
    for name in ('capture_replay.exe', 'd3d11_dlaa.dll') + (('exit_monitor.exe',) if a.exit_monitor else ()):
        shutil.copy2(OUT / 'bin' / name, run / name)
    shutil.copy2(DLL / 'd3d11.dll', run / 'd3d11.dll')
    shutil.copytree(DLL / 'nier_render_fonts', run / 'nier_render_fonts')
    (run / 'NIER_RENDER.ini').write_bytes(b'[Rendering]\r\nPreset=Native\r\n')
    shots = a.shots or str(a.frames - 1)

    env = {k: v for k, v in os.environ.items() if k != 'WINEPREFIX' and not k.startswith(('NIER_', 'REPLAY_', 'MOCK_', 'FAKE_'))}
    env.update(REPLAY_FRAMES=str(a.frames), REPLAY_FRAME_MS=str(a.frame_ms), REPLAY_SHOTS=shots,
               REPLAY_SWITCH=str(a.switch), WINEDEBUG='-all')
    a.size = a.size or '1920x1200'
    env['REPLAY_SIZE'] = a.size
    if a.mode != 'off':
        runtime = OUT / 'bin' / 'fake_remix.dll' if a.mode == 'fake' else Path(a.runtime)
        shutil.copy2(a.conf, run / 'rtx.conf')
        env.update(NIER_REMIX='1', NIER_REMIX_LIVE='1', NIER_REMIX_RUNTIME=win(runtime), NIER_REMIX_SCENE=win(SCENE),
                   NIER_REMIX_LIVE_TEX=win(run / 'live-textures'), NIER_REMIX_LIVE_STATS_EVERY='60', NIER_REMIX_SIZE=a.size,
                   DXVK_RTX_CONFIG_FILE=win(run / 'rtx.conf'), RTX_HIDE_SPLASH_MESSAGE='1',
                   FAKE_REMIX_INSTANCE_LOG='1')
    for item in a.env:
        key, _, value = item.partition('=')
        env[key] = value
    limit = a.timeout or (a.frames * max(a.frame_ms, 80) // 1000 + 120)
    exe = ['./capture_replay.exe', *manifests]
    if a.exit_monitor:
        exe = ['./exit_monitor.exe', 'target-exit.txt', './capture_replay.exe', *manifests]
    token = uuid.uuid4().hex
    template = OUT / ('wine/prefix' if a.mode == 'fake' else 'proton-prefix')
    template.mkdir(parents=True, exist_ok=True)
    ownership_prefix = prepare_private_prefix(template, run / 'prefix', token) if a.isolated_prefix else template
    if a.mode == 'fake':
        for name in ('prefix', 'home', 'cache', 'xdg'):
            (OUT / 'wine' / name).mkdir(parents=True, exist_ok=True)
        (OUT / 'wine' / 'xdg').chmod(0o700)
        env.update(WINEPREFIX=str(ownership_prefix.resolve()), HOME=str(OUT / 'wine/home'), XDG_CACHE_HOME=str(OUT / 'wine/cache'),
                   XDG_RUNTIME_DIR=str(OUT / 'wine/xdg'), WAYLAND_DISPLAY='', LIBGL_ALWAYS_SOFTWARE='1',
                   WINEDLLOVERRIDES='d3d11=n,b;winemenubuilder.exe=d;mscoree,mshtml=')
        cmd = ['xvfb-run', '-a', '-s', f'-screen 0 {a.size}x24', 'wine', *exe]
    else:
        width, height = a.size.split('x')
        env.update(STEAM_COMPAT_CLIENT_INSTALL_PATH=str(Path.home() / '.local/share/Steam'),
                   STEAM_COMPAT_DATA_PATH=str(ownership_prefix.resolve()), WINEDLLOVERRIDES='d3d11=n,b',
                   MESA_VK_DEVICE_SELECT=a.gpu + '!', DXVK_LOG_LEVEL='info', DXVK_LOG_PATH=win(run))
        (OUT / 'proton-prefix').mkdir(parents=True, exist_ok=True)
        cmd = ['gamescope', '--backend', 'headless', '-W', width, '-H', height, '-w', width, '-h', height, '--',
               str(PROTON), 'run', *exe]
    env.update(NIER_RUN_TOKEN=token, STEAM_COMPAT_DATA_PATH=str(ownership_prefix.resolve()))
    print('run:', ' '.join(cmd), f'(limit {limit}s)', flush=True)
    started = time.monotonic()
    code, errors, forced, p = 'launch-failed', [], [], None
    target_exit, survived = None, False
    try:
        with open(run / 'host.log', 'wb') as host:
            p = subprocess.Popen(cmd, cwd=run, env=env, stdout=host, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                if a.exit_monitor:
                    code, target_exit = wait_for_target(p, run / 'target-exit.txt', limit, a.exit_grace)
                else:
                    code = p.wait(timeout=limit)
            except subprocess.TimeoutExpired:
                code = 'timeout'
    except (OSError, KeyboardInterrupt) as exc:
        errors.append(str(exc) or type(exc).__name__)
        if p is not None:
            code = 'aborted'
    finally:
        try:
            forced = cleanup(token, ownership_prefix)
            if p is not None:
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if code != 'target-exited':
                        raise
                    survived = True   # reported, not an error: the target itself exited
        except Exception as exc:
            errors.append(f'cleanup: {exc}')
    summary = summarise(run)
    if target_exit is not None:
        try:
            target_exit = {'pid': int(target_exit['pid']), 'exit_code': int(target_exit['exit_code']),
                           'elapsed_ms': int(target_exit['elapsed_ms'])}
        except (KeyError, ValueError):
            errors.append(f'target report unusable: {target_exit}')
            target_exit = None
    summary.update(label=a.label, mode=a.mode, prefix=str(ownership_prefix.resolve()), exit=code, errors=errors, forced_pids=forced,
                   seconds=round(time.monotonic() - started, 1),
                   frames=a.frames, frame_ms=a.frame_ms, captures=a.frames_dirs, extra_env=a.env,
                   conf=Path(a.conf).read_text() if a.mode != 'off' else None)
    if a.exit_monitor:
        summary.update(target_exit=target_exit, launcher_survived_cleanup=survived)
    summary['shots'] = []
    for raw in sorted(run.glob('shot-*.raw')):
        png = raw.with_suffix('.png')
        try:
            image = raw_to_png(raw, png)
            summary['shots'].append({'file': str(png), 'size': image.size, 'mean_rgb': [round(v) for v in image.resize((1, 1)).getpixel((0, 0))]})
        except Exception as exc:
            errors.append(f'shot conversion {raw.name}: {exc}')
    (run / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k not in ('conf', 'remix_fps')}, indent=1))
    if a.exit_monitor:
        # a clean target exit passes even with lingering services (reported in forced_pids); the launcher exit code does not matter
        return 0 if (summary['target_exit'] or {}).get('exit_code') == 0 and summary['result'].get('presented') == str(a.frames) and not errors else 1
    return 0 if summary['result'].get('presented') == str(a.frames) and code == 0 and not errors and not forced else 1


if __name__ == '__main__':
    sys.exit(main())
