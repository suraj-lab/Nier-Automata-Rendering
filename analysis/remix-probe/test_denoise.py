#!/usr/bin/env python3
"""Frozen gate for denoise.py and noise.py: spatial filtering of Remix stills.

Usage: test_denoise.py <denoise.py>

Synthetic fixtures only, so the gate never depends on 200 MB of runtime captures. It pins what the
filter must not get wrong: it must actually reduce noise, it must not soften a silhouette the way a
box filter does, it must leave a flat frame flat, and it must refuse bad input without writing output.
Prints {"passed": true, "checks": [...]}.
"""
import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

FOURCC_F16 = 113


def write_frame(path, rgb):
    """Legacy-header DDS holding `rgb` (h, w, 3) as 16-bit float RGBA -- the format Remix writes."""
    h, w = rgb.shape[:2]
    head = bytearray(124)
    struct.pack_into('<7I', head, 0, 124, 0x1 | 0x2 | 0x4 | 0x1000, h, w, 8 * w, 0, 1)
    struct.pack_into('<I', head, 72, 32)
    head[80:84] = struct.pack('<I', FOURCC_F16)
    struct.pack_into('<I', head, 104, 0x1000)
    px = np.concatenate([rgb, np.ones((h, w, 1), np.float32)], axis=2).astype('<f2')
    Path(path).write_bytes(b'DDS ' + bytes(head) + px.tobytes())


def noise_of(candidate_dir, frame, block=8):
    p = subprocess.run([sys.executable, str(candidate_dir / 'noise.py'), str(frame), '--json'],
                       capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, f'noise.py failed: {p.stderr[-300:]}'
    return json.loads(p.stdout)['noise']


def denoise(candidate, work, src, name, *args):
    out = work / f'{name}.png'
    if out.exists():
        out.unlink()
    p = subprocess.run([sys.executable, str(candidate), str(out), str(src), *args],
                       capture_output=True, text=True, timeout=600)
    return out, p


def main():
    candidate = Path(sys.argv[1]).resolve()
    work = Path(tempfile.mkdtemp(prefix='denoise-gate-'))
    checks = []
    try:
        rng = np.random.default_rng(20261027)

        # 1. A flat frame must stay flat: no method may invent structure.
        flat = np.full((32, 32, 3), 0.25, np.float32)
        write_frame(work / 'flat.dds', flat)
        for method in ('box', 'atrous'):
            out, p = denoise(candidate, work, work / 'flat.dds', f'flat-{method}', '--method', method)
            assert p.returncode == 0, f'flat/{method}: exit {p.returncode}: {p.stderr[-300:]}'
            img = np.asarray(Image.open(out), np.float32) / 255.0
            assert float(img.std()) < 0.01, f'flat/{method}: output not flat (std {img.std():.4f})'
        checks.append('a flat frame stays flat under both methods')

        # 2. Noisy flat field: filtering must genuinely reduce the metric, and more with a wider kernel.
        noisy = (0.25 + rng.normal(0, 0.02, (64, 64, 3))).astype(np.float32)
        write_frame(work / 'noisy.dds', noisy)
        n0 = noise_of(candidate.parent, work / 'noisy.dds')
        n3 = noise_of(candidate.parent, work / 'noisy.dds')
        assert abs(n0 - n3) < 1e-9, 'noise metric is not deterministic'
        _, p1 = denoise(candidate, work, work / 'noisy.dds', 'box1', '--method', 'box', '--radius', '1', '--json')
        _, p2 = denoise(candidate, work, work / 'noisy.dds', 'box2', '--method', 'box', '--radius', '2', '--json')
        _, p3 = denoise(candidate, work, work / 'noisy.dds', 'atr', '--method', 'atrous', '--json')
        for name, p in (('box1', p1), ('box2', p2), ('atrous', p3)):
            assert p.returncode == 0, f'{name}: exit {p.returncode}: {p.stderr[-300:]}'
        def reported(p):
            return float(json.loads(p.stdout)['ratio'])
        r1, r2, ra = reported(p1), reported(p2), reported(p3)
        assert r2 < r1 < 1.0, f'box radius 2 ({r2}) should clean more than radius 1 ({r1})'
        assert ra < 1.0, f'atrous did not reduce noise ({ra})'
        checks.append(f'noise falls with the kernel: box1 {r1:.2f}x, box2 {r2:.2f}x, atrous {ra:.2f}x')

        # 3. A silhouette must survive an edge-stopping filter and not survive a box blur.
        h = w = 96
        step = np.zeros((h, w, 3), np.float32)
        step[:, w // 2:] = 0.75
        step += rng.normal(0, 0.01, (h, w, 3)).astype(np.float32)
        write_frame(work / 'edge.dds', step)
        def gradient(path_png):
            a = np.asarray(Image.open(path_png).convert('L'), np.float32)
            return float(np.abs(np.diff(a, axis=1)).max())
        _, pb = denoise(candidate, work, work / 'edge.dds', 'edge-box', '--method', 'box', '--radius', '2')
        _, pa = denoise(candidate, work, work / 'edge.dds', 'edge-atr', '--method', 'atrous')
        assert pb.returncode == 0 and pa.returncode == 0, 'edge fixture failed'
        g_box, g_atr = gradient(work / 'edge-box.png'), gradient(work / 'edge-atr.png')
        assert g_atr > g_box * 1.3, f'atrous ({g_atr:.0f}) is not sharper than box ({g_box:.0f}) on a step edge'
        checks.append(f'an edge survives atrous ({g_atr:.0f}) better than box ({g_box:.0f})')

        # 4. Outlier rejection must kill a lone speck but keep a small real feature.
        speck = np.full((48, 48, 3), 0.2, np.float32)
        speck[10, 10] = 1.0                       # an isolated firefly
        speck[30:35, 30:35] = 0.9                 # a 5x5 feature: larger than the median window
        write_frame(work / 'speck.dds', speck)
        _, pf = denoise(candidate, work, work / 'speck.dds', 'speck', '--method', 'firefly')
        assert pf.returncode == 0, f'firefly: exit {pf.returncode}: {pf.stderr[-300:]}'
        out_img = np.asarray(Image.open(work / 'speck.png'), np.float32) / 255.0
        # sRGB encode: 1.0 -> 1.0, 0.2 -> ~0.48, 0.9 -> ~0.95
        assert out_img[10, 10].max() < 0.6, f"firefly not removed (pixel {out_img[10, 10].max():.2f})"
        assert out_img[32, 32].max() > 0.85, f'5x5 feature was destroyed ({out_img[32, 32].max():.2f})'
        checks.append('a lone firefly is removed while a 5x5 feature survives')

        # 5. Bad input is a clean exit, not a traceback and not a half-written file.
        (work / 'junk.dds').write_bytes(b'not a dds')
        out, p = denoise(candidate, work, work / 'junk.dds', 'junk')
        assert p.returncode == 2, f'non-DDS input: exit {p.returncode} (want 2)'
        assert 'Traceback' not in p.stderr, 'non-DDS input produced a traceback'
        assert not out.exists(), 'wrote output for invalid input'
        out, p = denoise(candidate, work, work / 'flat.dds', 'badmethod', '--method', 'nope')
        assert p.returncode == 2 and not out.exists(), 'unknown method was not refused'
        p = subprocess.run([sys.executable, str(candidate)], capture_output=True, text=True, timeout=120)
        assert p.returncode == 2, 'missing arguments did not exit 2'
        checks.append('non-DDS input, unknown method and missing arguments exit 2 cleanly')

        # 6. A NaN payload must be refused: it would otherwise become black in the sRGB encode.
        nan = np.full((16, 16, 3), np.nan, np.float32)
        write_frame(work / 'nan.dds', nan)
        out, p = denoise(candidate, work, work / 'nan.dds', 'nan')
        assert p.returncode == 2 and not out.exists(), 'NaN payload was not refused'
        checks.append('a NaN payload exits 2 without writing output')

        print(json.dumps({'passed': True, 'checks': checks}, indent=2))
    except AssertionError as e:
        print(json.dumps({'passed': False, 'error': str(e), 'checks_passed': checks}, indent=2))
        sys.exit(1)
    finally:
        import shutil
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
