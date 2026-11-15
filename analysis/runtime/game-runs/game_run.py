#!/usr/bin/env python3
"""Unattended NieR run: headless gamescope + Proton on the RX 6800 XT, screenshots at fixed seconds, menu presses.

  game_run.py <label> [--shots 38,46,70] [--menu-drive "wait:38,press:A:0.3"] [--limit 110] [--live] [--env K=V ...]

Why this exists instead of the shell script: `timeout --foreground gamescope ...` leaves gamescope and its reaper alive
when the game ignores SIGTERM (seen three times on 2026-11-13), which then blocks the next run and the DLL installer.
Here the whole run is one process group that is always killed, the way replay/run_replay.py does it.

Guarantees:
  - copied save paths are validated before launch; real saves are snapshotted before and after.
    A mismatch preserves both versions and fails the run; historical saves are NEVER restored automatically.
  - the game folder is never written by this script; the game writes its own logs and nothing else.
  - nothing survives the run: SIGTERM, then SIGKILL, to the group.
"""
import argparse
import json
import re
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'checks'))
from unattended_guard import authorize, report_run
from game_run_safety import acquire_run_lock, cleanup, owned_pids, release_run_lock, safe_label, snapshot, validate_prefix, verify_save, prepare_private_prefix

A = Path(__file__).resolve().parent.parent.parent     # analysis/  (game-runs -> runtime -> analysis)
RUNS = A / 'runtime' / 'game-runs'
GAME = Path('/mnt/second/SteamLibrary/steamapps/common/NieRAutomata')
PREFIX = RUNS / 'prefix-2026-11-13'
SAVE = Path('/mnt/second/SteamLibrary/steamapps/compatdata/524220/pfx/drive_c/users/steamuser/'
            'Documents/My Games/NieR_Automata')
PROTON = Path('/usr/share/steam/compatibilitytools.d/proton-cachyos-slr/proton')
def safe_size(size):
    parts = size.split('x') if isinstance(size, str) else []
    if len(parts) != 2 or not all(p.isdigit() and int(p) > 0 for p in parts):
        raise ValueError(f'bad display size: {size!r}')
    return int(parts[0]), int(parts[1])


def launch_command(size='1920x1080'):
    width, height = safe_size(size)
    return ['gamescope', '--backend', 'headless', '-W', str(width), '-H', str(height),
            '-w', str(width), '-h', str(height), '--', str(PROTON), 'run', './NieRAutomata.exe']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('label')
    ap.add_argument('--shots', default='', help='seconds after the first present, e.g. 38,46,70')
    ap.add_argument('--menu-drive', default='', help='NIER_REMIX_LIVE_MENU_DRIVE script (press:/wait:/still:)')
    ap.add_argument('--capture-at', default='', help='NIER_CAPTURE_AT: seconds after the first frame to capture (G3)')
    ap.add_argument('--drive', default='', help='NIER_REMIX_LIVE_DRIVE: the world script (still:/turn:/walk:/press:)')
    ap.add_argument('--shots-every', type=float, default=0.0,
                    help='add a screenshot every N seconds over --shots-window (G5 motion runs)')
    ap.add_argument('--shots-window', default='60,120', help='start,end seconds for --shots-every')
    ap.add_argument('--limit', type=int, default=110)
    ap.add_argument('--size', default='1920x1080', help='gamescope display/surface size, e.g. 3440x1440')
    ap.add_argument('--isolated-prefix', action='store_true', help='copy the shared prefix template into this run directory')
    ap.add_argument('--live', action='store_true', help='NIER_REMIX=1 NIER_REMIX_LIVE=1 (Remix path on)')
    ap.add_argument('--template', default=None,
                    help='prefix template under game-runs/ (make_location_prefix.py); non-default needs --isolated-prefix')
    ap.add_argument('--env', action='append', default=[])
    a = ap.parse_args()

    a.label = safe_label(a.label)
    if a.template is not None and (not a.isolated_prefix or not re.fullmatch(r'prefix-[a-z0-9-]+', a.template)
                                      or not (RUNS / a.template).is_dir()):
        print(f'game_run: refused: template {a.template!r} must be a prefix-* folder in {RUNS} and needs --isolated-prefix',
              file=sys.stderr)
        return 2
    authorize('desktop_live_run', a.label)   # no-op unless NIER_UNATTENDED=1
    try:
        lock = acquire_run_lock(Path(os.environ.get('NIER_RUN_LOCK', RUNS / 'run.lock')), a.label)
    except RuntimeError as exc:
        print(f'game_run: refused: {exc}', file=sys.stderr)
        return 2
    try:
        return run_once(a)
    finally:
        release_run_lock(lock)


def run_once(a):
    protected = ('STEAM_COMPAT_', 'WINEPREFIX', 'NIER_RUN_', 'MESA_VK_DEVICE_SELECT')
    for item in a.env:
        key, separator, _ = item.partition('=')
        if not separator or not key or key.startswith(protected):
            ap.error('invalid or safety-critical --env override')
    run = RUNS / a.label
    run.mkdir(parents=True, exist_ok=False)
    token = uuid.uuid4().hex
    template = PREFIX if a.template is None else RUNS / a.template   # default: exactly today's prefix
    prefix = prepare_private_prefix(template, run / 'prefix', token) if a.isolated_prefix else PREFIX
    validate_prefix(prefix, SAVE)
    (run / 'shots').mkdir()
    env = {k: v for k, v in os.environ.items() if k != 'WINEPREFIX' and not k.startswith(('NIER_', 'REPLAY_', 'MOCK_', 'STEAM_COMPAT'))}
    env.update(STEAM_COMPAT_CLIENT_INSTALL_PATH=str(Path.home() / '.local/share/Steam'),
               STEAM_COMPAT_DATA_PATH=str(prefix.resolve()), MESA_VK_DEVICE_SELECT='1002:73bf!',
               WINEDLLOVERRIDES='d3d11=n,b', SteamAppId='524220', STEAMAPPID='524220', SteamGameId='524220',
               DXVK_LOG_LEVEL='info', DXVK_LOG_PATH=str(run))
    shots = a.shots
    if a.shots_every > 0:
        # G5: a burst of frames over a window, so motion (ghosting, pop-in, upscaler stability) can be read afterwards.
        first, last = (float(v) for v in a.shots_window.split(','))
        burst, t = [], first
        while t <= last:
            burst.append(f'{t:.2f}')
            t += a.shots_every
        shots = ','.join(burst)
        print(f'shots: {len(burst)} frames every {a.shots_every}s over {first}-{last}s', flush=True)
    if shots:
        env['NIER_SCREENSHOT_DIR'] = 'Z:' + str((run / 'shots').resolve()).replace('/', '\\')
        env['NIER_SCREENSHOT_AT'] = shots
    if a.capture_at:
        env['NIER_CAPTURE_AT'] = a.capture_at
    if a.drive:
        env['NIER_REMIX_LIVE_DRIVE'] = a.drive
        env['NIER_REMIX_LIVE_DRIVE_MIN_INSTANCES'] = '8'
    if a.menu_drive:
        env['NIER_REMIX_LIVE_MENU_DRIVE'] = a.menu_drive
    if a.live:
        env['NIER_REMIX'] = '1'
        env['NIER_REMIX_LIVE'] = '1'
        env['NIER_REMIX_LIVE_TEX'] = 'Z:' + str((run / 'live-textures').resolve()).replace('/', '\\')
        env['NIER_REMIX_LIVE_STATS_EVERY'] = '60'
        # The real runtime the replays use. The remix-1.6.1 shim (rt/d3d9.dll) reports "enabled" and then never presents:
        # its implementation DLL is loaded by a bare LoadLibraryW, which fails outside the runtime folder.
        env['NIER_REMIX_RUNTIME'] = 'Z:/mnt/second/SteamLibrary/steamapps/common/PortalRTX/bin/.trex/d3d9.dll'
        env['NIER_REMIX_SCENE'] = 'Z:' + str((A / 'runtime' / 'remix-probe' / 'textured-scene' / 'scene.bin').resolve()).replace('/', '\\')
    env['NIER_RUN_TOKEN'] = token  # gamescope can detach; ownership survives in its exact environment marker.
    env['NIER_RUN_LABEL'] = a.label
    for item in a.env:
        key, _, value = item.partition('=')
        env[key] = value

    before = snapshot(SAVE, run / 'save-before')
    cmd = launch_command(a.size)
    print('run:', ' '.join(cmd), f'(limit {a.limit}s)', flush=True)
    started = time.monotonic()
    code, error, forced, errors = 'launch-failed', None, [], []
    child = None
    try:
        with open(run / 'host.log', 'wb') as host:
            child = subprocess.Popen(cmd, cwd=GAME, env=env, stdout=host, stderr=subprocess.STDOUT, start_new_session=True)
            code, seen = 'timeout', False
            while time.monotonic() - started < a.limit:
                time.sleep(0.5)
                running = False
                for pid in owned_pids(token, prefix):
                    try:
                        cmdline = Path(f'/proc/{pid}/cmdline').read_bytes()
                    except OSError:
                        continue
                    if b'NieRAutomata.exe' in cmdline and b'proton' not in cmdline:
                        running = True
                if running:
                    seen = True
                elif seen and time.monotonic() - started > 20:
                    code = 'exit'
                    break
                elif child.poll() is not None and not owned_pids(token, prefix):
                    code = 'exit' if seen else 'launch-failed'
                    break
    except (OSError, KeyboardInterrupt) as exc:
        error = str(exc) or type(exc).__name__
        code = 'launch-failed' if child is None else 'aborted'
    finally:
        try:
            forced = cleanup(token, prefix)
            if child is not None:
                child.wait(timeout=5)
        except Exception as exc:
            errors.append(f'cleanup: {exc}')
        after, save_ok = None, False
        try:
            after, save_ok = verify_save(SAVE, before, run / 'save-after')
        except Exception as exc:
            errors.append(f'save verification: {exc}')
        summary = {'label': a.label, 'template': (a.template or PREFIX.name) if a.isolated_prefix else None, 'exit': code, 'error': error, 'errors': errors,
                   'seconds': round(time.monotonic() - started, 1), 'limit': a.limit,
                   'shots': sorted(p.name for p in (run / 'shots').glob('shot-*.raw')),
                   'menu_drive': a.menu_drive, 'live': a.live, 'extra_env': a.env,
                   'save_before': before, 'save_after': after, 'save_ok': save_ok,
                   'forced_pids': forced, 'save_restored': False}
        (run / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        report_run(summary)
        print(json.dumps({k: v for k, v in summary.items() if k not in ('save_before', 'save_after')}, indent=1))
    return 0 if code == 'exit' and save_ok and not forced and not errors else 1


if __name__ == '__main__':
    sys.exit(main())
