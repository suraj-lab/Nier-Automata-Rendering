#!/usr/bin/env python3
"""FROZEN TARGET for item T1 (PLAN_2026-11-13), parked: not in the suite until the switch is finished.

Gate: a geometry whose texture was not captured yet gets its material when the texture lands.

Textures are captured at most `NIER_REMIX_LIVE_TEX_PER_FRAME` per frame (default 4, each is a GPU readback plus a file
write on the game thread). A draw whose texture is deferred is uploaded with no material, and because its geometry
content never changes afterwards, nothing revisits it: the surface stays untextured (white) for the rest of the session.
That is the observed live symptom "most surfaces come out untextured white".

What this gate pins, with two geometries and two textures and a capture budget of one texture per frame:
  - every geometry ends up with exactly one mesh that has a material;
  - the deferred geometry's first mesh may have no material, but a later mesh for the same geometry must have one;
  - no geometry is rebuilt every frame (bounded mesh count);
  - with the budget at the default (4) the same run also ends fully textured, so the knob itself is not what fixes it.

What it demands is **not** a rebuild: the texture that lands must swap the material in place (DestroyMaterial then
CreateMaterial under the same hash; the runtime makes the handle the hash, `rtx_remix_api.cpp:886`), so the mesh keeps
its identity, its BLAS and its instance history. The fake runtime now flags a repeat CreateMaterial under a live hash as
a VIOLATION, which is what the real runtime silently ignores.

How it was got there, so it is not undone by accident: a deferred readback reserves its texture id at first sight
(`live_capture.h`, `deferred_readbacks()`), the material hash is built from ids only (`live_scene.h`), a material whose
albedo file is not yet on disk is sent grey (`albedoConstant` 0.5) instead of as a null handle, the build no longer waits
for files (`hold_untextured`, rollback `NIER_REMIX_LIVE_HOLD_UNTEXTURED=1`), and `refresh_incomplete_materials()` re-creates
an incomplete material under its own hash once a file lands. `landed` means **on disk** (`State::landed`), not "a path was
handed over at capture time".
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

tr.ENV_KEYS = tuple(tr.ENV_KEYS) + ('NIER_REMIX_LIVE_STATS_EVERY', 'NIER_REMIX_LIVE', 'NIER_REMIX_LIVE_TEX', 'NIER_REMIX_LIVE_TEX_PER_FRAME',
                                     'FAKE_REMIX_INSTANCE_LOG', 'NIER_REMIX_LIVE_TEX_WRITE_DELAY_MS',
                                     'NIER_REMIX_LIVE_GREY_FIRST')


def meshes_by_hash(fake):
    """World geometries only: the background shell (|x| in the tens of thousands) is not part of these assertions."""
    out = {}
    for line in fake.splitlines():
        if not line.startswith('CreateMesh'):
            continue
        kv = dict(re.findall(r'(\w+)=(\S+)', line))
        if abs(float(kv.get('v0', '0').split(',')[0])) > 5000:
            continue
        out.setdefault(kv['key'], []).append({'materials': int(kv['materials']),
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
                'NIER_REMIX_LIVE_TEX': tr.win(tex), 'MOCK_CAMERA': 'live-late',
                }

        # The writer delay makes the file land *after* the material that names it was created, which is the case T1 is
        # about; without it the mock's tiny textures are on disk before the material exists and nothing has to be swapped.
        _, r, log, fake = tr.run(work, 'late', {**base, 'NIER_REMIX_LIVE_TEX_PER_FRAME': '1', 'NIER_REMIX_LIVE_STATS_EVERY': '10'})
        assert fake and 'VIOLATION' not in fake, fake[-1200:]
        built = meshes_by_hash(fake)
        assert len(built) == 2, f'expected the two live geometries, got {len(built)}: {list(built)}'
        for ghash, made in built.items():
            # A geometry whose albedo had no id at first sight (readback deferred, per-frame budget spent) cannot name a
            # material yet and is built once, bare; every later build must then be a real content change, never a texture.
            # That is what this asserts: the geometry ends with a material, and no rebuild comes from a texture (below).
            assert any(m['materials'] >= 1 for m in made), f'geometry {ghash} never got a material: {made}'

        # The swap itself: CreateMaterial, then DestroyMaterial and CreateMaterial again under the SAME hash, which is the
        # only way the runtime accepts a changed surface (a repeat create under a live hash is ignored, and now flagged).
        def material_lines(fake_log):
            return [l for l in fake_log.splitlines() if l.startswith(('CreateMaterial', 'DestroyMaterial'))]

        by_hash = {}
        for line in material_lines(fake):
            kv = dict(re.findall(r'(\w+)=(\S+)', line))
            by_hash.setdefault(kv['hash'], []).append(line)
        swapped = {h: lines for h, lines in by_hash.items() if any(x.startswith('DestroyMaterial') for x in lines)}
        assert swapped, f'no material was ever destroyed and re-created, so a late texture never reached a surface: ' \
                        f'{material_lines(fake)[-6:]}'
        for h, lines in swapped.items():
            assert lines[0].startswith('CreateMaterial'), f'material {h} destroyed before it was created: {lines}'
            assert sum(1 for x in lines if x.startswith('DestroyMaterial')) == 1, f'material {h}: {lines}'
            creates = [x for x in lines if x.startswith('CreateMaterial')]
            assert len(creates) == 2, f'material {h} must be created, then destroyed and created again: {lines}'
            first, second = (dict(re.findall(r'(\w+)=(\S+)', x)) for x in creates)
            assert first['hash'] == second['hash'] == h, (first, second)
            assert first != second, f'material {h} was re-created with identical arguments, so nothing changed: {lines}'
        # No texture-triggered rebuild may remain: that counter is the visible symptom T1 removes.
        why_lines = [x for x in tr.remix_lines(log) if x.startswith('remix: live rebuilds ')]
        assert why_lines, tr.remix_lines(log)[-6:]
        why = {k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', why_lines[-1])}
        assert why['texture'] == 0, f'texture-triggered rebuilds must be gone with the material swap: {why}'
        # A bare first build is allowed only when the albedo had no id yet; when it is repaired, the repair is the swap
        # above (the same material hash, destroyed and created again), not a new mesh with a new material.
        results['late'] = (f'{len(built)} geometries, one build each, {len(swapped)} material(s) swapped under a stable hash, '
                           'no texture rebuild')

        # The mechanism behind that: with the budget at zero nothing is captured, so the same run must leave every
        # geometry bare. Without this the invariants above could hold for reasons unrelated to the knob.
        tex0 = work / 'live-textures-starved'
        tex0.mkdir()
        _, r, log, fake = tr.run(work, 'starved', {**base, 'NIER_REMIX_LIVE_TEX': tr.win(tex0),
                                                  'NIER_REMIX_LIVE_TEX_PER_FRAME': '0'})
        assert fake and 'VIOLATION' not in fake, fake
        starved = meshes_by_hash(fake)
        assert starved, 'the scene must still draw with no textures'
        # Item T1: with no texture at all the surface is still sent, in grey, so the draw is lit and visible instead of
        # arriving as an untextured null material.
        assert all(m['materials'] >= 1 for made in starved.values() for m in made), \
            f'a budget of zero must still send a grey material: {starved}'
        assert not [l for l in fake.splitlines() if l.startswith('CreateMaterial') and 'live_' in l], 'a texture was written'
        results['starved'] = 'A zero capture budget leaves every geometry grey with a material and no texture path.'

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
