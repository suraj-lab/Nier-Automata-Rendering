#!/usr/bin/env python3
"""Gate: native game HUD shader draws onto the Remix image before the game's HDR final compositor.

Uses the captured shipped HUD PS when available (runtime-only artifact, not redistributed).
Pins two sprites coexisting, untouched corner=Remix, and NO_HUD disabling the handoff.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
A = C.parent
OUT = A / 'runtime/native-hud'
import test_live_hud_capture as old
tr, tmo, ts = old.tr, old.tmo, old.ts
tr.ENV_KEYS = tuple(tr.ENV_KEYS) + ('MOCK_NATIVE_HUD_PS', 'NIER_REMIX_CAPTURE_NATIVE_ONLY')


def inside():
    fixture = A / 'runtime/hud-evidence/ps_1888250464.dxbc'
    if not fixture.exists():
        print(json.dumps({'passed': True, 'skipped': 'shipped HUD shader fixture unavailable'}))
        return
    work = Path(tempfile.mkdtemp(prefix='run-', dir=OUT))
    try:
        tmo.build(work)
        subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-shared',
            '-static', '-static-libgcc', '-static-libstdc++', '-isystem', str(A / 'remix-probe/vendor'),
            str(C / 'remix_live_fake_runtime.cpp'), '-ld3d9', '-o', str(work / 'fake_remix.dll')], check=True)
        scene = work / 'scene'
        (scene / 'scene_textures').mkdir(parents=True)
        (scene / 'scene.bin').write_bytes(ts.scene_bytes(ts.CAMERA, ts.DRAWS, ts.TEXTURES, ts.TRIS))
        base = {'NIER_REMIX_RUNTIME': tr.win(work / 'fake_remix.dll'), 'NIER_REMIX_SCENE': tr.win(scene / 'scene.bin'),
            'MOCK_FRAME_MS': '40', 'MOCK_CAMERA': 'live-native-hud', 'NIER_REMIX': '1', 'NIER_REMIX_LIVE': '1',
            'MOCK_NATIVE_HUD_PS': tr.win(fixture)}
        tex = work / 'textures'; tex.mkdir()
        composite = work / 'native.raw'
        _, r, log, fake = tr.run(work, 'native', {**base, 'NIER_REMIX_LIVE_TEX': tr.win(tex),
            'NIER_REMIX_CAPTURE_COMPOSITE': tr.win(composite), 'NIER_REMIX_CAPTURE_NATIVE_ONLY': '1'})
        assert fake and 'VIOLATION' not in fake, (fake or log)[-1500:]
        assert 'native HUD handoff' in log, 'no evidence the original sprite renderer was used'
        assert composite.exists(), 'native HUD composite was not captured'
        raw = composite.read_bytes()
        def px(x, y):
            i = (y * 1920 + x) * 4
            return tuple(raw[i:i+3])
        for point in [(960, 540), (96, 540)]:
            c = px(*point)
            assert c[1] > 200 and c[0] < 60 and c[2] < 60, f'native sprite missing/erased at {point}: {c}'
        assert max(abs(a-b) for a,b in zip(px(1900, 8),tr.REMIX)) < 24, f'original world leaked through: {px(1900,8)}'
        assert r.get('hud_state_lost') == '0' and r.get('cs_lost') == '0', r
        tex2 = work / 'textures-off'; tex2.mkdir()
        _, _, log2, _ = tr.run(work, 'nohud', {**base, 'NIER_REMIX_LIVE_TEX': tr.win(tex2), 'NIER_REMIX_LIVE_NO_HUD': '1'})
        assert 'native HUD handoff' not in log2, 'NO_HUD did not disable native handoff'
        report = {'passed': True, 'work': str(work), 'composite': str(composite),
            'fixture_sha256': hashlib.sha256(fixture.read_bytes()).hexdigest(),
            'limits': 'Shipped HUD pixel shader + synthetic VS/texture in software Wine, fake Remix; not real gameplay.'}
        (OUT / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report))
    except Exception as exc:
        (OUT / 'validation.json').write_text(json.dumps({'passed': False, 'work': str(work), 'error': str(exc)[-1800:]}) + '\n')
        raise
    finally:
        subprocess.run(['wineserver', '-k'], env=os.environ, capture_output=True)


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
