#!/usr/bin/env python3
"""Frozen gate: a geometry whose texture was not captured yet gets its material when the texture lands.

Textures are captured at most `NIER_REMIX_LIVE_TEX_PER_FRAME` per frame (default 4, each is a GPU readback plus a file
write on the game thread). A draw whose texture is deferred is uploaded with no material, and because its geometry
content never changes afterwards, nothing revisits it: the surface stays untextured (white) for the rest of the session.
That is the observed live symptom "most surfaces come out untextured white".

What this gate pins, with two geometries and two textures and a capture budget of one texture per frame:
  - every geometry ends up with exactly one mesh that has a material;
  - the deferred geometry's first mesh may have no material, but a later mesh for the same geometry must have one;
  - no geometry is rebuilt every frame (bounded mesh count);
  - with the budget at the default (4) the same run also ends fully textured, so the knob itself is not what fixes it.

The gate is written for the existing capture path; the implementation it demands is a late-material rebuild, i.e. the
deferred texture must invalidate the geometries that were built without it. `NIER_REMIX_LIVE_TEX_PER_FRAME` must exist:
0 means "capture no textures this frame", n means n.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

C = Path(__file__).resolve().parent
A = C.parent
OUT = A / 'runtime/live-late-material'
import test_remix_live as tr
import test_menu_overlay as tmo
import test_nscn_scene as ts

tr.ENV_KEYS = tuple(tr.ENV_KEYS) + ('NIER_REMIX_LIVE', 'NIER_REMIX_LIVE_TEX', 'NIER_REMIX_LIVE_TEX_PER_FRAME',
                                     'FAKE_REMIX_INSTANCE_LOG')


def meshes_by_hash(fake):
    """World geometries only: the background shell (|x| in the tens of thousands) is not part of these assertions."""
    out = {}
    for line in fake.splitlines():
        if not line.startswith('CreateMesh'):
            continue
        kv = dict(re.findall(r'(\w+)=(\S+)', line))
        if abs(float(kv.get('v0', '0').split(',')[0])) > 5000:
            continue
        out.setdefault(kv['hash'], []).append({'materials': int(kv['materials']),
                                               'presented': int(kv['presented'])})
    return out


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
        tex = work / 'live-textures'
        tex.mkdir()
        base = {'NIER_REMIX_RUNTIME': tr.win(work / 'fake_remix.dll'), 'NIER_REMIX_SCENE': tr.win(scene / 'scene.bin'),
                'MOCK_FRAME_MS': '40', 'NIER_REMIX': '1', 'NIER_REMIX_LIVE': '1',
                'NIER_REMIX_LIVE_TEX': tr.win(tex), 'MOCK_CAMERA': 'live-late'}

        # One texture per frame: the second texture is deferred, so its geometry is first built without a material.
        _, r, log, fake = tr.run(work, 'late', {**base, 'NIER_REMIX_LIVE_TEX_PER_FRAME': '1'})
        assert fake and 'VIOLATION' not in fake, fake
        built = meshes_by_hash(fake)
        assert len(built) == 2, f'expected the two live geometries, got {len(built)}: {list(built)}'
        for ghash, made in built.items():
            assert any(m['materials'] >= 1 for m in made), \
                f'geometry {ghash} never got a material; builds={made}'
            assert len(made) <= 3, f'geometry {ghash} rebuilt too often: {made}'
        # Whether a geometry is built before its first texture lands depends on the worker's timing, so the rule is
        # asserted as an invariant rather than as a required event: every bare build must be repaired later.
        bare = {g: made for g, made in built.items() if any(m['materials'] == 0 for m in made)}
        for g, made in bare.items():
            first_bare = next(m['presented'] for m in made if m['materials'] == 0)
            repaired = [m for m in made if m['materials'] >= 1 and m['presented'] > first_bare]
            assert repaired, f'geometry {g} was built without a material and never repaired: {made}'
        results['late'] = ('Every geometry ends with a material; %d were first built bare and all were repaired.'
                           % len(bare))

        # The mechanism behind that: with the budget at zero nothing is captured, so the same run must leave every
        # geometry bare. Without this the invariants above could hold for reasons unrelated to the knob.
        tex0 = work / 'live-textures-starved'
        tex0.mkdir()
        _, r, log, fake = tr.run(work, 'starved', {**base, 'NIER_REMIX_LIVE_TEX': tr.win(tex0),
                                                  'NIER_REMIX_LIVE_TEX_PER_FRAME': '0'})
        assert fake and 'VIOLATION' not in fake, fake
        starved = meshes_by_hash(fake)
        assert starved, 'the scene must still draw with no textures'
        assert all(m['materials'] == 0 for made in starved.values() for m in made), \
            f'textures were captured despite a budget of zero: {starved}'
        results['starved'] = 'A zero capture budget leaves every geometry untextured, so the knob is the reason.'

        # Default budget (4 textures per frame): the same run must also end fully textured, so nothing above depends on
        # the knob forcing a deferral.
        tex2 = work / 'live-textures-default'
        tex2.mkdir()
        _, r, log, fake = tr.run(work, 'default', {**base, 'NIER_REMIX_LIVE_TEX': tr.win(tex2)})
        assert fake and 'VIOLATION' not in fake, fake
        for ghash, made in meshes_by_hash(fake).items():
            assert any(m['materials'] >= 1 for m in made), f'geometry {ghash} untextured at the default budget: {made}'
        results['default'] = 'At the default capture budget every geometry is textured.'
    except Exception as exc:
        (OUT / 'validation.json').write_text(json.dumps({'passed': False, 'error': str(exc)[-3000:], 'results': results,
                                                         'work': str(work)}, indent=2) + '\n')
        raise
    finally:
        subprocess.run(['wineserver', '-k'], env=os.environ, capture_output=True)
    report = {'passed': True, 'results': results,
              'dll_sha256': hashlib.sha256((tmo.DLL / 'd3d11.dll').read_bytes()).hexdigest(),
              'limits': 'Software-only Wine mock, fake Remix. It pins the late-material rule, not which real NieR '
                        'surfaces are white nor why.'}
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
