# Hidden negative/extra cases for capture_to_mesh.py (not shown to the worker). Usage: test_hidden.py <candidate>
import sys, json, struct, tempfile, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pathlib import Path
import test_capture_to_mesh as t
cand = Path(sys.argv[1]).resolve(); work = Path(tempfile.mkdtemp()); res = []
def case(name, fn):
    try: fn(); res.append((name, True, ''))
    except Exception as e: res.append((name, False, str(e)[:300]))
def _trunc(d): b = (d/'ib.bin').read_bytes(); (d/'ib.bin').write_bytes(b[:3]); return d
def _patch(d, **kw):
    m = json.loads((d/'capture.json').read_text()); m.update(kw); (d/'capture.json').write_text(json.dumps(m)); return d
def _patch_layout(d, fmt):
    m = json.loads((d/'capture.json').read_text()); m['layout'][0]['format'] = fmt; (d/'capture.json').write_text(json.dumps(m)); return d
def _rm(d, n): (d/n).unlink(); return d
case('index out of range -> 2', lambda: t.expect_fail(cand, t.synth(work, 'oor', indices=(0,1,9)), work, 'oor', 2))
case('short index buffer -> 2', lambda: t.expect_fail(cand, t.synth(work, 'short', start_index=0, indices=(0,1,2)) and _trunc(work/'short'), work, 'short', 2))
case('unsupported ib_format -> 2', lambda: t.expect_fail(cand, _patch(t.synth(work, 'fmt'), ib_format=41), work, 'fmt', 2))
case('unsupported POSITION format -> 2', lambda: t.expect_fail(cand, _patch_layout(t.synth(work, 'pf'), 28), work, 'pf', 2))
case('POSITION half4 (fmt 10) ok', lambda: t.expect_ok(cand, t.synth(work, 'h4', pos_format=10, slot1=True), work, 'h4'))
case('POSITION f32x4 (fmt 2) ok', lambda: t.expect_ok(cand, _patch_layout(t.synth(work, 'f4'), 2), work, 'f4'))
case('missing vb_1.bin -> defaults', lambda: t.expect_ok(cand, _rm(t.synth(work, 'novb1', slot1=True), 'vb_1.bin'), work, 'novb1'))
case('missing capture.json -> 2', lambda: t.expect_fail(cand, _rm(t.synth(work, 'nojson'), 'capture.json'), work, 'nojson', 2))
case('negative base_vertex out of range -> 2', lambda: t.expect_fail(cand, _patch(t.synth(work, 'neg'), base_vertex=-5), work, 'neg', 2))
print(json.dumps({'passed': all(r[1] for r in res), 'results': res}, indent=1)); shutil.rmtree(work, ignore_errors=True)
