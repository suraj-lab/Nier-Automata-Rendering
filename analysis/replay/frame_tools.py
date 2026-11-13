#!/usr/bin/env python3
"""Numbers and comparison sheets for replay shots (the method of analysis/PLAN_2026-11-13.md, sections 2 and 3b).

  frame_tools.py stats <png> [<png> ...]                 one line per shot: luma percentiles, clip, crush, saturation
  frame_tools.py diff  <a.png> <b.png>                   mean absolute difference in grey levels (0..255)
  frame_tools.py sheet <out.jpg> <label>=<png> [...]     panels side by side, labelled, same size (for the user to pick)
        [--crop x0,y0,x1,y1]   fractions 0..1: adds a second row with that region at full resolution

Luma is Rec.709 on the 8-bit values as stored (no linearisation): it is a ranking number, not photometry.
Two runs of the same static frame differ by 1.1-1.3 grey levels (denoiser noise): a diff below 2 is "unchanged".
"""
import sys
from PIL import Image, ImageDraw
import numpy as np


def stats(path):
    a = np.asarray(Image.open(path).convert('RGB')).astype(np.float32) / 255
    y = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
    mx, mn = a.max(-1), a.min(-1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    return {'median': float(np.percentile(y, 50)), 'p95': float(np.percentile(y, 95)),
            'clip_pct': float(100 * (y > 0.98).mean()), 'crush_pct': float(100 * (y < 0.02).mean()),
            'saturation': float(sat.mean())}


def diff(a, b):
    return float(np.abs(np.asarray(Image.open(a).convert('RGB'), dtype=np.float32) -
                        np.asarray(Image.open(b).convert('RGB'), dtype=np.float32)).mean())


def sheet(out, panels, crop=None, width=760):
    images = [(label, Image.open(path).convert('RGB')) for label, path in panels]
    w0, h0 = images[0][1].size
    assert all(im.size == (w0, h0) for _, im in images), 'panels differ in size: not the same capture and frame'
    h = h0 * width // w0
    rows = [[im.resize((width, h), Image.LANCZOS) for _, im in images]]
    if crop:
        x0, y0, x1, y1 = (float(v) for v in crop.split(','))
        box = (int(x0 * w0), int(y0 * h0), int(x1 * w0), int(y1 * h0))
        rows.append([im.crop(box).resize((width, (box[3] - box[1]) * width // (box[2] - box[0])), Image.LANCZOS)
                     for _, im in images])
    canvas = Image.new('RGB', (len(images) * (width + 10) - 10, 28 + sum(r[0].height + 8 for r in rows)), (20, 20, 20))
    draw = ImageDraw.Draw(canvas)
    top = 28
    for row in rows:
        for i, im in enumerate(row):
            canvas.paste(im, (i * (width + 10), top))
        top += row[0].height + 8
    for i, (label, _) in enumerate(images):
        draw.text((i * (width + 10) + 6, 8), label, fill=(255, 255, 255))
    canvas.save(out, quality=88)


def main():
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == 'stats':
        for path in args[1:]:
            s = stats(path)
            print(f"{path}: median={s['median']:.3f} p95={s['p95']:.3f} clip={s['clip_pct']:.1f}% "
                  f"crush={s['crush_pct']:.1f}% saturation={s['saturation']:.3f}")
    elif len(args) == 3 and args[0] == 'diff':
        print(f'{diff(args[1], args[2]):.2f}')
    elif len(args) >= 3 and args[0] == 'sheet':
        crop = None
        if '--crop' in args:
            crop = args[args.index('--crop') + 1]
            del args[args.index('--crop'):args.index('--crop') + 2]
        sheet(args[1], [tuple(p.split('=', 1)) for p in args[2:]], crop)
        print(args[1])
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
