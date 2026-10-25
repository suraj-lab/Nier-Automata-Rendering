# Hidden cases for scene_from_frame.py (not shown to the worker). Usage: test_hidden.py <candidate>
import sys, json, struct, tempfile, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pathlib import Path
import test_scene_from_frame as t
cand = Path(sys.argv[1]).resolve(); work = Path(tempfile.mkdtemp()); res = []
def patch(d, **kw):
    m = json.loads((d/'capture.json').read_text()); m.update(kw); (d/'capture.json').write_text(json.dumps(m)); return d
def frame(name):
    f = work / name; f.mkdir(); return f
def case(name, fn):
    try: fn(); res.append((name, True, ''))
    except Exception as e: res.append((name, False, str(e)[:300]))
def r32_base():
    f = frame('r32'); d = t.draw(f, 0, cb11=t.mat34(10, (1, 2, 3)))
    vb = (d/'vb_0.bin').read_bytes(); (d/'vb_0.bin').write_bytes(bytes(28 * 2) + vb)  # 2 padding rows
    (d/'ib.bin').write_bytes(bytes(8) + struct.pack('<6I', 0, 1, 2, 0, 2, 3))
    patch(d, ib_format=42, ib_offset=4, start_index=1, base_vertex=2, index_count=6)
    t.expect_ok(cand, f, work, 'r32')
def half_pos():
    f = frame('half'); d = t.draw(f, 0, cb11=t.mat34(0, (0, 0, 0)))
    rows = bytearray()
    for p in [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]: rows += struct.pack('<4e', *p, 1) + bytes(20)
    (d/'vb_0.bin').write_bytes(rows); m = json.loads((d/'capture.json').read_text()); m['layout'][0]['format'] = 10
    (d/'capture.json').write_text(json.dumps(m)); t.expect_ok(cand, f, work, 'half')
def blend_slot1():
    f = frame('slot1'); d = t.draw(f, 0, skinned=True, bones=[t.mat34(0, (0, 0, 1)), t.mat34(30, (0, 1, 0))], weights=(200, 55, 0, 0))
    vb = (d/'vb_0.bin').read_bytes(); s1 = b''.join(vb[i*28+20:i*28+28] for i in range(4))
    (d/'vb_1.bin').write_bytes(s1); m = json.loads((d/'capture.json').read_text())
    m['vertex_buffers'].append({'slot': 1, 'stride': 8, 'offset': 0, 'bytes': len(s1)})
    for e in m['layout'][1:]: e['slot'] = 1; e['offset'] -= 20
    (d/'capture.json').write_text(json.dumps(m)); t.expect_ok(cand, f, work, 'slot1')
def zero_weight_oob():
    f = frame('zw'); d = t.draw(f, 0, skinned=True, bones=[t.mat34(0, (0, 0, 0))], weights=(255, 0, 0, 0))
    vb = bytearray((d/'vb_0.bin').read_bytes())
    for i in range(4): vb[i*28+20:i*28+24] = bytes((0, 9, 9, 9))  # idx 9 only with weight 0
    (d/'vb_0.bin').write_bytes(vb)
    s = t.expect_ok(cand, f, work, 'zero weight')[0]; assert s['kept'] == 1, s
def remainder():
    f = frame('rem'); t.draw(f, 0, cb11=t.mat34(0, (0, 0, 0)), indices=(0, 1, 2, 0, 2))
    s = t.expect_ok(cand, f, work, 'remainder')[0]; assert s['triangles'] == 1, s
def vp_tie():
    f = frame('tie'); t.draw(f, 0, vp=(100, 100), cb11=t.mat34(0, (0, 0, 0))); t.draw(f, 1, vp=(200, 100), cb11=t.mat34(0, (1, 0, 0)))
    s = t.expect_ok(cand, f, work, 'tie')[0]; assert s['other_viewport'] == 1, s
def ib_range():
    f = frame('ibr'); d = t.draw(f, 0, cb11=t.mat34(0, (0, 0, 0))); t.draw(f, 1, cb11=t.mat34(0, (1, 0, 0)))
    patch(d, index_count=99); s = t.expect_ok(cand, f, work, 'ib range')[0]; assert s['rejected'] == 1, s
for n, fn in [('R32 + ib_offset/start/base', r32_base), ('POSITION half4', half_pos), ('blend elements in slot 1', blend_slot1),
              ('zero-weight out-of-range bone ignored', zero_weight_oob), ('index remainder ignored', remainder),
              ('viewport tie -> larger area', vp_tie), ('index buffer overrun -> reject draw', ib_range)]:
    case(n, fn)
print(json.dumps({'passed': all(r[1] for r in res), 'results': res}, indent=1)); shutil.rmtree(work, ignore_errors=True)
