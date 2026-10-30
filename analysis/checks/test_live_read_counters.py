#!/usr/bin/env python3
"""Gate: the live stats lines say where game-thread readbacks come from and where the Remix worker's time goes.

The 2026-10-29 live log could not answer either question: "readback 152 ms" was the worker's wait for Remix's frame,
not a game-thread buffer read, and no line counted buffer reads at all. This pins the new lines:
  - `remix: live reads=N first= trimmed= unmirrored= const= immutable= default= dynamic= read_kb= read_ms= texture_ms=
    skinned=`, cumulative: reasons and kinds each sum to `reads`, and each reason is produced by the scenario that
    causes it (a write too large to mirror -> unmirrored; static bytes dropped by the shadow budget, then an evicted
    mesh rebuilt -> trimmed). `reads` never exceeds the staging copies the mock game itself observed.
  - `remix: N fps over the last N frames (ms/frame: update, submit, present, copy, readback, convert, publish, other)`.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

C = Path(__file__).resolve().parent
A = C.parent
OUT = A / 'runtime/live-read-counters'
import test_remix_live as tr
import test_menu_overlay as tmo
import test_nscn_scene as ts

tr.ENV_KEYS = tuple(tr.ENV_KEYS) + ('NIER_REMIX_LIVE', 'NIER_REMIX_LIVE_TEX', 'NIER_REMIX_LIVE_STATS_EVERY',
                                     'NIER_REMIX_LIVE_MAX_WRITE_KB', 'NIER_REMIX_LIVE_SHADOW_KB', 'NIER_REMIX_LIVE_BUDGET_KB')
KEYS = ('reads', 'first', 'trimmed', 'unmirrored', 'const', 'immutable', 'default', 'dynamic', 'read_kb', 'read_ms',
        'texture_ms', 'skinned', 'created')


def reads(log):
    lines = [x for x in tr.remix_lines(log) if x.startswith('remix: live reads=')]
    assert lines, 'no "live reads=" stats line: ' + str(tr.remix_lines(log)[-6:])
    last = dict(re.findall(r'(\w+)=(\d+)', lines[-1]))
    assert set(KEYS) <= set(last), lines[-1]
    v = {k: int(last[k]) for k in KEYS}
    assert v['first'] + v['trimmed'] + v['unmirrored'] == v['reads'], f'reasons do not sum to reads: {lines[-1]}'
    assert v['const'] + v['immutable'] + v['default'] + v['dynamic'] == v['reads'], f'kinds do not sum to reads: {lines[-1]}'
    return v


def inside():
    work = Path(tempfile.mkdtemp(prefix='run-', dir=OUT))
    results = {}
    try:
        tmo.build(work)
        subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-shared',
                        '-static', '-static-libgcc', '-static-libstdc++', '-isystem', str(A / 'remix-probe/vendor'),
                        str(C / 'remix_live_fake_runtime.cpp'), '-ld3d9', '-o', str(work / 'fake_remix.dll')], check=True)
        scene = work / 'scene'
        (scene / 'scene_textures').mkdir(parents=True)
        (scene / 'scene.bin').write_bytes(ts.scene_bytes(ts.CAMERA, ts.DRAWS, ts.TEXTURES, ts.TRIS))

        def run(name, extra):
            tex = work / f'tex-{name}'
            tex.mkdir()
            env = {'NIER_REMIX_RUNTIME': tr.win(work / 'fake_remix.dll'), 'NIER_REMIX_SCENE': tr.win(scene / 'scene.bin'),
                   'MOCK_FRAME_MS': '40', 'NIER_REMIX': '1', 'NIER_REMIX_LIVE': '1', 'NIER_REMIX_LIVE_TEX': tr.win(tex),
                   'MOCK_CAMERA': 'live', 'NIER_REMIX_LIVE_STATS_EVERY': '10', **extra}
            _, r, log, fake = tr.run(work, name, env)
            assert fake and 'VIOLATION' not in fake, (fake or '')[-1500:]
            r['fake'] = fake
            return r, log

        # 1. Every Map write is too large to mirror (threshold 0): the mesh whose dynamic buffer is rewritten at frame 50
        #    must be read back for that reason, and the per-stage timing line must carry the new fields.
        r, log = run('unmirrored', {'NIER_REMIX_LIVE_MAX_WRITE_KB': '0'})
        v = reads(log)
        assert v['unmirrored'] >= 1, f'a write that was not mirrored produced no unmirrored read: {v}'
        assert v['dynamic'] >= 1, f'the rewritten dynamic vertex buffer was not counted as dynamic: {v}'
        spied = int(r['geometry_reads']) + int(r['camera_reads'])
        assert 0 < v['reads'] <= spied, f'counted {v["reads"]} reads, the mock saw {spied} staging copies: {r}'
        fps = [x for x in tr.remix_lines(log) if 'fps over the last' in x]
        assert fps, 'no fps line with NIER_REMIX_LIVE_STATS_EVERY=10'
        for field in ('update', 'submit', 'present', 'copy', 'readback', 'convert', 'publish', 'other'):
            assert re.search(rf'\b{field} -?[\d.]+', fps[-1]), f'fps line lacks "{field}": {fps[-1]}'
        results['unmirrored'] = f'{v}; fps line: {fps[-1]}'

        # 2. Shadow budget of 1 KB plus a mesh budget for two meshes: B's static bytes are dropped, B is evicted while
        #    unused and drawn again from frame 65, so its rebuild must re-read bytes dropped by the budget.
        r, log = run('trimmed', {'MOCK_CAMERA': 'live-evict', 'NIER_REMIX_LIVE_SHADOW_KB': '1',
                                 'NIER_REMIX_LIVE_BUDGET_KB': '12'})
        v = reads(log)
        assert v['trimmed'] >= 1, f'an evicted mesh rebuilt from dropped static bytes produced no trimmed read: {v}'
        results['trimmed'] = str(v)

        # 3. Default settings: geometry is mirrored and nothing is dropped, so the only reasons are first sight.
        r, log = run('default', {})
        v = reads(log)
        assert v['trimmed'] == 0 and v['unmirrored'] == 0 and v['first'] >= 1, f'default run: {v}'
        results['default'] = str(v)

        # 4. An immutable mesh created with initial data at frame 60, after Remix started: it must be built (z = 7.5)
        #    from the bytes kept at creation, with no staging read of any vertex or index buffer from frame 60 on.
        r, log = run('created', {'MOCK_LATE_IMMUTABLE': '1'})
        v = reads(log)
        late = [x for x in r['fake'].splitlines() if x.startswith('CreateMesh') and ',7.500 ' in x]
        assert late, 'the late immutable mesh was never built'
        assert v['created'] >= 2, f'the late immutable vertex/index buffers were not captured at creation: {v}'
        assert r['geometry_reads_late'] == '0', f'the late immutable mesh was read back from the GPU: {r} {v}'
        results['created'] = f'{v}; geometry_reads_late={r["geometry_reads_late"]}'
    except Exception as exc:
        (OUT / 'validation.json').write_text(json.dumps({'passed': False, 'error': str(exc)[-3000:], 'results': results,
                                                         'work': str(work)}, indent=2) + '\n')
        raise
    finally:
        subprocess.run(['wineserver', '-k'], env=os.environ, capture_output=True)
    report = {'passed': True, 'results': results,
              'limits': 'Wine mock with a fake Remix: pins the counting and the log format, not the real game\'s numbers.'}
    (OUT / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


def main():
    if sys.argv[1:] == ['--inside']:
        return inside()
    for name in ('prefix', 'home', 'cache', 'xdg'):
        (OUT / name).mkdir(parents=True, exist_ok=True)
    (OUT / 'xdg').chmod(0o700)
    assert not (OUT / 'prefix').is_symlink()
    env = os.environ.copy()
    for k in tr.ENV_KEYS:
        env.pop(k, None)
    env.update(WINEPREFIX=str(OUT / 'prefix'), HOME=str(OUT / 'home'), XDG_CACHE_HOME=str(OUT / 'cache'),
               XDG_RUNTIME_DIR=str(OUT / 'xdg'), WINEDEBUG='-all', WAYLAND_DISPLAY='', LIBGL_ALWAYS_SOFTWARE='1',
               GALLIUM_DRIVER='llvmpipe', WINEDLLOVERRIDES='d3d11=n,b;winemenubuilder.exe=d;mscoree,mshtml=')
    subprocess.run(['xvfb-run', '-a', '-s', '-screen 0 1920x1080x24', sys.executable, str(Path(__file__).resolve()), '--inside'],
                   cwd=OUT, env=env, check=True)


if __name__ == '__main__':
    main()
