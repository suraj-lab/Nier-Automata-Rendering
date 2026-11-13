#!/usr/bin/env python3
"""Make a small JPEG of a replay shot (or a crop of it) that fits an agent's modest size (pass offset=1 to the Read tool: context-mode refuses whole-file reads of big files).

  view.py <png> <out.jpg> [--crop x0,y0,x1,y1 (fractions 0..1)] [--width 1152] [--gamma 1.0]
"""
import argparse
import io
from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument('src')
ap.add_argument('dst')
ap.add_argument('--crop')
ap.add_argument('--width', type=int, default=1152)
ap.add_argument('--gamma', type=float, default=1.0)
a = ap.parse_args()
LIMIT = 180000
im = Image.open(a.src).convert('RGB')
if a.crop:
    x0, y0, x1, y1 = (float(v) for v in a.crop.split(','))
    im = im.crop((int(x0 * im.width), int(y0 * im.height), int(x1 * im.width), int(y1 * im.height)))
if a.gamma != 1.0:
    im = im.point([round(255 * (i / 255) ** (1 / a.gamma)) for i in range(256)] * 3)
width = min(a.width, im.width)
while True:
    small = im.resize((width, max(1, im.height * width // im.width)), Image.LANCZOS)
    for quality in (80, 70, 60, 50, 40):
        buf = io.BytesIO()
        small.save(buf, 'JPEG', quality=quality)
        if buf.tell() <= LIMIT:
            open(a.dst, 'wb').write(buf.getvalue())
            print(a.dst, small.size, quality, buf.tell())
            raise SystemExit(0)
    width = width * 7 // 8
