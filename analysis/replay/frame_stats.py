import sys
import numpy as np
from PIL import Image
def stats(path, crop_hud=True):
    a = np.asarray(Image.open(path).convert('RGB')).astype(np.float64) / 255.0
    h, w, _ = a.shape
    if crop_hud: a = a[int(h*0.12):int(h*0.95), int(w*0.02):int(w*0.80)]   # drop the HUD corner text
    lin = a
    l = 0.2126*lin[...,0] + 0.7152*lin[...,1] + 0.0722*lin[...,2]
    mx, mn = a.max(2), a.min(2)
    sat = np.where(mx > 1e-3, (mx-mn)/np.maximum(mx,1e-3), 0)
    m = a.reshape(-1,3).mean(0)
    return dict(median=float(np.median(l)), p95=float(np.percentile(l,95)), p05=float(np.percentile(l,5)), sat=float(sat.mean()),
                r=float(m[0]), g=float(m[1]), b=float(m[2]), rb=float(m[0]/max(m[2],1e-3)))
for p in sys.argv[1:]:
    s = stats(p); print(f"{p.split('/')[-3] if 'shots' in p else p.split('/')[-2]:24s} " + ' '.join(f'{k}={v:.3f}' for k,v in s.items()))
