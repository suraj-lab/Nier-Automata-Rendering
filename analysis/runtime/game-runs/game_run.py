#!/usr/bin/env python3
"""Unattended NieR run: headless gamescope + Proton on the RX 6800 XT, screenshots at fixed seconds, menu presses.

  game_run.py <label> [--shots 38,46,70] [--menu-drive "wait:38,press:A:0.3"] [--limit 110] [--live] [--env K=V ...]

Why this exists instead of the shell script: `timeout --foreground gamescope ...` leaves gamescope and its reaper alive
when the game ignores SIGTERM (seen three times on 2026-11-13), which then blocks the next run and the DLL installer.
Here the whole run is one process group that is always killed, the way replay/run_replay.py does it.

Guarantees:
  - the game's own save folder is hashed before and after; any change is reported and the verified backup is restored
    (runtime/game-runs/save-backup-2026-11-13). The runs themselves use a COPY of the Proton prefix.
  - the game folder is never written by this script; the game writes its own logs and nothing else.
  - nothing survives the run: SIGTERM, then SIGKILL, to the group.
"""
import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

A = Path(__file__).resolve().parent.parent.parent     # analysis/  (game-runs -> runtime -> analysis)
RUNS = A / 'runtime' / 'game-runs'
GAME = Path('/mnt/second/SteamLibrary/steamapps/common/NieRAutomata')
PREFIX = RUNS / 'prefix-2026-11-13'
BACKUP = RUNS / 'save-backup-2026-11-13'
SAVE = Path('/mnt/second/SteamLibrary/steamapps/compatdata/524220/pfx/drive_c/users/steamuser/'
            'Documents/My Games/NieR_Automata')
PROTON = Path('/usr/share/steam/compatibilitytools.d/proton-cachyos-slr/proton')
SAVE_FILES = ('SlotData_0.dat', 'GameData.dat', 'SystemData.dat', 'Graphic.ini')


def hashes():
    return {name: hashlib.sha256((SAVE / name).read_bytes()).hexdigest()
            for name in SAVE_FILES if (SAVE / name).exists()}


def restore(why):
    print(f'save guard: {why} — restoring the verified backup')
    for name in SAVE_FILES:
        if (BACKUP / name).exists():
            shutil.copy2(BACKUP / name, SAVE / name)
    print('save guard: now', json.dumps(hashes(), indent=1))


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
    ap.add_argument('--live', action='store_true', help='NIER_REMIX=1 NIER_REMIX_LIVE=1 (Remix path on)')
    ap.add_argument('--env', action='append', default=[])
    a = ap.parse_args()

    run = RUNS / a.label
    (run / 'shots').mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(('NIER_', 'REPLAY_', 'MOCK_', 'STEAM_COMPAT'))}
    env.update(STEAM_COMPAT_CLIENT_INSTALL_PATH=str(Path.home() / '.local/share/Steam'),
               STEAM_COMPAT_DATA_PATH=str(PREFIX), MESA_VK_DEVICE_SELECT='1002:73bf!',
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
    env['NIER_RUN_LABEL'] = a.label   # marker: gamescope detaches into its own session, so the run is found by env
    for item in a.env:
        key, _, value = item.partition('=')
        env[key] = value

    before = hashes()
    cmd = ['gamescope', '--backend', 'headless', '-W', '1920', '-H', '1080', '-w', '1920', '-h', '1080', '--',
           str(PROTON), 'run', './NieRAutomata.exe']
    print('run:', ' '.join(cmd), f'(limit {a.limit}s)', flush=True)
    def marked():
        """Pids of this run's processes, found by the marker: gamescope calls setsid, so waiting on the child is useless."""
        out = []
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit():
                continue
            try:
                data = (entry / 'environ').read_bytes()
            except OSError:
                continue
            if b'NIER_RUN_LABEL=' + a.label.encode() in data:
                out.append(int(entry.name))
        return out

    started = time.monotonic()
    with open(run / 'host.log', 'wb') as host:
        subprocess.Popen(cmd, cwd=GAME, env=env, stdout=host, stderr=subprocess.STDOUT, start_new_session=True)
        def game_running():
            for entry in Path('/proc').iterdir():
                if not entry.name.isdigit():
                    continue
                try:
                    cmdline = (entry / 'cmdline').read_bytes()
                except OSError:
                    continue
                if b'NieRAutomata.exe' in cmdline and b'proton' not in cmdline:
                    return True
            return False

        seen = False
        while time.monotonic() - started < a.limit:
            time.sleep(0.5)
            if game_running():
                seen = True                              # the game itself is up
            elif seen and time.monotonic() - started > 20:  # ...and gone again: it exited by itself
                break
        code = 'exit' if time.monotonic() - started < a.limit else 'timeout'
        for pid in marked():
            if pid != os.getpid():
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
    after = hashes()
    summary = {'label': a.label, 'exit': code, 'seconds': round(time.monotonic() - started, 1), 'limit': a.limit,
               'shots': sorted(p.name for p in (run / 'shots').glob('shot-*.raw')),
               'menu_drive': a.menu_drive, 'live': a.live, 'extra_env': a.env,
               'save_before': before, 'save_after': after, 'save_ok': before == after}
    if before != after:
        restore('the real save changed during the run')
        summary['save_restored'] = True
    (run / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k not in ('save_before', 'save_after')}, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
