#!/usr/bin/env python3
"""Summarise the LAST live run in NIER_SCALE.log and give one verdict per Phase 1 acceptance row (analysis/ROADMAP.md).

Usage: python3 analysis/checks/analyze_live_run.py [path/to/NIER_SCALE.log]
Default:  /mnt/second/SteamLibrary/steamapps/common/NieRAutomata/NIER_SCALE.log

Read-only. The log is appended to on every launch, so only the lines after the last `remix: enabled` are read.
Rows: 1.1 filter, 1.2 cutout, 1.3 late material, 1.4 untextured, 1.5 lights, 1.8 HUD, 1.9 sky, 1.10 stability,
plus the ms/frame cost split (stage B input). Rows that need eyes on the screen say so ("LOOK").
Gate: analysis/checks/test_analyze_live_run.py feeds it lines built from the DLL's own format strings.
"""
import re
import sys
from pathlib import Path

DEFAULT = Path('/mnt/second/SteamLibrary/steamapps/common/NieRAutomata/NIER_SCALE.log')


def num(line, key, cast=int):
    # Stats lines use key=value, the fps line uses "key value": accept both.
    m = re.search(rf'(?<![\w]){key}[= ]([-\d.]+)', line)
    return cast(m.group(1)) if m else None


def last_run(text):
    lines = [l.split('remix: ', 1)[-1].rstrip() for l in text.splitlines() if 'remix: ' in l]
    starts = [i for i, l in enumerate(lines) if l.startswith('enabled ')]
    return lines[starts[-1]:] if starts else lines, len(starts)


def series(stats, key):
    return [v for v in (num(s, key) for s in stats) if v is not None]


def trend(values):
    return f'first {values[0]}, max {max(values)}, last {values[-1]}' if values else 'not logged'


def main():
    path = Path(sys.argv[1]) if sys.argv[1:] else DEFAULT
    if not path.exists():
        sys.exit(f'no log at {path}')
    lines, runs = last_run(path.read_text(errors='replace'))
    if not lines:
        sys.exit('no remix lines: NIER_REMIX was not set for this run')

    first = next((l for l in lines if l.startswith('live scene first frame')), None)
    stats = [l for l in lines if l.startswith('live draws=')]
    fps_lines = [l for l in lines if 'fps over the last' in l]
    print(f'log            {path} (last of {runs} runs in the file)')
    print(f'run mode       {"LIVE" if first else "captured scene (no live frame)"}; {len(stats)} stats samples '
          f'(one per 300 Remix frames)')
    for line in [l for l in lines if l.startswith(('disabled (', 'paused ', 'resumed ', 'F10 '))][:10]:
        print(f'state          {line}')
    if not first or not stats:
        print('verdict        no live frame or no periodic stats: check NIER_REMIX_LIVE / NIER_REMIX_LIVE_TEX, and run '
              'longer than ~300 Remix frames')
        return
    last = stats[-1]

    def row(item, verdict, detail):
        print(f'{item:<6} {verdict:<5} {detail}')

    print('\n-- Phase 1 acceptance (PASS / FAIL / LOOK = check the screen too) --')
    # 1.1 render-target filter
    # skipped_pass and scene are per frame: a menu or cutscene sample can legitimately show 0, so use the whole run.
    scenes = [m.group(1) for s in stats for m in [re.search(r'scene=(\d+x\d+)', s)] if m and m.group(1) != '0x0']
    latched = any('filter latched off' in l for l in lines)
    draws = series(stats, 'draws')
    skipped = max(series(stats, 'skipped_pass'), default=0)
    if latched:
        row('1.1', 'FAIL', 'the filter latched itself off (3 consecutive empty frames): scene target not recognised')
    elif not scenes or not skipped:
        row('1.1', 'FAIL', f'scene={scenes[-1] if scenes else None} max skipped_pass={skipped}: nothing was filtered')
    else:
        prepass = series(stats, 'prepass')
        verdict = 'PASS' if min(draws) < 2000 else 'FAIL'
        row('1.1', verdict, f'scene={scenes[-1]} max skipped_pass={skipped} draws {trend(draws)} (expect ~1400, not ~2900); '
                            f'pre-pass skipped {trend(prepass)} (expect ~40% of scene draws; 0 = rule not matching)')
    # 1.2 cutout
    blended, tested = series(stats, 'blended'), series(stats, 'alpha_tested')
    row('1.2', 'LOOK' if (blended and max(blended)) or (tested and max(tested)) else 'FAIL',
        f'blended {trend(blended)}; alpha_tested {trend(tested)} (expect ~20% of scene draws: foliage, grass, decals); '
        'on screen: grass and leaves cut out, no streak fields')
    # 1.3 late material: no runaway builds, nothing dropped
    # built is cumulative: an area change builds hundreds of meshes at once, so steady growth across the whole second
    # half of the run is the signal, and it asks for a look (stutter on screen) rather than failing outright.
    built, dropped = series(stats, 'built'), series(stats, 'dropped')
    late = built[len(built) // 2:]
    steps = [b - a for a, b in zip(late, late[1:])]
    runaway = len(steps) >= 3 and min(steps) > 50
    verdict = 'FAIL' if dropped and max(dropped) else ('LOOK' if runaway else 'PASS')
    row('1.3', verdict, f'built {trend(built)}; dropped {trend(dropped)}' + ('; builds never settle' if runaway else ''))
    # 1.4 untextured
    untextured, textures = num(last, 'untextured'), num(last, 'textures')
    share = 100.0 * untextured / draws[-1] if untextured is not None and draws[-1] else None
    if share is None:
        row('1.4', 'FAIL', 'untextured= not logged')
    elif share > 20 and not textures:
        row('1.4', 'FAIL', f'{share:.0f}% untextured, textures=0: the capture path (readback, format, disk budget)')
    elif share > 20:
        row('1.4', 'FAIL', f'{share:.0f}% untextured with {textures} textures: material creation or the albedo heuristic')
    else:
        row('1.4', 'PASS', f'{share:.0f}% untextured, {textures} textures; white surfaces (1.7) are then texture content')
    # 1.5 lights
    lights, creates = series(stats, 'lights'), series(stats, 'light_creates')
    states = [m.group(1) for s_ in stats for m in [re.search(r'light_state=(0x[0-9a-f]+)', s_)] if m]
    if not lights or max(lights) == 0:
        why = {'0x0': 'no scene draw had slot 20 bound', '0x1': 'slot 20 bound but not a buffer view',
               '0x3': 'stride is not 48', '0x7': 'bytes could not be read'}.get(states[-1] if states else '', '')
        row('1.5', 'FAIL', f'lights {trend(lights)}; light_state {states[-1] if states else "not logged"} {why}'.rstrip())
    else:
        churn = len(creates) >= 2 and (creates[-1] - creates[0]) > 10 * max(lights) * (len(creates) - 1)
        row('1.5', 'FAIL' if churn else 'LOOK',
            f'lights {trend(lights)}; light_creates {trend(creates)} (grows with moving lights, not by thousands)')
    # 1.8 HUD
    hud = series(stats, 'hud')
    replay = next((l for l in lines if l.startswith('hud replay draws=')), None)
    if not hud or max(hud) == 0:
        row('1.8', 'FAIL', f'hud {trend(hud)}: no HUD draws captured')
    else:
        failed = replay and ('ok=0' in replay or 'failed=1' in replay)
        row('1.8', 'FAIL' if failed else 'LOOK', f'hud {trend(hud)}; {replay or "replay line not logged"}')
    # 1.9 sky
    sky = series(stats, 'sky')
    row('1.9', 'LOOK' if sky and max(sky) else 'FAIL',
        f'sky {trend(sky)}; on screen: background present, world not inside a shell')
    # 1.10 stability
    stalls = [l for l in lines if 'watchdog' in l]
    meshes, mbytes = series(stats, 'meshes'), series(stats, 'mesh_bytes')
    growing = len(mbytes) >= 4 and mbytes[-1] > 1.5 * mbytes[len(mbytes) // 2] and mbytes[-1] > mbytes[-2]
    enough = len(stats) >= 15
    verdict = 'FAIL' if stalls or growing or (dropped and max(dropped)) else ('PASS' if enough else 'SHORT')
    row('1.10', verdict, f'{len(stats)} samples (need >= 15 for 10 min); meshes {trend(meshes)}; mesh_bytes {trend(mbytes)}; '
                         f'{len(stalls)} watchdog reports' + (f'; last: {stalls[-1]}' if stalls else ''))

    # Cost split, for stage B.
    if fps_lines:
        line = fps_lines[-1]
        split = {k: num(line, k, float) for k in ('update', 'submit', 'present', 'copy', 'readback', 'convert', 'publish', 'other')}
        total = sum(v for v in split.values() if v)
        print(f'\ncost           {line}')
        if split['readback'] is not None and total:
            print(f'               readback is {100 * split["readback"] / total:.0f}% of the frame'
                  + (" — the worker waits on Remix's GPU frame (GetRenderTargetData), not on a copy" if split['readback'] / total > 0.5 else ''))


if __name__ == '__main__':
    main()
