#!/usr/bin/env python3
"""Frozen gate: alpha-blended draws reach Remix as cutout geometry.

NieR draws foliage, hair and grilles with classic straight-alpha blending. Remix has no per-draw blend state, so the
live path reads the game's blend state and marks those instances `REMIXAPI_INSTANCE_CATEGORY_BIT_ALPHA_BLEND_TO_CUTOUT`.
Without it, every foliage card renders as a solid quad (measured in the live game: solid foliage, opaque sky shells).

What this gate pins:
  - a plain draw carries no category flags;
  - a straight-alpha-blended draw carries exactly the cutout bit;
  - additive blending (src = ONE, particles) does NOT become a cutout: that is the mutation the naive
    "blend enabled means cutout" implementation gets wrong (asserted with a real additive blend state);
  - with `NIER_REMIX_LIVE` off the flag never appears (nothing is submitted at all).

Software mocks only: it pins the rule, not NieR's real blend usage.
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
OUT = A / 'runtime/live-alpha'
import test_remix_live as tr
import test_menu_overlay as tmo
import test_nscn_scene as ts

CUTOUT = 1 << 15  # REMIXAPI_INSTANCE_CATEGORY_BIT_ALPHA_BLEND_TO_CUTOUT
SKY = 1 << 2      # REMIXAPI_INSTANCE_CATEGORY_BIT_SKY: the sky dome carries it, this gate ignores it

tr.ENV_KEYS = tuple(tr.ENV_KEYS) + ('NIER_REMIX_LIVE', 'NIER_REMIX_LIVE_TEX', 'FAKE_REMIX_INSTANCE_LOG')


def flags_by_frame(fake):
    frames = {}
    for line in fake.splitlines():
        if not line.startswith('DrawInstance'):
            continue
        presented = int(re.search(r'presented=(\d+)', line).group(1))
        flags = int(re.search(r'flags=(\d+)', line).group(1)) & ~SKY  # SKY is a separate question
        frames.setdefault(presented, []).append(flags)
    return frames


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
                'NIER_REMIX_LIVE_TEX': tr.win(tex), 'FAKE_REMIX_INSTANCE_LOG': '1'}

        # Opaque geometry: no category flags at all.
        _, r, log, fake = tr.run(work, 'opaque', {**base, 'MOCK_CAMERA': 'live'})
        assert fake and 'VIOLATION' not in fake, fake
        plain = flags_by_frame(fake)
        opaque_fake = fake
        assert plain, 'the live scene must draw instances'
        assert all(f == 0 for values in plain.values() for f in values), \
            f'opaque draws must carry no category flags: {sorted({f for v in plain.values() for f in v})}'
        results['opaque'] = 'Opaque draws carry no category flags.'

        # Straight alpha: exactly the cutout bit, every instance, every frame.
        _, r, log, fake = tr.run(work, 'blend', {**base, 'MOCK_CAMERA': 'live-blend'})
        assert fake and 'VIOLATION' not in fake, fake
        blended = flags_by_frame(fake)
        assert blended, 'the live scene must draw instances'
        for frame, values in blended.items():
            for flags in values:
                assert flags == CUTOUT, f'frame {frame}: blended draw must be cutout, flags={flags}'
        results['blend'] = 'Straight-alpha-blended draws are submitted as cutout (ALPHA_BLEND_TO_CUTOUT).'

        # Mutation: blending is on, but additive. A "blend enabled means cutout" implementation marks particles as
        # cutout cards and gets holes in every explosion; this asserts it does not.
        _, r, log, fake = tr.run(work, 'additive', {**base, 'MOCK_CAMERA': 'live-additive'})
        assert fake and 'VIOLATION' not in fake, fake
        additive = flags_by_frame(fake)
        assert additive, 'the live scene must draw instances'
        assert all(f == 0 for values in additive.values() for f in values), \
            f'additive blending must not become cutout: {sorted({f for v in additive.values() for f in v})}'
        results['additive'] = 'Additive blending (particles) is not marked as cutout.'

        # Alpha TEST, not blend: NieR's foliage, grass cards and decals discard in the pixel shader with blending off
        # (real capture: 123 of 553 scene draws). Their meshes must get an alpha-test material carrying the shader's own
        # comparison: "if (a < 0.5) discard" keeps a >= 0.5, i.e. kGreaterOrEqual (6) at 128. The opaque run above
        # is the control: no material may carry an alpha test there.
        def materials(text):
            return [(int(m.group(1)), int(m.group(2))) for x in text.splitlines() if x.startswith('CreateMaterial')
                    for m in [re.search(r'alpha=(-?\d+)/(\d+)', x)] if m]
        opaque_materials = materials(opaque_fake)
        assert opaque_materials and all(op != 6 for op, _ in opaque_materials), f'opaque run alpha-tested: {opaque_materials}'
        tex_c = work / 'live-textures-cutout'
        tex_c.mkdir()
        _, r, log, fake = tr.run(work, 'cutout', {**base, 'MOCK_CAMERA': 'live', 'MOCK_CUTOUT_PS': '1',
                                                  'NIER_REMIX_LIVE_TEX': tr.win(tex_c)})
        assert fake and 'VIOLATION' not in fake, fake
        assert (6, 128) in materials(fake), f'no alpha-test material from the discarding shader: {materials(fake)}'
        counts = [int(m.group(1)) for x in tr.remix_lines(log) for m in [re.search(r' alpha_tested=(\d+)', x)] if m]
        assert counts and max(counts) > 0, f'alpha_tested= must report the discarding draws: {counts}'
        results['alpha_test'] = 'A discarding pixel shader gives its mesh an alpha-test material with the shader\'s own threshold.'

        # Red test: without the live path there is nothing to mark, so the flag cannot appear by accident.
        _, r, log, fake = tr.run(work, 'off', {'MOCK_CAMERA': 'live-blend'})
        assert not fake or CUTOUT not in fake, 'Remix off must submit nothing at all'
        results['off'] = 'Remix off: no instance is submitted, so the flag cannot leak.'
    except Exception as exc:
        (OUT / 'validation.json').write_text(json.dumps({'passed': False, 'error': str(exc)[-3000:], 'results': results,
                                                         'work': str(work)}, indent=2) + '\n')
        raise
    finally:
        subprocess.run(['wineserver', '-k'], env=os.environ, capture_output=True)
    report = {'passed': True, 'results': results,
              'dll_sha256': hashlib.sha256((tmo.DLL / 'd3d11.dll').read_bytes()).hexdigest(),
              'limits': 'Software-only Wine mock, fake Remix. Whether NieR draws foliage with straight alpha is '
                        'unverified until one live run logs `blended=`.'}
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
