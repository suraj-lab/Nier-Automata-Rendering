#!/usr/bin/env python3
"""Gate: analyze_live_run.py reads what the DLL actually prints, and only the last run in the (appended) log.

The log lines are not hand-written: they are produced from the printf format strings in remix_live.cpp, so a format
change the analyzer does not follow fails here instead of silently blanking a verdict in the live test.
Native Python only; no Wine.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
SRC = (C / 'remix_live.cpp').read_text()


def fmt(prefix):
    """The C format string (adjacent literals joined) of the first log call whose text starts with `prefix`."""
    start = SRC.index('"' + prefix)
    parts, i = [], start
    while True:
        m = re.compile(r'\s*"((?:[^"\\]|\\.)*)"').match(SRC, i)
        if not m:
            break
        parts.append(m.group(1))
        i = m.end()
    return ''.join(parts)


def render(prefix, values):
    """printf the format with `values` (a dict per %-conversion, in order) using Python's % operator."""
    f = fmt(prefix)
    convs = re.findall(r'%[-.\d]*(?:ll|l|z)?[udfsx]', f)
    assert len(convs) == len(values), f'{prefix}: format has {len(convs)} conversions, test gives {len(values)}: {f}'
    py = re.sub(r'%([-.\d]*)(?:ll|l|z)?([udfsx])', lambda m: '%' + m.group(1) + ('d' if m.group(2) == 'u' else m.group(2)), f)
    return py % tuple(values)  # the formats already start with 'remix: '


def stats(draws, blended, untextured, textures, hud, scene, skipped, built, dropped, mesh_bytes, lights, creates, sky):
    # Order of the conversions in the "live draws=" format: draws instances meshes built evicted identical blended
    # untextured textures hud small_viewport scene(w,h) skipped_pass fallbacks mesh_bytes dropped lights light_creates sky
    # prepass
    w, h = scene
    return render('remix: live draws=',
                  [draws, draws + 100, 900, built, 0, 5, blended, untextured, textures, hud, 3, w, h, skipped, 0,
                   mesh_bytes, dropped, lights, creates, sky, 700 if skipped else 0, 120 if skipped else 0,
                   0xff if lights else 0])


def analyze(text):
    with tempfile.NamedTemporaryFile('w', suffix='.log', delete=False) as f:
        f.write(text)
    out = subprocess.run([sys.executable, str(C / 'analyze_live_run.py'), f.name], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout


def verdict(out, item):
    m = re.search(rf'^{re.escape(item)}\s+(\w+)', out, re.M)
    return m.group(1) if m else None


def main():
    enabled = render('remix: enabled', ['C:\\remix.dll', 'C:\\scene.bin'])
    first = render('remix: live scene first frame', [1400, 10, 1400, 8, 0])
    fps = render('remix: %.1f fps', [12.0, 300, 1.0, 1.0, 1.0, 0.0, 70.0, 2.0, 0.0, 9.0])
    replay = 'remix: hud replay draws=56 verts=336 srvs=56 ok=1 failed=0'
    assert fmt('remix: hud replay draws=').startswith('remix: hud replay draws=%u verts=%u srvs=%u ok=%d failed=%d')

    # An old run (pre-filter, with a watchdog stall) followed by a good one: only the good one may be judged.
    old = '\n'.join([enabled, first, stats(2391, 0, 50, 10, 0, (0, 0), 0, 2323, 0, 10 ** 8, 0, 0, 0),
                     'remix: watchdog worker in \'dxvk_CreateD3D9\' for 5587 ms'])
    good = [enabled, first, replay, fps]
    for i in range(20):
        good.append(stats(1400, 300, 40, 150, 56, (2580, 1080), 1500, 2000 + i, 0, 300 * 10 ** 6, 12, 14, 1))
    # The last sample landed on a menu: nothing to filter that frame. 1.1 must still judge the run, not the sample.
    good.append(stats(30, 0, 0, 150, 56, (2580, 1080), 0, 2020, 0, 300 * 10 ** 6, 0, 14, 0))
    out = analyze(old + '\n' + '\n'.join(good) + '\n')
    assert 'last of 2 runs' in out, out
    expected = {'1.1': 'PASS', '1.2': 'LOOK', '1.3': 'PASS', '1.4': 'PASS', '1.5': 'LOOK', '1.8': 'LOOK', '1.9': 'LOOK',
                '1.10': 'PASS'}
    for item, want in expected.items():
        assert verdict(out, item) == want, f'{item}: want {want}, got {verdict(out, item)}\n{out}'
    assert 'readback is 83% of the frame' in out, f'cost split not parsed from "present N, ..." form:\n{out}'

    # The same good run, broken one way per row: each verdict must flip.
    bad = [enabled, first, 'remix: hud replay draws=56 verts=336 srvs=56 ok=0 failed=1', fps,
           render('remix: live scene target filter latched off', [])]
    for i in range(8):
        bad.append(stats(2900, 0, 1200, 0, 0, (2580, 1080), 0, 2000 + 400 * i, 3, (i + 1) * 300 * 10 ** 6, 0, 0, 0))
    bad.append('remix: watchdog worker in \'submit\' for 3000 ms')
    out = analyze('\n'.join(bad) + '\n')
    for item in ('1.1', '1.2', '1.3', '1.4', '1.5', '1.8', '1.9', '1.10'):
        assert verdict(out, item) == 'FAIL', f'{item}: want FAIL, got {verdict(out, item)}\n{out}'
    assert 'builds never settle' in out, out

    # A short clean run cannot pass 1.10.
    out = analyze('\n'.join(good[:8]) + '\n')
    assert verdict(out, '1.10') == 'SHORT', out
    print('test_analyze_live_run: all passed')


if __name__ == '__main__':
    main()
