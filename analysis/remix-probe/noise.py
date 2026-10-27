#!/usr/bin/env python3
"""Within-block noise metric for Remix frames.

Defined once so filter results are comparable across sessions. Remix's API-only path never denoises
(see PROGRESS.md), so this number is the only way to say whether a change helped:

    noise = mean over BLOCK x BLOCK tiles of std(luma inside the tile) / mean(luma over the frame)

Blocks are used rather than the whole frame so that large-scale shading does not count as noise, and
luma is Rec.709. Report the ratio to an unfiltered frame; the recorded history is box 3x3 = 0.62x and
box 5x5 = 0.53x on a real 1028x540 frame, which is far worse than sqrt(N) because the noise is
spatially correlated.

Usage: noise.py <frame.dds> [--block N] [--json]
"""
import json
import sys

import numpy as np

from dds_stack import load

LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)


def luma(rgb):
    return (rgb.astype(np.float32) @ LUMA).astype(np.float32)


MIN_MEAN_LUMA = 0.02  # below this the ratio carries no information: a near-black frame divides by ~0


def mean_luma(rgb):
    return float(luma(rgb).mean())


def measure(rgb, block=8):
    """Mean within-tile luma standard deviation, normalised by mean luma. 0.0 for a flat frame.

    The denominator is floored at MIN_MEAN_LUMA: a diagnostic frame that is almost entirely black
    otherwise reports noise > 1, which says nothing about denoising quality (seen on 2 of 46 stored
    frames, 2026-10-27).
    """
    y = luma(rgb)
    mean = max(float(y.mean()), MIN_MEAN_LUMA)
    if not np.isfinite(mean):
        return 0.0
    h, w = y.shape
    b = max(1, int(block))
    tiles = []
    for ty in range(0, h - b + 1, b):
        for tx in range(0, w - b + 1, b):
            tiles.append(float(y[ty:ty + b, tx:tx + b].std()))
    if not tiles:
        return 0.0
    return float(np.mean(tiles)) / mean


def main(argv):
    if not argv:
        print('usage: noise.py <frame.dds> [--block N] [--json]', file=sys.stderr)
        return 2
    block = 8
    if '--block' in argv:
        block = int(argv[argv.index('--block') + 1])
    try:
        frame = load(argv[0])
    except (ValueError, OSError) as e:
        print(f'noise: {e}', file=sys.stderr)
        return 2
    value = measure(frame, block)
    if '--json' in argv:
        print(json.dumps({'frame': argv[0], 'block': block, 'noise': round(value, 4),
                          'mean_luma': round(mean_luma(frame), 4)}))
    else:
        print(f'{argv[0]}: noise {value:.4f} (block {block})')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
