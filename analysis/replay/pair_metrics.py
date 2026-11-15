#!/usr/bin/env python3
"""Per-region comparison of an original/Remix frame pair (W2), with exclusion masks.

    compare(original_path, remix_path, spec) -> regions, deltas, identical, frame_delta, excluded_pixels

Metrics are defined exactly as in frame_tools.py: Rec.709 luma on the stored 8-bit values, no linearisation, and
mean (max-min)/max for saturation. Percent metrics are 0..100. `frame_delta` is the mean absolute difference in
grey levels over non-excluded pixels only, so it cannot be dominated by the pixels the spec excludes. A size mismatch
is an error, never a resample.
"""
from pathlib import Path

import numpy as np
from PIL import Image


def _rect(name, value):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f'region {name!r} must be [x0,y0,x1,y1]')
    try:
        x0, y0, x1, y1 = (float(v) for v in value)
    except (TypeError, ValueError):
        raise ValueError(f'region {name!r} has non-numeric bounds')
    if not all(0.0 <= v <= 1.0 for v in (x0, y0, x1, y1)):
        raise ValueError(f'region {name!r} bounds outside 0..1: {value!r}')
    if x0 >= x1 or y0 >= y1:
        raise ValueError(f'region {name!r} is inverted or empty: {value!r}')
    return x0, y0, x1, y1


def _pixels(rect, width, height):
    x0, y0, x1, y1 = rect
    px, py = int(round(x0 * width)), int(round(y0 * height))
    qx, qy = int(round(x1 * width)), int(round(y1 * height))
    qx, qy = min(max(qx, px + 1), width), min(max(qy, py + 1), height)
    px, py = min(px, qx - 1), min(py, qy - 1)
    return slice(py, qy), slice(px, qx)


def _read(path):
    image = Image.open(path)
    return np.asarray(image.convert('RGB'), dtype=np.float32) / 255.0


def _stats(rgb):
    if rgb.size == 0:
        raise ValueError('region contains no comparable pixels')
    luma = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    high, low = rgb.max(-1), rgb.min(-1)
    saturation = np.where(high > 0, (high - low) / np.maximum(high, 1e-6), 0.0)
    return {'median': float(np.percentile(luma, 50)), 'p95': float(np.percentile(luma, 95)),
            'clip_pct': float(100.0 * (luma > 0.98).mean()), 'crush_pct': float(100.0 * (luma < 0.02).mean()),
            'saturation': float(saturation.mean())}


METRICS = ('median', 'p95', 'clip_pct', 'crush_pct', 'saturation')


def compare(original_path, remix_path, spec):
    if not isinstance(spec, dict) or not isinstance(spec.get('regions'), dict) or not spec['regions']:
        raise ValueError('spec needs a non-empty "regions" mapping')
    regions = {name: _rect(name, value) for name, value in spec['regions'].items()}
    raw_excluded = spec.get('exclude', [])
    if not isinstance(raw_excluded, (list, tuple)):
        raise ValueError('spec "exclude" must be a list of [x0,y0,x1,y1] rects')
    excluded = [_rect(f'exclude[{i}]', value) for i, value in enumerate(raw_excluded)]
    original, remix = _read(original_path), _read(remix_path)
    if original.shape != remix.shape:
        raise ValueError(f'frame size mismatch: {original.shape[1]}x{original.shape[0]} vs '
                         f'{remix.shape[1]}x{remix.shape[0]}')
    height, width = original.shape[:2]
    keep = np.ones((height, width), dtype=bool)
    for rect in excluded:
        keep[_pixels(rect, width, height)] = False
    out = {'regions': {}, 'identical': bool(np.array_equal(original, remix)),
           'frame_delta': float(np.abs(original - remix)[keep].mean() * 255.0),
           'excluded_pixels': int((~keep).sum())}
    for name, rect in regions.items():
        rows, cols = _pixels(rect, width, height)
        for side, array in (('original', original), ('remix', remix)):
            mask = keep[rows, cols]
            rgb = array[rows, cols][mask]
            out['regions'].setdefault(name, {})[side] = _stats(rgb)
        out['regions'][name]['delta'] = {
            metric: out['regions'][name]['remix'][metric] - out['regions'][name]['original'][metric]
            for metric in METRICS}
        out['regions'][name]['pixels'] = int(keep[rows, cols].sum())
    return out
