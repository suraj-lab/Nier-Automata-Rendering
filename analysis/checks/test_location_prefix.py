#!/usr/bin/env python3
"""Self-check for runtime/game-runs/make_location_prefix.py on a fake tree (real save untouched)."""
import importlib.util, json, sys, tempfile
from pathlib import Path as _P
from pathlib import Path
spec=importlib.util.spec_from_file_location('m',_P(__file__).resolve().parents[1] / "runtime/game-runs/make_location_prefix.py")
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
t=Path(tempfile.mkdtemp()); base=t/'prefix-base'; sv=base/m.SAVE_REL; sv.mkdir(parents=True)
for n,c in [('SlotData_0.dat',b'camp'),('GameData.dat',b'g-old'),('Graphic.ini',b'gfx')]: (sv/n).write_bytes(c)
real=t/'real'; real.mkdir()
for n,c in [('SlotData_0.dat',b'camp'),('SlotData_1.dat',b'pond'),('GameData.dat',b'g-new')]: (real/n).write_bytes(c)
d,man=m.build('pond',1,runs=t,base=base,real_save=real)
s=d/m.SAVE_REL; got={p.name:p.read_bytes() for p in s.iterdir()}
ok = got=={'SlotData_0.dat':b'pond','GameData.dat':b'g-new','Graphic.ini':b'gfx'} and (base/m.SAVE_REL/'SlotData_0.dat').read_bytes()==b'camp'
for bad in [lambda: m.build('pond',1,runs=t,base=base,real_save=real), lambda: m.build('x',5,runs=t,base=base,real_save=real), lambda: m.build('../x',1,runs=t,base=base,real_save=real)]:
    try: bad(); ok=False
    except ValueError: pass
print(json.dumps({'passed':ok,'got':{k:v.decode() for k,v in got.items()}}))
sys.exit(0 if ok else 1)
