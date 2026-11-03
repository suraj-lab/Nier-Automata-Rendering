#!/usr/bin/env python3
"""frametime1: join the user's recording (post-tonemap truth, method from Rayman3-RTX session-findings 6.1) with the
live log's 60-frame report windows. Per window: distinct-image rate and longest visible freeze in the video, against
the worker's `other` ms and the number of new texture outputs. Read-only; needs ffmpeg/ffprobe and numpy.

    python3 frametime1_video.py   # decodes the 1.7 GB mp4 to /tmp at 96x60 once (~2 min on 16 threads)
"""
import json, os, re, subprocess
import numpy as np

ROOT = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'runtime', 'laptop-port')
MP4 = os.path.join(ROOT, 'frametime1', 'frametime1.mp4')
LOG = os.path.join(ROOT, 'frametime1-20261101T203530Z.json')
T0 = 20 * 3600 + 37 * 60 + 16.16   # recording file name "NieR Automata 2026.11.01 - 20.37.16.16.mp4"
W, H = 96, 60
RAW, PTS = '/tmp/ft1_small.rgb', '/tmp/ft1_pts.txt'
CHANGED = 1.0                       # mean |dRGB| per pixel; the diff histogram is bimodal around it

if not os.path.exists(RAW):
    with open(PTS, 'w') as f:
        subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'frame=pts_time',
                        '-of', 'csv=p=0', MP4], stdout=f, check=True)
    subprocess.run(['ffmpeg', '-v', 'error', '-threads', '16', '-i', MP4, '-vf', f'scale={W}:{H}:flags=area,format=rgb24',
                    '-f', 'rawvideo', '-fps_mode', 'passthrough', RAW], check=True)
frames = np.fromfile(RAW, dtype=np.uint8).reshape(-1, H, W, 3).astype(np.float32)
pts = np.array([float(x) for x in open(PTS).read().split()])
assert len(pts) == len(frames), (len(pts), len(frames))
diff = np.abs(frames[1:] - frames[:-1]).mean(axis=(1, 2, 3))
updates = pts[np.concatenate([[True], diff > CHANGED])]

def secs(t):
    h, m, s = t.split(':')
    return int(h) * 3600 + int(m) * 60 + float(s)

rows, cur = [], {}
for line in json.load(open(LOG))['log'].splitlines():
    m = re.search(r'remix: ([\d.]+) fps over the last \d+ frames \(ms/frame: (.*)\)', line)
    if m:
        cur = {'t': line[:12], 'fps': float(m.group(1)), **dict((k, float(v)) for k, v in re.findall(r'(\w+) (-?[\d.]+)', m.group(2)))}
    elif 'remix: live draws' in line:
        if 't' in cur:
            cur['textures'] = float(re.search(r'textures=(\d+)', line).group(1))
            rows.append(cur)
        cur = {}

out = []
for prev, row in zip(rows, rows[1:]):
    s, e = secs(prev['t']) - T0, secs(row['t']) - T0
    if s < 0 or e > pts[-1]:
        continue
    u = updates[(updates >= s) & (updates < e)]
    out.append((row['t'], row['fps'], len(u) / (e - s), np.diff(u).max() * 1000 if len(u) > 2 else 0.0,
                row['other'], row['textures'] - prev['textures']))
print('window_end  log_fps  video_updates/s  longest_freeze_ms  other_ms  new_textures')
for r in out:
    print('%s  %5.1f  %5.1f  %6.0f  %6.1f  %4d' % r)
c = lambda i, j: np.corrcoef([r[i] for r in out], [r[j] for r in out])[0, 1]
print('windows=%d  r(log fps, video updates)=%.2f  r(longest freeze, new textures)=%.2f  r(video updates, new textures)=%.2f'
      % (len(out), c(1, 2), c(3, 5), c(2, 5)))
