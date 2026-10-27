#!/usr/bin/env python3
"""Spatial denoise for Remix stills, applied outside the renderer.

Remix's denoiser does not engage for an API-only client (PROGRESS.md: five configurations, noise
unchanged), so the stills path filters afterwards. A box filter is the recorded baseline (0.62x at
3x3, 0.53x at 5x5) and blurs as much as it cleans; `atrous` is the edge-stopping version: three
5x5 passes at steps 1/2/4 that weight neighbours by luma difference, so a flat noisy area is smoothed
while a silhouette stays put.

Usage: denoise.py <out.png> <frame.dds> [--method box|atrous|firefly|firefly+atrous]
                 [--radius N] [--sigma S] [--firefly RATIO] [--json]
"""
import json
import sys

import numpy as np
from PIL import Image

from dds_stack import load
from noise import measure

LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)


def _shifted(a, dy, dx):
    """Move `a` by (dy, dx) with edge replication, so the output keeps the input's shape."""
    p = max(abs(dy), abs(dx))
    padded = np.pad(a, ((p, p), (p, p), (0, 0)), mode='edge')
    h, w = a.shape[:2]
    return padded[p + dy:p + dy + h, p + dx:p + dx + w]


def box(rgb, radius=2):
    acc = np.zeros_like(rgb, np.float32)
    n = 0
    r = max(1, int(radius))
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            acc += _shifted(rgb.astype(np.float32), dy, dx)
            n += 1
    return acc / n


def _median(rgb, radius=1):
    """Per-channel median over a (2r+1)^2 window, edges replicated."""
    from numpy.lib.stride_tricks import sliding_window_view
    a = rgb.astype(np.float32)
    r = max(1, int(radius))
    padded = np.pad(a, ((r, r), (r, r), (0, 0)), mode='edge')
    win = sliding_window_view(padded, (2 * r + 1, 2 * r + 1), axis=(0, 1))
    return np.median(win, axis=(-2, -1))


def firefly(rgb, radius=1, ratio=1.5, absolute=0.02):
    """Replace isolated bright outliers with the local median.

    The noise in a Remix still is sparse high-amplitude speckle, and an edge-stopping filter keeps it
    (a firefly looks exactly like an edge to it). A pixel is an outlier when its luma exceeds the local
    median by both a ratio and an absolute margin -- the absolute term keeps dark regions from being
    reclassified by rounding.
    """
    a = rgb.astype(np.float32)
    med = _median(a, radius)
    y, y_med = a @ LUMA, med @ LUMA
    outlier = (y > y_med * ratio + absolute)
    out = np.where(outlier[:, :, None], med, a)
    return out


def atrous(rgb, sigma=0.06, steps=(1, 2, 4)):
    """Three edge-stopping 5x5 passes. sigma is in linear-luma units: neighbours further away than
    this contribute little, which is what keeps an edge from being averaged across."""
    out = rgb.astype(np.float32)
    for step in steps:
        centre = out
        y_c = centre @ LUMA
        acc = np.zeros_like(out)
        wsum = np.zeros(out.shape[:2], np.float32)
        for dy in (-2, -1, 0, 1, 2):
            for dx in (-2, -1, 0, 1, 2):
                ny, nx = dy * step, dx * step
                nb = _shifted(centre, ny, nx)
                spatial = np.exp(-(dy * dy + dx * dx) / (2 * 1.5 * 1.5))
                dy_l = (_shifted(centre, ny, nx) @ LUMA) - y_c
                w = spatial * np.exp(-(dy_l * dy_l) / (2 * sigma * sigma))
                acc += nb * w[:, :, None]
                wsum += w
        out = acc / np.maximum(wsum, 1e-8)[:, :, None]
    return out


def to_png(rgb):
    return Image.fromarray((np.clip(rgb, 0, 1) ** (1 / 2.2) * 255).astype(np.uint8))


def main(argv):
    if len(argv) < 2:
        print('usage: denoise.py <out.png> <frame.dds> [--method box|atrous] [--radius N] [--sigma S]',
              file=sys.stderr)
        return 2
    out_path, in_path = argv[0], argv[1]
    method = 'atrous'
    radius, sigma = 2, 0.06
    firefly_ratio = 1.5
    if '--method' in argv:
        method = argv[argv.index('--method') + 1]
    if '--radius' in argv:
        radius = int(argv[argv.index('--radius') + 1])
    if '--sigma' in argv:
        sigma = float(argv[argv.index('--sigma') + 1])
    if '--firefly' in argv:
        firefly_ratio = float(argv[argv.index('--firefly') + 1])
    if method not in ('box', 'atrous', 'firefly', 'firefly+atrous'):
        print(f'denoise: unknown method {method!r}', file=sys.stderr)
        return 2
    try:
        frame = load(in_path)
        if not np.isfinite(frame).all():
            print('denoise: non-finite pixel values', file=sys.stderr)
            return 2
        before = measure(frame)
        if method == 'box':
            filtered = box(frame, radius)
        elif method == 'atrous':
            filtered = atrous(frame, sigma)
        elif method == 'firefly':
            filtered = firefly(frame, 1, firefly_ratio)
        else:
            filtered = atrous(firefly(frame, 1, firefly_ratio), sigma)
        after = measure(filtered)
        to_png(filtered).save(out_path)
    except (ValueError, OSError) as e:
        print(f'denoise: {e}', file=sys.stderr)
        return 2
    ratio = after / before if before else 0.0
    if '--json' in argv:
        print(json.dumps({'method': method, 'before': round(before, 4), 'after': round(after, 4),
                          'ratio': round(ratio, 4), 'out': str(out_path)}))
    else:
        print(f'{method}: noise {before:.4f} -> {after:.4f} ({ratio:.2f}x) -> {out_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
