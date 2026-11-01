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

tr.ENV_KEYS = tuple(tr.ENV_KEYS) + ('NIER_REMIX_LIVE_CAMERA_LOG', 'NIER_REMIX_LIVE', 'NIER_REMIX_LIVE_TEX', 'NIER_REMIX_LIVE_STATS_EVERY',
                                     'NIER_REMIX_LIVE_MAX_WRITE_KB', 'NIER_REMIX_LIVE_SHADOW_KB', 'NIER_REMIX_LIVE_BUDGET_KB',
                                     'NIER_REMIX_LIVE_ASYNC_READS', 'NIER_REMIX_LIVE_READ_LATENCY',
                                     'MOCK_LATE_IMMUTABLE', 'MOCK_LIVE_REWRITE_SAME', 'MOCK_SHARED_REWRITE', 'NIER_REMIX_LIVE_PRESENCE_MIN', 'FAKE_REMIX_INSTANCE_LOG',
                                     'NIER_REMIX_LIVE_BUILD_BUDGET_US', 'NIER_REMIX_LIVE_TEX_WRITE_DELAY_MS',
                                     'NIER_REMIX_TEST_FRAME_MS')  # tr.run clears only these: a case's switch must not leak
KEYS = ('reads', 'first', 'trimmed', 'unmirrored', 'const', 'immutable', 'default', 'dynamic', 'read_kb', 'read_ms',
        'texture_ms', 'skinned', 'created', 'blocking', 'pending', 'waits')


REASONS = ('first', 'unknown', 'buffer', 'pose', 'texture', 'evicted')


def rebuilds(log):
    # Why geometries were rebuilt: the live world popped in and out on the laptop (2026-10-30) while ~250 meshes a
    # second were rebuilt, and the cause could not be told from the totals.
    lines = [x for x in tr.remix_lines(log) if x.startswith('remix: live rebuilds ')]
    assert lines, 'no "live rebuilds" stats line: ' + str(tr.remix_lines(log)[-6:])
    last = dict(re.findall(r'(\w+)=(\d+)', lines[-1]))
    assert set(REASONS) <= set(last), lines[-1]
    # Stall diagnostics (2026-10-31): per-window game frame count and worst interval, and the buffer-rebuild split.
    assert {'buffer_skinned', 'buffer_dynamic', 'game_frames', 'game_max_ms', 'worst_capture_ms', 'worst_hook_ms',
            'worst_present_ms'} <= set(last), lines[-1]
    for x in lines:  # the slowest observe()'s exclusive phases cannot exceed it (1 ms rounding each)
        d = {k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', x)}
        assert d['slow_reads_ms'] + d['slow_texture_ms'] + d['slow_build_ms'] <= d['slow_observe_ms'] + 3, x
    for x in lines:  # the breakdown belongs to the worst frame, so its parts cannot exceed it (1 ms rounding each)
        d = {k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', x)}
        assert d['worst_capture_ms'] + d['worst_hook_ms'] + d['worst_present_ms'] <= d['game_max_ms'] + 3, x
    assert any(int(dict(re.findall(r'(\w+)=(\d+)', x))['game_frames']) > 0 for x in lines), lines[-3:]
    assert int(last['buffer_skinned']) <= int(last['buffer']) and int(last['buffer_dynamic']) <= int(last['buffer']), lines[-1]
    return {k: int(last[k]) for k in REASONS}


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
        # Control for case 5: in the default (synchronous) mode every read stalls the game thread.
        assert v['blocking'] == v['reads'] and v['pending'] == 0 and v['waits'] == 0, f'sync reads not counted as blocking: {v}'
        sync_meshes = sorted({re.search(r'v0=(\S+)', x).group(1) for x in r['fake'].splitlines() if x.startswith('CreateMesh')})
        results['unmirrored'] = f'{v}; fps line: {fps[-1]}'

        # 2. Shadow budget of 1 KB plus a mesh budget for two meshes: B's static bytes are dropped, B is evicted while
        #    unused and drawn again from frame 65, so its rebuild must re-read bytes dropped by the budget.
        r, log = run('trimmed', {'MOCK_CAMERA': 'live-evict', 'NIER_REMIX_LIVE_SHADOW_KB': '1',
                                 'NIER_REMIX_LIVE_BUDGET_KB': '12'})
        v = reads(log)
        assert v['trimmed'] >= 1, f'an evicted mesh rebuilt from dropped static bytes produced no trimmed read: {v}'
        why = rebuilds(log)
        assert why['evicted'] >= 1, f'the evicted mesh drawn again was not counted as an eviction rebuild: {why}'
        results['trimmed'] = f'{v}; rebuilds {why}'

        # 3. Default settings: geometry is mirrored and nothing is dropped, so the only reasons are first sight.
        r, log = run('default', {})
        v = reads(log)
        assert v['trimmed'] == 0 and v['unmirrored'] == 0 and v['first'] >= 1, f'default run: {v}'
        assert not [x for x in tr.remix_lines(log) if 'live camera frame=' in x], 'camera log is on by default'
        why = rebuilds(log)
        # 'live' draws mesh A, adds mesh B at frame 35 and rewrites A's dynamic buffer at frame 48: two first sights and
        # exactly one buffer rebuild; nothing is skinned, evicted or waiting for a texture. A first sight of a buffer
        # created before the capture hooks armed has no tracked version yet and is counted as 'unknown', not 'first'.
        assert why['first'] + why['unknown'] >= 2 and why['buffer'] == 1, f'default run rebuild reasons: {why}'
        assert why['pose'] == 0 and why['evicted'] == 0 and why['texture'] == 0, f'default run rebuild reasons: {why}'
        default_meshes = sorted({re.search(r'v0=(\S+)', x).group(1) for x in r['fake'].splitlines() if x.startswith('CreateMesh')})
        results['default'] = f'{v}; rebuilds {why}'

        # 3b. NIER_REMIX_LIVE_CAMERA_LOG=1: one line per live frame, captured camera next to the game's own camera. The mock
        #     has nothing mapped at the game's camera address, so the guarded read must report instead of faulting.
        r, log = run('camera-log', {'NIER_REMIX_LIVE_CAMERA_LOG': '1'})
        cams = [x for x in tr.remix_lines(log) if 'live camera frame=' in x]
        assert len(cams) >= 20, f'expected one camera line per live frame, got {len(cams)}'
        assert all('game=unreadable' in x and re.search(r'captured=-?[\d.]+,-?[\d.]+,-?[\d.]+ ', x) for x in cams), cams[:3]
        assert r['presented'] == '80', r
        # The camera comes from the CPU mirror of the game's constant-buffer writes: no blocking staging read per frame
        # (live 2026-10-31: up to 4 per frame), and a camera published on (nearly) every game frame.
        lines = [x for x in tr.remix_lines(log) if x.startswith('remix: live rebuilds ')]
        last = {k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', lines[-1])}
        assert int(r['camera_reads']) <= 2, f'the camera is still read back through staging copies: {r}'
        assert last['camera_cpu'] >= 60, f'the camera was not taken from the CPU mirror: {lines[-1]}'
        assert all(int(dict(re.findall(r'(\w+)=(\d+)', x))['camera_gap_max']) <= 2 for x in lines[1:]), \
            f'game frames without a camera: {[x[-80:] for x in lines]}'
        results['camera-log'] = f'{len(cams)} lines; camera_reads={r["camera_reads"]}; {cams[-1]}'

        # 4. An immutable mesh created with initial data at frame 60, after Remix started: it must be built (z = 7.5)
        #    from the bytes kept at creation, with no staging read of any vertex or index buffer from frame 60 on.
        r, log = run('created', {'MOCK_LATE_IMMUTABLE': '1'})
        v = reads(log)
        late = [x for x in r['fake'].splitlines() if x.startswith('CreateMesh') and ',7.500 ' in x]
        assert late, 'the late immutable mesh was never built'
        assert v['created'] >= 2, f'the late immutable vertex/index buffers were not captured at creation: {v}'
        assert r['geometry_reads_late'] == '0', f'the late immutable mesh was read back from the GPU: {r} {v}'
        results['created'] = f'{v}; geometry_reads_late={r["geometry_reads_late"]}'

        # 5. NIER_REMIX_LIVE_ASYNC_READS=1 (live 2026-10-31: ~60 synchronous reads a second, ~5 ms each whatever their
        #    size, froze the camera in steps). Same scenario as case 1, every read held "still drawing" for 3 polls: the
        #    game thread must never block, the latency path must really be taken, and the same meshes must still be built.
        r, log = run('async', {'NIER_REMIX_LIVE_MAX_WRITE_KB': '0', 'NIER_REMIX_LIVE_ASYNC_READS': '1',
                               'NIER_REMIX_LIVE_READ_LATENCY': '3'})
        v = reads(log)
        assert v['reads'] >= 1 and v['blocking'] == 0, f'async mode still blocked the game thread: {v}'
        assert v['pending'] >= 3 * v['reads'] and v['waits'] >= 1, f'the latency path was not exercised: {v}'
        assert v['unmirrored'] >= 1, f'the rewritten buffer was not re-read asynchronously: {v}'
        async_meshes = sorted({re.search(r'v0=(\S+)', x).group(1) for x in r['fake'].splitlines() if x.startswith('CreateMesh')})
        assert async_meshes == sync_meshes, f'async reads lost or changed geometry: {async_meshes} vs {sync_meshes}'
        assert r['presented'] == '80', r
        results['async'] = f'{v}; meshes {async_meshes}'

        # 6. Async with a buffer the game rewrites EVERY frame (live 2026-10-31 async1: such reads never landed: each
        #    write made the in-flight copy stale and it was re-issued forever, so lights=0 and those meshes froze).
        #    Mesh A's vertex buffer is rewritten each frame and never mirrored: its reads must keep landing, and A must
        #    still be drawn every frame.
        r, log = run('async-rewrite', {'NIER_REMIX_LIVE_MAX_WRITE_KB': '0', 'NIER_REMIX_LIVE_ASYNC_READS': '1',
                                       'NIER_REMIX_LIVE_READ_LATENCY': '1', 'MOCK_LIVE_REWRITE_SAME': '1',
                                       'FAKE_REMIX_INSTANCE_LOG': '1'})
        v = reads(log)
        assert v['blocking'] == 0, f'async mode blocked: {v}'
        assert v['unmirrored'] >= 15, f'reads of a buffer rewritten every frame stopped landing: {v}'
        a_frames = {int(m.group(1)) for x in r['fake'].splitlines()
                    for m in [re.match(r'DrawInstance presented=(\d+)', x)] if m}
        assert len(a_frames) >= 60, f'instances missing on {80 - len(a_frames)} of 80 frames: {sorted(a_frames)[:10]}'
        results['async-rewrite'] = f'{v}; drawn on {len(a_frames)} frames'

        # 6b. Two objects share that every-frame-rewritten buffer (popin-gaps-b4000: four objects sharing one rewritten
        #     slot-2 buffer sat in read_pending for the whole run). A landed read is already stale, so its bytes are a
        #     per-frame snapshot: only the first draw used it, and every later draw found the re-issued copy in flight.
        r, log = run('async-shared', {'NIER_REMIX_LIVE_MAX_WRITE_KB': '0', 'NIER_REMIX_LIVE_ASYNC_READS': '1',
                                      'NIER_REMIX_LIVE_READ_LATENCY': '1', 'MOCK_LIVE_REWRITE_SAME': '1',
                                      'MOCK_SHARED_REWRITE': '1', 'FAKE_REMIX_INSTANCE_LOG': '1',
                                      'NIER_REMIX_LIVE_PRESENCE_MIN': '0'})
        stuck = [x for x in tr.remix_lines(log) if x.startswith('remix: stuck ')]
        assert not stuck, f'an object sharing the rewritten buffer was never built: {stuck[:2]}'
        queue = [dict(re.findall(r'(missing_inst)=(\d+)', x)) for x in tr.remix_lines(log) if x.startswith('remix: presence ')]
        late = [int(q['missing_inst']) for q in queue[10:] if q]
        run_len = longest = 0
        for m in late:  # a rebuild after the mock's content change may miss a frame; a starved object misses all of them
            run_len = run_len + 1 if m else 0
            longest = max(longest, run_len)
        assert late and longest <= 2, f'instances without a mesh for {longest} frames in a row: {late[:40]}'
        per_frame = {}
        for x in r['fake'].splitlines():
            m = re.match(r'DrawInstance presented=(\d+) mesh=(\d+)', x)
            if m:
                per_frame.setdefault(int(m.group(1)), set()).add(m.group(2))
        meshes = set().union(*per_frame.values()) if per_frame else set()
        both = [f for f, ms in per_frame.items() if len(ms) >= 2]
        assert len(meshes) >= 2, f'the second object sharing the rewritten buffer was never built: meshes {meshes}'
        assert len(both) >= 40, f'both objects drawn on only {len(both)} of 80 frames'
        # The bytes are identical every frame: once built, the snapshot's contents must be recognised, not decoded again
        # (popin-hold2-b4000: 380 rebuilds/s of unchanged bytes once snapshots were shared).
        rb = [dict(re.findall(r'(\w+)=(\d+)', x)) for x in tr.remix_lines(log) if x.startswith('remix: live rebuilds ')]
        rd = [dict(re.findall(r'(\w+)=(\d+)', x)) for x in tr.remix_lines(log) if x.startswith('remix: live reads=')]
        skips, rebuilt = int(rd[-1]['stale_skips']), int(rb[-1]['buffer'])
        assert skips >= 40 and rebuilt <= skips // 2, f'unchanged snapshots were decoded again: buffer rebuilds {rebuilt}, skips {skips}'
        results['async-shared'] = f'meshes {len(meshes)}; both drawn on {len(both)} frames; rebuilds {rebuilt}, skipped {skips}'

        # 7. NIER_REMIX_LIVE_BUILD_BUDGET_US (live 2026-10-31 async2: worst game frames of 114-304 ms were our own draw hooks
        #    building hundreds of new meshes in one frame when the camera turned). A 1 us budget allows one new build per
        #    frame: the rest must wait for later frames, and every mesh of the default run must still be built.
        r, log = run('build-budget', {'NIER_REMIX_LIVE_BUILD_BUDGET_US': '1'})
        lines = [x for x in tr.remix_lines(log) if x.startswith('remix: live rebuilds ')]
        deferred = int(dict(re.findall(r'(\w+)=(\d+)', lines[-1]))['build_deferred'])
        assert deferred >= 1, f'the build budget never deferred a build: {lines[-1]}'
        budget_meshes = sorted({re.search(r'v0=(\S+)', x).group(1) for x in r['fake'].splitlines() if x.startswith('CreateMesh')})
        assert budget_meshes == default_meshes, f'the budget lost geometry: {budget_meshes} vs {default_meshes}'
        results['build-budget'] = f'build_deferred={deferred}; meshes {budget_meshes}'

        # 8. NIER_REMIX_LIVE_TEX_WRITE_DELAY_MS=400 (live 2026-10-31 cam1: the screen froze for 1.1 s exactly when new DDS
        #    files were created, and the file write ran on the game's thread). Every texture write now takes 400 ms: the
        #    game must keep its frame time (mock frames are 40 ms) and the textures must still reach the disk.
        r, log = run('slow-disk', {'NIER_REMIX_LIVE_TEX_WRITE_DELAY_MS': '400'})
        dds = sorted(p.name for p in (work / 'tex-slow-disk').glob('live_*.dds'))
        assert dds, 'no texture reached the disk'
        lines = [x for x in tr.remix_lines(log) if x.startswith('remix: live rebuilds ')]
        worst = max(int(dict(re.findall(r'(\w+)=(\d+)', x))['game_max_ms']) for x in lines)
        assert worst < 250, f'a texture write stalled the game thread: worst game frame {worst} ms'
        results['slow-disk'] = f'{dds}; worst game frame {worst} ms'

        # 9. A path tracer slower than the game (live: ~15 Remix fps under 40+ game fps). The window must only ever move
        #    forward: the user's recording showed it flipping between the newest and the previous Remix frame on nearly
        #    every present (camera snapping back, characters jittering), because a present swapped `ready` back in after
        #    `shown` had overtaken it. 120 ms worker frames against 40 ms game frames.
        r, log = run('slow-remix', {'NIER_REMIX_TEST_FRAME_MS': '120'})
        lines = [x for x in tr.remix_lines(log) if x.startswith('remix: live rebuilds ')]
        back = int(dict(re.findall(r'(\w+)=(\d+)', lines[-1]))['shown_backwards'])
        assert back == 0, f'the window went back to an older Remix frame {back} times'
        results['slow-remix'] = f'shown_backwards={back} over {r["presented"]} presents'
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
