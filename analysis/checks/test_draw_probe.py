#!/usr/bin/env python3
"""CPU-only draw probe: real proxy + mock, no Remix/camera/geometry readbacks, even with NIER_REMIX=1."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import test_menu_overlay as tmo
import test_remix_live as tr

OUT = tmo.A / 'runtime/draw-probe'
KEYS = (*tr.ENV_KEYS, 'NIER_DRAW_PROBE')


def inside():
    work = Path(tempfile.mkdtemp(prefix='run-', dir=OUT))
    results = {}
    saved = {key: os.environ.get(key) for key in KEYS}
    try:
        tmo.build(work)
        for name, mode, probe in [('off', '1', False), ('indexed', '1', True), ('instanced', 'instanced', True), ('capture-keys', None, True)]:
            for key in KEYS:
                os.environ.pop(key, None)
            os.environ.update(MOCK_FRAME_MS='80', NIER_REMIX='1' if probe else '0')
            if mode:
                os.environ['MOCK_CAMERA'] = mode
            if probe:
                os.environ['NIER_DRAW_PROBE'] = '1'
            directory, result, log = tmo.scenario(work, name, b'[Rendering]\r\nPreset=Native\r\n', True, (0, 0))
            assert result.get('camera_reads', '0') == '0' and result.get('geometry_reads', '0') == '0', result
            assert not list((directory / 'NIER_CAPTURE').glob('frame_*')), 'Probe must not allow F9 GPU readbacks'
            assert result['presented'] == '80' and result['cs_lost'] == '0', result
            assert 'remix:' not in log, 'Probe must override NIER_REMIX, not initialize a renderer or read back buffers'
            reports = [dict(re.findall(r'(\w+)=([^ ]+)', line)) for line in log.splitlines() if 'draw-probe:' in line]
            if not probe:
                assert not reports, log
            elif mode is None:
                assert reports and 'menu: frame captured' not in log, log
            else:
                assert 1 <= len(reports) <= 4, reports  # initial + once per five seconds, not per-draw logging
                samples = [r for r in reports if r.get('sample') == '1']
                assert samples, 'missing CPU-only diagnostic sample'
                r = samples[0]
                assert int(r['instanced' if mode == 'instanced' else 'indexed']) > 0, r
                assert r['hook_mask'] == '3' and r['layout_hook'] == '1', r
                assert r['layout'] == '1' and r['cb0'] == '256' and r['cb11'] == '0', r
                # Camera-only fixture leaves topology undefined; the probe must report it, not infer triangle lists.
                assert r['topology'] == '0' and r['vb_mask'] == '1' and r['ib_format'] == '57', r
                assert r['viewport'] == '1920x1080' and r['backbuffer'] == '1920x1080', r
                assert r['sample_identity'] == r['armed_identity'], r
            results[name] = 'passed'
    except Exception as exc:
        report = {'passed': False, 'error': str(exc)[-2500:], 'results': results, 'work': str(work)}
    else:
        report = {'passed': True, 'results': results, 'work': str(work),
                  'limits': 'Wine mock only; no claim that native game draw hooks are reached.'}
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        subprocess.run(['wineserver', '-k'], env=os.environ, capture_output=True)
    (OUT / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


def main():
    if sys.argv[1:] == ['--inside']:
        return inside()
    for name in ('prefix', 'home', 'cache', 'xdg'):
        (OUT / name).mkdir(parents=True, exist_ok=True)
    (OUT / 'xdg').chmod(0o700)
    assert not (OUT / 'prefix').is_symlink()
    env = os.environ.copy()
    for key in KEYS:
        env.pop(key, None)
    env.update(WINEPREFIX=str(OUT / 'prefix'), HOME=str(OUT / 'home'), XDG_CACHE_HOME=str(OUT / 'cache'),
               XDG_RUNTIME_DIR=str(OUT / 'xdg'), WINEDEBUG='-all', WAYLAND_DISPLAY='', LIBGL_ALWAYS_SOFTWARE='1',
               GALLIUM_DRIVER='llvmpipe', WINEDLLOVERRIDES='d3d11=n,b;winemenubuilder.exe=d;mscoree,mshtml=')
    return subprocess.run(['xvfb-run', '-a', '-s', '-screen 0 1920x1080x24', sys.executable,
                           str(Path(__file__).resolve()), '--inside'], cwd=OUT, env=env).returncode


if __name__ == '__main__':
    sys.exit(main())
