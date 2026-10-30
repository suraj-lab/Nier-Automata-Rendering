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
KEYS = (*tr.ENV_KEYS, 'NIER_DRAW_PROBE', 'NIER_DRAW_PROBE_REHOOK')


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
                assert result['ctx_canary_in_proxy'] == '0', result  # the probe must not hook anything when off
            elif mode is None:
                assert reports and 'menu: frame captured' not in log, log
            else:
                assert 1 <= len(reports) <= 4, reports  # initial + once per five seconds, not per-draw logging
                samples = [r for r in reports if r.get('sample') == '1']
                assert samples, 'missing CPU-only diagnostic sample'
                r = samples[0]
                assert int(r['instanced' if mode == 'instanced' else 'indexed']) > 0, r
                assert r['hook_mask'] == '3' and r['layout_hook'] == '1', r
                assert r['canary'] == '1', r  # a non-draw slot we own stays ours: the table itself is untouched
                assert result['ctx_canary_in_proxy'] == '1', result
                assert r['layout'] == '1' and r['cb0'] == '256' and r['cb11'] == '0', r
                # Camera-only fixture leaves topology undefined; the probe must report it, not infer triangle lists.
                assert r['topology'] == '0' and r['vb_mask'] == '1' and r['ib_format'] == '57', r
                assert r['viewport'] == '1920x1080' and r['backbuffer'] == '1920x1080', r
                assert r['sample_identity'] == r['armed_identity'], r
            results[name] = 'passed'
        # Another layer takes the two draw slots mid-run. This is the laptop failure (same context object, same table,
        # hooks gone after the resolution switch): the probe must report the loss with the slot values, not a healthy
        # table, and must show that the object and table were the ones we hooked.
        for key in KEYS:
            os.environ.pop(key, None)
        os.environ.update(MOCK_FRAME_MS='80', NIER_REMIX='1', MOCK_CAMERA='1', NIER_DRAW_PROBE='1', MOCK_STEAL_DRAW='10')
        directory, result, log = tmo.scenario(work, 'stolen', b'[Rendering]\r\nPreset=Native\r\n', True, (0, 0))
        assert result['presented'] == '80' and result['cs_lost'] == '0', result
        assert 'remix:' not in log, 'Probe must override NIER_REMIX, not initialize a renderer'
        reports = [dict(re.findall(r'(\w+)=([^ ]+)', line)) for line in log.splitlines() if 'draw-probe:' in line]
        assert reports, log
        first, last = reports[0], reports[-1]
        assert first['hook_mask'] == '3', first  # hooks were installed before the takeover
        assert last['hook_mask'] == '0', last
        assert last['restored12'] == '0' and last['restored20'] == '0', last
        assert last['foreign12'] == '1' and last['foreign20'] == '1', last
        assert last['ctx_installed'] == last['armed_context'], last  # same object: a lost hook, not a new context
        assert last['table_installed'] == last['armed_table'], last  # same table: someone overwrote our slots
        assert last['install_ok'] == '1' and last['install_skipped'] == '0', last
        assert int(last['slot12'], 16) and int(last['orig12'], 16), last
        assert last['slot12'] != last['orig12'] and last['slot12'] != first['slot12'], last
        assert last['rehook12'] == '-' and last['rehook_mask'] == '0', last  # re-hooking is opt-in
        results['stolen'] = 'passed'
        # With re-hooking armed, a slot owned by a third party must stay untouched: chaining to a function we did not
        # replace is how overlay Present-recursion loops start. The probe reports the refusal and changes nothing.
        for key in KEYS:
            os.environ.pop(key, None)
        os.environ.update(MOCK_FRAME_MS='80', NIER_REMIX='1', MOCK_CAMERA='1', NIER_DRAW_PROBE='1',
                          NIER_DRAW_PROBE_REHOOK='1', MOCK_STEAL_DRAW='10')
        directory, result, log = tmo.scenario(work, 'steal-rehook', b'[Rendering]\r\nPreset=Native\r\n', True, (0, 0))
        assert result['presented'] == '80' and result['cs_lost'] == '0', result
        reports = [dict(re.findall(r'(\w+)=([^ ]+)', line)) for line in log.splitlines() if 'draw-probe:' in line]
        after = [r for r in reports if r.get('hook_mask') == '0']
        assert after, reports
        for r in after:
            assert r['rehook12'] == 'foreign' and r['rehook20'] == 'foreign', r
            assert r['rehook_mask'] == '0', r
        assert len({r['slot12'] for r in after}) == 1, 'the probe modified a foreign slot'
        # The mock takes only the two draw slots: the canary must survive, which is what tells a slot-specific
        # owner apart from something re-applying a saved snapshot of the whole vtable.
        assert {r['canary'] for r in after} == {'1'}, after[0]
        # Repair points (OMSetRenderTargets, Map) run before every draw and must still refuse a foreign pointer.
        assert all(r.get('repairs') == '0' for r in after), after[0]
        results['steal-rehook'] = 'passed'
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
