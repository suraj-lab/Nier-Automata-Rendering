#!/usr/bin/env python3
"""Trace gate: real submit outcomes and Wine capture->worker deltas, never a visibility policy."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

C = Path(__file__).resolve().parent
A = C.parent
sys.path.insert(0, str(C))
import test_live_scene as tls
import test_remix_live as tr
import test_menu_overlay as tmo
import test_nscn_scene as ts

OUT = A / 'runtime/live-visibility'
tr.ENV_KEYS = tuple(tr.ENV_KEYS) + ('NIER_REMIX_LIVE', 'NIER_REMIX_LIVE_TEX', 'NIER_REMIX_LIVE_BUDGET',
                                  'NIER_REMIX_LIVE_TRACE', 'FAKE_REMIX_INSTANCE_LOG', 'NIER_REMIX_LIVE_PRESENCE_MIN')
NATIVE = tls.HARNESS.replace('int main() {', 'int original_scene_gate() {') + r'''
#include <cassert>
static remixapi_ErrorCode REMIXAPI_CALL reject_instance(const remixapi_InstanceInfo*) {
    return REMIXAPI_ERROR_CODE_GENERAL_FAILURE;
}
int main() {
    auto api = make_api();
    live_scene::State s;
    s.meshes[10] = reinterpret_cast<remixapi_MeshHandle>(0x1234);
    live_capture::Frame f;
    live_capture::Item a; a.geometry = 10; a.trace_source = 101; a.trace_w = 900; a.trace_h = 600; a.count = 2;
    live_capture::Item missing = a; missing.geometry = 20; missing.trace_source = 202; missing.count = 1;
    f.items = {a, missing};
    f.transforms = {1,0,0,23, 0,1,0,4, 0,0,1,5, 1,0,0,31, 0,1,0,4, 0,0,1,5};
    float camera[14] = {}; camera[12] = 60;
    visibility_trace::Batch b;
    assert(live_scene::submit(api, f, s, camera, 1.5f, &b) == REMIXAPI_ERROR_CODE_SUCCESS);
    assert(b.events.size() == 3 && b.dropped == 0 && last_instances == 2);
    assert(b.events[0].reason == visibility_trace::Reason::Drawn && b.events[0].source == 101);
    assert(b.events[0].target_w == 900 && b.events[0].position[0] == 23 && b.events[1].position[0] == 31);
    assert(b.events[2].reason == visibility_trace::Reason::MeshMissing && b.events[2].geometry == 20);
    assert(s.meshes.size() == 1 && s.evicted == 0); // diagnostics may NOT retain or remove geometry
    f.items[0].count = 3;
    b = {};
    live_scene::submit(api, f, s, camera, 1.5f, &b);
    assert(b.events.size() == 4 && b.events[2].reason == visibility_trace::Reason::BadTransform);
    api.DrawInstance = reject_instance;
    b = {};
    assert(live_scene::submit(api, f, s, camera, 1.5f, &b) != REMIXAPI_ERROR_CODE_SUCCESS);
    assert(b.events.size() == 1 && b.events[0].reason == visibility_trace::Reason::DrawFailed);
    assert(b.events[0].error != 0 && b.dropped != 0); // early abort cannot imply later meshes disappeared
    b = {};
    live_scene::submit(api, live_capture::Frame{}, s, camera, 1.5f, &b);
    assert(b.events.empty() && b.dropped != 0);
    std::puts("actual DrawInstance outcomes, missing meshes, transform bounds, failures, no policy changes");
}
'''


def native(work):
    source = work / 'native.cpp'
    source.write_text(NATIVE)
    p = subprocess.run(['g++', '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                        '-DREMIX_WINAPI_NO_INCLUDE', '-DREMIX_WINAPI_NO_LIBRARY_LOADER', '-D_WIN64=1',
                        '-D__stdcall=', '-D__declspec(x)=', '-isystem', str(tls.VENDOR), '-I', str(C),
                        str(source), '-o', str(work / 'native')], capture_output=True, text=True)
    assert p.returncode == 0, 'native compile: ' + p.stderr[-3500:]
    p = subprocess.run([str(work / 'native')], capture_output=True, text=True)
    assert p.returncode == 0, 'native run: ' + (p.stdout + p.stderr)[-3500:]


def rows(log, stage):
    return [dict(re.findall(r'(\w+)=([^\s]+)', line)) for line in log.splitlines()
            if 'remix: visibility ' + stage + ' ' in line]


def mesh_signature(log):
    """Content-determined evidence of what reached the runtime, independent of frame timing and pointer-derived
    hashes/keys (which differ between processes)."""
    out = []
    for line in log.splitlines():
        if line.startswith('CreateMesh'):
            fields = dict(re.findall(r'(\w+)=([^\s]+)', line))
            out.append(tuple(fields.get(k) for k in ('surfaces', 'verts', 'indices', 'materials', 'skinned',
                                                     'bonesPerVertex', 'weights', 'v0', 'presented')))
    return sorted(out)


def wine(work):
    tmo.build(work)
    p = subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-shared', '-static', '-static-libgcc', '-static-libstdc++', '-isystem', str(tls.VENDOR),
                        str(C / 'remix_live_fake_runtime.cpp'), '-ld3d9', '-o', str(work / 'fake_remix.dll')],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr[-3500:]
    scene = work / 'scene'
    (scene / 'scene_textures').mkdir(parents=True)
    (scene / 'scene.bin').write_bytes(ts.scene_bytes(ts.CAMERA, ts.DRAWS, ts.TEXTURES, ts.TRIS))
    tex = work / 'textures'; tex.mkdir()
    on = {'NIER_REMIX': '1', 'NIER_REMIX_LIVE': '1', 'NIER_REMIX_RUNTIME': tr.win(work / 'fake_remix.dll'),
          'NIER_REMIX_SCENE': tr.win(scene / 'scene.bin'), 'NIER_REMIX_LIVE_TEX': tr.win(tex),
          'NIER_REMIX_LIVE_BUDGET': '3072', 'MOCK_CAMERA': 'live-evict', 'MOCK_FRAME_MS': '60',
          'FAKE_REMIX_INSTANCE_LOG': '1'}
    _, _, off_log, off_fake = tr.run(work, 'trace-off', on)
    assert 'remix: visibility ' not in off_log and 'VIOLATION' not in off_fake
    _, _, log, fake = tr.run(work, 'trace-on', {**on, 'NIER_REMIX_LIVE_TRACE': '1'})
    assert 'VIOLATION' not in fake and not any('disabled' in x for x in tr.remix_lines(log)), log[-3000:]
    # Diagnostics must not change what reaches the runtime: same mesh content, same instance count per draw.
    assert mesh_signature(off_fake) == mesh_signature(fake), 'enabling the trace changed the submitted mesh set'
    assert 'DrawInstance' in fake and mesh_signature(off_fake) == mesh_signature(fake)
    frames = rows(log, 'frame')
    assert len(frames) >= 30, 'no per-capture-sequence trace: ' + log[-3000:]
    seqs = [int(x['seq']) for x in frames]
    assert seqs == sorted(set(seqs)), 'duplicate/backwards trace snapshots'
    capture, submit = rows(log, 'capture'), rows(log, 'submit')
    assert any(x.get('reason') == 'accepted' and x.get('present') == '1' for x in capture), capture[:10]
    assert any(x.get('reason') == 'drawn' and x.get('present') == '1' for x in submit), submit[:10]
    # Every submitted snapshot joins back to its capture snapshot.
    capture_seqs = {x['seq'] for x in capture}
    assert all(x['seq'] in capture_seqs for x in submit), 'submit diagnostics lost their capture join'
    # A retained mesh the game stopped submitting: capture says not_observed, and the worker says the same too.
    # A missing row carries the LAST observed reason, so presence is read from `present`, never from `reason`.
    capture_gone = {(x['geometry'], x['seq']) for x in capture
                    if x.get('present') == '0' and x.get('geometry') != '0'}
    submit_gone = {(x['geometry'], x['seq']) for x in submit if x.get('present') == '0'}
    assert capture_gone & submit_gone, 'disappearance never joined between capture and submission'
    # ... and it must come back, be accepted again, and then actually be DRAWN later in the sequence.
    for geometry in {g for g, _ in (capture_gone & submit_gone)}:
        absent = min(int(s) for g, s in capture_gone if g == geometry)
        # A returned draw is labelled 'accepted' if it had to be rebuilt and 'unchanged' if the mesh still exists;
        # both mean the capture saw it again.
        back = [int(x['seq']) for x in capture
                if x['geometry'] == geometry and x.get('present') == '1'
                and x.get('reason') in ('accepted', 'unchanged')
                and int(x['seq']) > absent]
        if not back:
            continue
        drawn = [int(x['seq']) for x in submit
                 if x['geometry'] == geometry and x.get('reason') == 'drawn' and int(x['seq']) >= back[0]]
        assert drawn, f'{geometry} returned to the capture but was never drawn again'
        ready = [int(x['render']) for x in rows(log, 'render_ready')]
        assert ready and max(ready) >= back[0], 'completion was never reported for the returned mesh'
        break
    else:
        raise AssertionError('no captured mesh disappeared, returned and was drawn again: ' + log[-2500:])
    assert all(int(x.get('evicted', 0)) == 0 for x in rows(log, 'frame')), 'test must falsify eviction-only explanation'

    # Regression for two wasted live runs: the diagnostics must fire with the verbose trace OFF. Both times an
    # always-on counter was incremented inside the TRACE guard, so a live run answered nothing.
    # threshold 1 so the mock's handful of meshes can exercise the watch at all
    _, _, plain_log, plain_fake = tr.run(work, 'presence-off', {**on, 'NIER_REMIX_LIVE_PRESENCE_MIN': '1'})
    lines = [l for l in plain_log.splitlines() if 'remix: presence ' in l]
    assert lines, 'no presence line with the trace off: the watch is gated behind TRACE again'
    explained = 0
    for line in lines:
        f = dict(re.findall(r'([a-z_]+)=(\d+)', line))
        if int(f.get('accepted', 0)) + int(f.get('unchanged', 0)) + int(f.get('pass', 0)) > 0:
            explained += 1
    assert explained, 'presence lines carry no capture counters: the per-frame histogram is dead without TRACE'
    # The camera-motion and screen-fraction fields must be present and live, not zero-filled placeholders.
    fields = [dict(re.findall(r'([a-z_]+)=([-0-9.]+)', l)) for l in lines]
    assert all({'cam_moved', 'cam_turned', 'cam_valid', 'dropped_frac'} <= set(f) for f in fields), lines[:2]
    assert any(f['cam_valid'] == '1' for f in fields), 'camera motion never valid: previous camera not tracked'
    assert all(0.0 <= float(f['dropped_frac']) <= 1.0 for f in fields), [f['dropped_frac'] for f in fields][:5]
    # Attribution: one presence_why per presence line, and its buckets account for every dropped key exactly.
    whys = [l for l in plain_log.splitlines() if 'remix: presence_why ' in l]
    assert len(whys) == len(lines), (len(whys), len(lines))
    for line in whys:
        f = {k: int(v) for k, v in re.findall(r'([a-z_]+)=(\d+)', line)}
        buckets = sum(v for k, v in f.items() if k in ('submit_other', 'churn_occurrence', 'churn_pointer',
                                                        'churn_shape', 'absent') or k.startswith('capture_')
                      and k not in ('capture_overflow', 'capture_events'))
        assert buckets == f['dropped'], f'presence_why is not a closed ledger: {line}'
        assert f['capture_events'] > 0, f'no capture events reach the attribution (it would call everything absent): {line}'
        assert f['known'] == f['dropped'], f'dropped keys without last-frame identity: {line}'
    print('presence_why sample:', whys[:3])
    dropping = [f for f in fields if int(f.get('dropped', 0)) > 0]
    assert dropping and any(float(f['dropped_frac']) > 0.0 for f in dropping), \
        'dropped keys never carry a screen fraction: last-frame coverage is not reaching the presence line'
    # Churn: the same draw re-bound to an identical copy of its vertex buffer every 10 frames. It must be named as
    # churn_pointer with the vertex buffer (and only it) moved, not as a loss.
    _, _, churn_log, _ = tr.run(work, 'churn', {**on, 'NIER_REMIX_LIVE_PRESENCE_MIN': '1', 'MOCK_CHURN_EVERY': '10'})
    churn = [{k: int(v) for k, v in re.findall(r'([a-z_]+)=(\d+)', l)}
             for l in churn_log.splitlines() if 'remix: presence_why ' in l]
    swaps = [f for f in churn if f.get('churn_pointer', 0) > 0]
    assert swaps, f'a re-bound vertex buffer was never attributed as churn_pointer: {churn[:4]}'
    assert all(f['moved_vb'] == f['churn_pointer'] and f['moved_offset'] == f['moved_base'] == f['moved_layout'] ==
               f['moved_other'] == 0 for f in swaps), swaps[:3]
    assert all('missing_now' in f and 'arrived_missing' in f for f in churn), churn[:2]
    print('churn sample:', swaps[:2], 'arrived_missing total', sum(f['arrived_missing'] for f in swaps))
    _, _, log, _ = tr.run(work, 'trace-passes', {**on, 'NIER_REMIX_LIVE_TRACE': '1',
                                               'MOCK_CAMERA': 'live-passes', 'MOCK_PREPASS': '1'})
    capture = rows(log, 'capture')
    assert any(x.get('reason') == 'pass' for x in capture), 'pass rejection not instrumented'
    assert any(x.get('reason') == 'prepass' for x in capture), 'prepass rejection not instrumented'
    _, _, log, _ = tr.run(work, 'trace-sky', {**on, 'NIER_REMIX_LIVE_TRACE': '1', 'NIER_REMIX_LIVE_NO_SKY': '1'})
    assert any(x.get('reason') == 'sky' for x in rows(log, 'capture')), 'sky skip not instrumented'


def inside():
    OUT.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='run-', dir=OUT))
    try:
        native(work)
        if '--native' not in sys.argv:
            wine(work)
        print(json.dumps({'passed': True, 'work': str(work), 'limits': 'Mocks; no claim of engine cull decisions or runtime visibility.'}))
    except Exception as e:
        print(json.dumps({'passed': False, 'work': str(work), 'error': str(e)}))
        return 1
    finally:
        if '--inside' in sys.argv:
            subprocess.run(['wineserver', '-k'], env=os.environ, capture_output=True)
    return 0


def main():
    if '--native' in sys.argv or '--inside' in sys.argv:
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
    p = subprocess.run(['xvfb-run', '-a', '-s', '-screen 0 1920x1080x24', sys.executable,
                        str(Path(__file__).resolve()), '--inside'], cwd=OUT, env=env,
                       capture_output=True, text=True)
    print(p.stdout.strip())
    if p.returncode and p.stderr:
        print(p.stderr[-2500:], file=sys.stderr)
    return p.returncode


if __name__ == '__main__':
    raise SystemExit(main())
