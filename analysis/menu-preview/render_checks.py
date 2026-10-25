#!/usr/bin/env python3
"""Capture the standalone D3D11 preview under a task-owned Wine prefix/Xvfb."""
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'analysis/runtime/menu-preview'
EXE = OUT / 'build/nier_menu_preview.exe'
CASES = ['custom75', 'native', 'dirty', 'saved', 'save-fail', 'startup-fail', 'closed',
         'missing-file', 'invalid-file', 'unreadable-file', 'recovery']


def pixel(data, x, y):
    offset = struct.unpack_from('<I', data, 10)[0]
    width, height = struct.unpack_from('<ii', data, 18)
    assert struct.unpack_from('<H', data, 28)[0] == 32
    assert 0 <= x < width and 0 <= y < abs(height)
    row = y if height < 0 else height - y - 1
    b, g, r = data[offset+(row*width+x)*4:offset+(row*width+x)*4+3]
    return r, g, b


def inside():
    assert EXE.is_file(), 'Run build.py first'
    captures = Path(tempfile.mkdtemp(prefix='captures-', dir=OUT))
    results = []
    env = os.environ.copy()
    prefix = Path(env.get('WINEPREFIX', '')).resolve()
    assert prefix == (OUT/'prefix').resolve() and prefix.is_relative_to(OUT.resolve())
    assert not (OUT/'prefix').is_symlink(), 'Never stop a Wine server reached through a prefix symlink'
    smoke = env.get('NIER_PREVIEW_SMOKE') == '1'
    try:
        for width, height in ([(1920, 1080)] if smoke else [(1920, 1080), (3440, 1440)]):
            for scale in ([1] if smoke else [1, 1.5, 2]):
                for case in (CASES[:1] if smoke else CASES):
                    name = f'{case}-{width}x{height}-{scale}x'
                    folder = captures / name; folder.mkdir()
                    cmd = ['wine', str(EXE), '--capture', f'--scale={scale}',
                           f'--viewport={width}x{height}', f'--case={case}']
                    try:
                        p = subprocess.run(cmd, cwd=folder, env=env, capture_output=True, text=True, timeout=120)
                    except subprocess.TimeoutExpired as error:
                        def decoded(value):
                            return value.decode(errors='replace') if isinstance(value, bytes) else value or ''
                        (folder/'wine.log').write_text(decoded(error.stdout)+decoded(error.stderr))
                        raise
                    (folder/'wine.log').write_text(p.stdout+p.stderr)
                    assert p.returncode == 0, f'{name}: exit {p.returncode}; see {folder}/wine.log'
                    metrics = json.loads((folder/'metrics.json').read_text())
                    assert metrics['simulated'] and metrics['save_calls'] == 0
                    assert (metrics['width'], metrics['height']) == (width, height)
                    bmp = (folder/'capture.bmp').read_bytes()
                    assert pixel(bmp, 0, 0) == (29, 36, 34)
                    if case == 'closed':
                        assert metrics['panel'] == [0,0,0,0]
                        assert pixel(bmp, width-100,100) == (29,36,34)
                    else:
                        x0,y0,x1,y1 = metrics['panel'];sx0,sy0,sx1,sy1=metrics['save']
                        assert abs(x1-(width-32*scale)) <= 1
                        assert abs(y0-32*scale) <= 1
                        assert y0 <= sy0 < sy1 < y1 <= height-32*scale+1
                        assert x0 <= sx0 < sx1 <= x1
                        assert pixel(bmp,int(x0+10*scale),int(y0+20*scale)) == (232,227,211)
                        if height == 1080 and scale == 2: assert metrics['body_scroll_max'] > 0
                    subprocess.run(['magick', str(folder/'capture.bmp'), str(folder/'capture.png')], check=True,
                                   capture_output=True)
                    (folder/'capture.bmp').unlink() # Current-task generated capture only; PNG retained.
                    results.append({'case':name,'passed':True,'png':str((folder/'capture.png').relative_to(ROOT)),**metrics})
                    print('PASS',name,flush=True)
    except Exception as error:
        (OUT/'render-validation.json').write_text(json.dumps({'passed':False,'captures':len(results),
            'directory':str(captures.relative_to(ROOT)),'error':str(error)},indent=2)+'\n')
        raise
    finally:
        # This environment names ONLY the preview prefix, never Steam/the user's Wine prefix.
        subprocess.run(['wineserver','-k'],env=env,capture_output=True)
    receipt = {'passed':True,'captures':len(results),'directory':str(captures.relative_to(ROOT)),
               'results':results,'limits':'Wine/Xvfb standalone D3D11 fixtures; not native Windows, ARM64, game hooks or real settings persistence'}
    (OUT/'render-validation.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({k:v for k,v in receipt.items() if k!='results'}))


def main():
    if sys.argv[1:] == ['--inside']:
        inside();return
    if sys.argv[1:] not in ([], ['--smoke']): raise SystemExit('Use no arguments or --smoke')
    for name in ['wine','wineserver','xvfb-run','magick']:
        assert shutil.which(name), f'Missing tool: {name}; no packages installed automatically'
    for name in ['prefix','home','cache','runtime']:
        (OUT/name).mkdir(parents=True,exist_ok=True)
    (OUT/'runtime').chmod(0o700)
    env = os.environ.copy()
    env.update(WINEPREFIX=str(OUT/'prefix'),HOME=str(OUT/'home'),XDG_CACHE_HOME=str(OUT/'cache'),
               XDG_RUNTIME_DIR=str(OUT/'runtime'),WINEDEBUG='-all',
               WINEDLLOVERRIDES='winemenubuilder.exe=d;mscoree,mshtml=',
               WAYLAND_DISPLAY='',LIBGL_ALWAYS_SOFTWARE='1',
               NIER_PREVIEW_SMOKE='1' if sys.argv[1:] == ['--smoke'] else '0')
    subprocess.run(['xvfb-run','-a','-s','-screen 0 3840x2160x24','python3',str(Path(__file__).resolve()),'--inside'],
                   env=env,cwd=OUT,check=True)


if __name__ == '__main__':
    main()
