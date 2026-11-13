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
import signal
import struct
import subprocess
import sys
import time
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


def win(path):
    return 'Z:' + str(Path(path).resolve()).replace('/', '\\')


def build(bin_dir, fake):
    bin_dir.mkdir(parents=True, exist_ok=True)
    jobs = [(R / 'capture_replay.cpp', bin_dir / 'capture_replay.exe', []),
            (C / 'menu_overlay_stub_dlaa.cpp', bin_dir / 'd3d11_dlaa.dll', ['-shared'])]
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
    width, height, fmt = struct.unpack_from('<3I', data, 0)
    image = Image.frombuffer('RGBA', (width, height), data[12:12 + width * height * 4], 'raw',
                             'BGRA' if fmt in (87, 91) else 'RGBA', 0, 1).convert('RGB')
    image.save(png)
    return image


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
    ap.add_argument('--min-indices', type=int, default=0, help='drop captured draws below this index count')
    a = ap.parse_args()

    run = OUT / a.label
    if run.exists():
        shutil.rmtree(run)   # our own output of an earlier run with the same label
    run.mkdir(parents=True)
    build(OUT / 'bin', a.mode == 'fake')
    manifests = []
    for i, frame in enumerate(a.frames_dirs):
        info = pack_capture.pack(frame, run, f'scene{i}', a.min_indices)
        manifests.append(win(run / f'scene{i}.manifest'))
        if not a.size and i == 0 and info['scene_size'][0]:
            a.size = '%dx%d' % info['scene_size']   # the game presented at its scene size on the laptop
        print(f'packed {frame}: {info}', flush=True)
    for name in ('capture_replay.exe', 'd3d11_dlaa.dll'):
        shutil.copy2(OUT / 'bin' / name, run / name)
    shutil.copy2(DLL / 'd3d11.dll', run / 'd3d11.dll')
    shutil.copytree(DLL / 'nier_render_fonts', run / 'nier_render_fonts')
    (run / 'NIER_RENDER.ini').write_bytes(b'[Rendering]\r\nPreset=Native\r\n')
    shots = a.shots or str(a.frames - 1)

    env = {k: v for k, v in os.environ.items() if not k.startswith(('NIER_', 'REPLAY_', 'MOCK_', 'FAKE_'))}
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
    if a.mode == 'fake':
        for name in ('prefix', 'home', 'cache', 'xdg'):
            (OUT / 'wine' / name).mkdir(parents=True, exist_ok=True)
        (OUT / 'wine' / 'xdg').chmod(0o700)
        env.update(WINEPREFIX=str(OUT / 'wine/prefix'), HOME=str(OUT / 'wine/home'), XDG_CACHE_HOME=str(OUT / 'wine/cache'),
                   XDG_RUNTIME_DIR=str(OUT / 'wine/xdg'), WAYLAND_DISPLAY='', LIBGL_ALWAYS_SOFTWARE='1',
                   WINEDLLOVERRIDES='d3d11=n,b;winemenubuilder.exe=d;mscoree,mshtml=')
        cmd = ['xvfb-run', '-a', '-s', f'-screen 0 {a.size}x24', 'wine', *exe]
    else:
        width, height = a.size.split('x')
        env.update(STEAM_COMPAT_CLIENT_INSTALL_PATH=str(Path.home() / '.local/share/Steam'),
                   STEAM_COMPAT_DATA_PATH=str(OUT / 'proton-prefix'), WINEDLLOVERRIDES='d3d11=n,b',
                   MESA_VK_DEVICE_SELECT=a.gpu + '!', DXVK_LOG_LEVEL='info', DXVK_LOG_PATH=win(run))
        (OUT / 'proton-prefix').mkdir(parents=True, exist_ok=True)
        cmd = ['gamescope', '--backend', 'headless', '-W', width, '-H', height, '-w', width, '-h', height, '--',
               str(PROTON), 'run', *exe]
    print('run:', ' '.join(cmd), f'(limit {limit}s)', flush=True)
    started = time.monotonic()
    with open(run / 'host.log', 'wb') as host:
        p = subprocess.Popen(cmd, cwd=run, env=env, stdout=host, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = p.wait(timeout=limit)
        except subprocess.TimeoutExpired:
            code = 'timeout'
        try:
            os.killpg(p.pid, signal.SIGTERM)   # gamescope and anything Proton left behind in this session only
            time.sleep(2)
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    summary = summarise(run)
    summary.update(label=a.label, mode=a.mode, exit=code, seconds=round(time.monotonic() - started, 1),
                   frames=a.frames, frame_ms=a.frame_ms, captures=a.frames_dirs, extra_env=a.env,
                   conf=Path(a.conf).read_text() if a.mode != 'off' else None)
    summary['shots'] = []
    for raw in sorted(run.glob('shot-*.raw')):
        png = raw.with_suffix('.png')
        image = raw_to_png(raw, png)
        raw.unlink()
        summary['shots'].append({'file': str(png), 'size': image.size, 'mean_rgb': [round(v) for v in image.resize((1, 1)).getpixel((0, 0))]})
    (run / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k not in ('conf', 'remix_fps')}, indent=1))
    return 0 if summary['result'].get('presented') == str(a.frames) else 1


if __name__ == '__main__':
    sys.exit(main())
