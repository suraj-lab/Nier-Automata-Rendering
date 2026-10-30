#!/usr/bin/env python3
"""Gate: our Present hook must not be discoverable through DXGI's shared vtable.

Laptop 2026-10-30: with Remix starting, NieR died of a stack overflow looping ours -> Steam overlay -> ours. Steam
injects its overlay whatever the per-game toggle says. The mock's MOCK_OVERLAY_REHOOK stand-in behaves like typical
overlay code: it finds Present through a dummy swapchain's vtable (shared with the game's), patches the start of that
function, keeps ONE global original, and re-discovers at frame 30. With our hook in the shared slot the re-discovery
patches OUR function and the loop forms (red). With our hook in a private vtable on the game's swapchain only, the
shared slot keeps DXGI's function and every frame runs game -> ours -> overlay -> DXGI once (green).
STUB_NO_PRESENT_HOOK: the downstream DLAA stand-in hooks nothing, as NIER_DLAA does behind our proxy on the laptop.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
A = C.parent
OUT = A / 'runtime/present-overlay-rehook'
import test_remix_live as tr
import test_menu_overlay as tmo

KEYS = tuple(tr.ENV_KEYS) + ('MOCK_OVERLAY_REHOOK', 'STUB_NO_PRESENT_HOOK', 'MOCK_SECOND_PRESENT_CHAIN', 'MOCK_FOREIGN_SWAPCHAIN', 'MOCK_PROXY_FIRST_DEVICE')


def inside():
    work = Path(tempfile.mkdtemp(prefix='run-', dir=OUT))
    try:
        tmo.build(work)
        for k in KEYS:
            os.environ.pop(k, None)
        os.environ.update(MOCK_FRAME_MS='20', MOCK_OVERLAY_REHOOK='30', STUB_NO_PRESENT_HOOK='1')
        d, r, log = tmo.scenario(work, 'rehook', b'[Rendering]\r\nPreset=Custom75\r\n', True, (0, 0))
        for k in KEYS:
            os.environ.pop(k, None)
        loops, calls = int(r.get('overlay_loops', -1)), int(r.get('overlay_calls', -1))
        assert r.get('overlay_discoveries') == '2', f'the overlay stand-in did not run twice: {r}'
        assert loops == 0, f'Present looped through the overlay {loops} times after its re-discovery: {r}'
        assert calls >= 79, f'the overlay detour ran on {calls} frames, expected every frame: {r}'
        assert r.get('presented') == '80', f'frames lost: {r}'
        assert 'menu: ready' in log and 'hook Present slot 8 -> 0' in log, log[-800:]
        os.environ.update(MOCK_FRAME_MS='20', MOCK_OVERLAY_REHOOK='30', STUB_NO_PRESENT_HOOK='1', MOCK_SECOND_PRESENT_CHAIN='1')
        _, second, second_log = tmo.scenario(work, 'second-chain', b'[Rendering]\r\nPreset=Custom75\r\n', True, (0, 0))
        for k in KEYS:
            os.environ.pop(k, None)
        assert second.get('second_created') == '1', f'second swapchain was never created: {second}'
        assert second.get('second_calls') == '0', f'the first swapchain switched to the second chain: {second}'
        assert second.get('overlay_calls') == '80' and second.get('overlay_loops') == '0', second
        assert 'shared Present changed' in second_log, 'expected a changed shared downstream to be rejected'
        os.environ.update(MOCK_FRAME_MS='20', MOCK_OVERLAY_REHOOK='30', STUB_NO_PRESENT_HOOK='1', MOCK_FOREIGN_SWAPCHAIN='1', MOCK_PROXY_FIRST_DEVICE='1')
        _, foreign, foreign_log = tmo.scenario(work, 'foreign-device', b'[Rendering]\r\nPreset=Custom75\r\n', True, (0, 0))
        for k in KEYS:
            os.environ.pop(k, None)
        assert 'menu: ready' in foreign_log, 'a proxy-created temporary device prevented adoption of the game swapchain'
        assert foreign.get('foreign_created') == '1', f'foreign swapchain never created: {foreign}'
        assert foreign.get('foreign_hooked') == '0', f'our Present was installed on a foreign device: {foreign}'
        assert foreign.get('overlay_calls') == '80' and foreign.get('overlay_loops') == '0', foreign
        report = {'passed': True, 'overlay_calls': calls, 'overlay_loops': loops, 'second_chain': 'first chain preserved',
                  'foreign_device': 'not hooked', 'work': str(work),
                  'limits': 'Wine mock; models a dummy-swapchain discovering overlay, not Steam\'s actual code.'}
    except Exception as exc:
        (OUT / 'validation.json').write_text(json.dumps({'passed': False, 'error': str(exc)[-2000:], 'work': str(work)},
                                                        indent=2) + '\n')
        raise
    finally:
        subprocess.run(['wineserver', '-k'], env=os.environ, capture_output=True)
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
    for k in KEYS:
        env.pop(k, None)
    env.update(WINEPREFIX=str(OUT / 'prefix'), HOME=str(OUT / 'home'), XDG_CACHE_HOME=str(OUT / 'cache'),
               XDG_RUNTIME_DIR=str(OUT / 'xdg'), WINEDEBUG='-all', WAYLAND_DISPLAY='', LIBGL_ALWAYS_SOFTWARE='1',
               GALLIUM_DRIVER='llvmpipe', WINEDLLOVERRIDES='d3d11=n,b;winemenubuilder.exe=d;mscoree,mshtml=')
    subprocess.run(['xvfb-run', '-a', '-s', '-screen 0 1920x1080x24', sys.executable, str(Path(__file__).resolve()), '--inside'],
                   cwd=OUT, env=env, check=True)


if __name__ == '__main__':
    main()
