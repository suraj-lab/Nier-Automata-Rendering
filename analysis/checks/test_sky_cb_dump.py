#!/usr/bin/env python3
"""Frozen W1.2 gate: per-layer sky constant-buffer dump from a packed capture.

Fixture: `runtime/a1-intake-20261114/frame_67078468/scene.manifest` (laptop City Ruins pond capture, 2880x1800,
1176 draws; its texture paths resolve under `runtime/laptop-play-20261114/frame_67078468/`) plus
`runtime/a1-intake-20261114/frame_67279062/scene.manifest` (desert) as a second frame. Expected values are read off
those captures' own constant-buffer blobs and RDEF chunks, and the register indices agree with the 2026-11-15
disassembly of the same sky PS (`W1_SKY_CENSUS.md`: g_IntensityParam b1[1].y, g_UvOffset b3[1], g_MeshColor b4,
g_SpParam.w b2[4], g_FogColor b2[7]). `check_raw_bytes` recomputes two of the numbers from the blob with `struct`
alone, so the tool is not its own oracle.
"""
import importlib
import json
import struct
import subprocess
import sys
from pathlib import Path

C = Path(__file__).resolve().parent
A = C.parent
CAP = A / 'runtime' / 'a1-intake-20261114' / 'frame_67078468' / 'scene.manifest'
CAP2 = A / 'runtime' / 'a1-intake-20261114' / 'frame_67279062' / 'scene.manifest'
TOOL = C / 'sky_cb_dump.py'
WORK = A / 'runtime' / 'sky-cb-dump-gate'
SKY = 0x33856d1d3ba64bb3
SKY_ID = 550292875656          # this capture's own name for the sky pixel shader (its ps_hash)
FOG_COLOR = 5.7529401779174805  # g_FogColor.rgb in the pond capture, all three components


def load():
    assert TOOL.is_file(), 'sky_cb_dump.py missing: no per-layer sky CB dump exists'
    sys.path.insert(0, str(C))
    return importlib.import_module('sky_cb_dump')


def close(got, want, tol=1e-5):
    return len(got) == len(want) and all(abs(a - b) <= tol * max(1.0, abs(b)) for a, b in zip(got, want))


def check_api(m):
    records = m.dump(CAP)
    assert len(records) == 4, f'expected the 4 sky draws of this frame, got {len(records)}'
    assert [r['draw'] for r in records] == [812, 857, 887, 1133], f"draw ordinals {[r['draw'] for r in records]}"
    assert [r['indices'] for r in records] == [900, 690, 690, 1044], f"index counts {[r['indices'] for r in records]}"
    assert {r['ps_code'] for r in records} == {SKY}, 'a record is not the sky pixel shader'
    assert {r['ps_blob'] for r in records} == {'ps_550292875656.dxbc'}, 'wrong shader blob matched'

    # Duplicate cbuffer names (the sky PS declares PSParamBuffer1 twice, bind 1 and 2): the resolution must match
    # declared size against the sizes the sky's own draws bind, not the RDEF table order.
    flat = {name: reg for r in records for name, reg in r['registers'].items()}
    for name, want in [('g_IntensityParam', (1, 1)), ('g_AlbedoParam', (1, 3)), ('g_BaseBoolParam', (1, 0)),
                       ('g_lightColor', (2, 0)), ('g_lightVec', (2, 1)), ('g_FogParam', (2, 2)),
                       ('g_SpParam', (2, 4)), ('g_FogColor', (2, 7)), ('g_UvOffset', (3, 1)),
                       ('g_ShadowParam', (3, 2)), ('g_MeshColor', (4, 0)), ('g_CameraVec', (13, 1))]:
        assert flat.get(name) == want, f'{name} resolved to {flat.get(name)}, not {want}'

    def val(r, name):
        return r['values'][name]

    assert [val(r, 'g_IntensityParam')[1] for r in records] == [1.0, 6.0, 6.0, 1.0], 'per-layer intensity.y wrong'
    assert [val(r, 'g_AlbedoParam')[3] for r in records] == [1.0, 0.0, 0.0, 0.0], 'g_AlbedoParam.w flag wrong'
    assert close(val(records[0], 'g_AlbedoParam'), (0.0, 0.0, 0.0, 1.0)), 'black albedo override not read'
    assert [val(r, 'g_MeshColor') for r in records] == [(1.0, 1.0, 1.0, 1.0)] * 4, 'g_MeshColor tint wrong'
    assert close(val(records[0], 'g_FogColor'), (FOG_COLOR,) * 3 + (0.0,)), 'g_FogColor wrong'
    assert close(val(records[0], 'g_FogParam'), (0.0, 0.0019226443255320191, 1.4712200164794922, FOG_COLOR))
    assert [val(r, 'g_SpParam')[3] for r in records] == [1.0] * 4, 'g_SpParam.w wrong'
    assert all(val(r, 'g_UvOffset') == (0.0, 0.0, 0.0, 0.0) for r in records), 'g_UvOffset wrong'
    assert close(val(records[0], 'g_lightColor'), (10.0, 9.0, 7.0, 10.0)), 'g_lightColor wrong'
    assert [val(r, 'g_BaseBoolParam')[3] for r in records] == [1.0, 0.0, 0.0, 0.0], 'fog-skip flag wrong'

    # Layer 0 is a black albedo override with fog skipped and no blending; layer 3 is the blended one. Anyone
    # reading these numbers has to see that, so the dump must carry the draw state, not just the colours.
    assert records[0]['state'][:2] == [0, 2] and records[0]['state'][5:8] == [1, 0, 3], 'layer-0 state wrong'
    assert records[3]['state'][:2] == [1, 9] and records[3]['state'][7] == 4, 'layer-3 blend state wrong'

    # Textures: each layer samples its own t0; the fog LUT t12 is one stored face; AO (t17) and BeforeFog (t19) are
    # not bound at all in this capture, which is what makes the base term zero in the shader's own arithmetic.
    assert [r['textures']['t0']['id'] for r in records] == [88, 139, 171, 26], 'per-layer t0 identity wrong'
    assert {r['textures']['t12']['id'] for r in records} == {37}, 'fog LUT slot wrong'
    assert all(r['textures']['t17'] is None for r in records), 't17 reported where nothing is bound'
    assert all(r['textures']['t19'] is None for r in records), 't19 reported where nothing is bound'
    assert records[0]['textures']['t0']['width'] == 256 and records[0]['textures']['t0']['mips'] == 9, 't0 header wrong'
    assert records[1]['textures']['t0']['width'] == 2048, 't0 header wrong on layer 2'
    # The capture holds the fog LUT as a single-face 32x32 DXGI 87 texture although the shader declares a cube:
    # texture_capture::write_dds writes TEXTURE2D/array 1 only, so the dump must report what the file holds.
    assert records[0]['textures']['t12']['array'] == 1 and records[0]['textures']['t12']['cube'] is False, \
        'fog LUT reported as a cube the capture does not contain'
    assert records[0]['textures']['t12']['height'] == 32 and records[0]['textures']['t12']['dxgi'] == 87, \
        'fog LUT header wrong'

    # Only requested names are reported: a name the caller did not ask for (or the shader does not declare) is absent.
    assert set(records[0]['values']) == {n for n in m.NAMES}, f"unexpected value set {sorted(records[0]['values'])}"
    odd = m.dump(CAP, names=('g_UvOffsetDN', 'g_NoSuchValue'))
    assert odd and all('g_NoSuchValue' not in r['values'] for r in odd), 'reported a value nobody asked for'
    assert set(odd[0]['values']) <= {'g_UvOffsetDN'}, f"requested names leaked their neighbours: {sorted(odd[0]['values'])}"


def check_second_capture(m):
    records = m.dump(CAP2)
    assert len(records) == 4, f'desert frame has {len(records)} sky draws'
    assert close(records[0]['values']['g_FogColor'], (2.93726,) * 3 + (0.0,), tol=1e-4), \
        'desert g_FogColor is not the game’s per-area value; the 2026-11-13 "identical in every capture" note is superseded'
    assert close(records[0]['values']['g_lightColor'], (8.0, 7.2, 4.8, 8.0)), 'desert sun colour wrong'
    assert close(records[0]['values']['g_FogParam'], (0.0, 0.00117108, 0.882826, 2.93726), tol=1e-4), \
        'desert fog parameters wrong'


def check_raw_bytes(m):
    """Independent of the tool: read the draw-812 values straight out of the blob at the RDEF offsets."""
    blob = (CAP.parent / 'scene.cbs').read_bytes()
    lines = CAP.read_text().splitlines()
    base, size = None, None
    for i, line in enumerate(lines):
        if line.startswith('draw ') and line.endswith(f' {SKY_ID}'):
            for follow in lines[i + 1:]:
                if follow == 'end':
                    break
                if follow.startswith('pcb 2 '):
                    _, _slot, base, size = follow.split()
    assert base is not None, 'fixture draw 812 has no pcb 2'
    assert int(size) >= 128, f'pcb 2 is {size} bytes, the 128-byte declaration does not fit'
    want = struct.unpack_from('<4f', blob, int(base) + 112)
    got = m.dump(CAP)[0]['values']['g_FogColor']
    assert got == want, f'tool read {got} at pcb2+112, the blob holds {want}'
    for i, line in enumerate(lines):
        if line.startswith('draw ') and line.endswith(f' {SKY_ID}'):
            for follow in lines[i + 1:]:
                if follow == 'end':
                    break
                if follow.startswith('pcb 1 '):
                    b1 = int(follow.split()[2])
                    assert struct.unpack_from('<4f', blob, b1 + 16)[1] == m.dump(CAP)[0]['values'][
                        'g_IntensityParam'][1], 'intensity read from the wrong slot-1 offset'
                    return


def check_resolve(m):
    """Duplicate-name resolution, exercised directly: exact sizes win, equal claims are refused, not guessed."""
    shader = A / 'runtime' / 'laptop-play-20261114' / 'shaders' / 'ps_550292875656.dxbc'
    members, table = m.resolve(shader, {1: 112, 2: 128})
    assert members['g_IntensityParam'][:2] == (1, 1) and members['g_IntensityParam'][2] == 16, '64-byte -> slot 1'
    assert members['g_FogColor'][:2] == (2, 7) and members['g_FogColor'][2] == 112, '128-byte -> slot 2'
    assert {(c['name'], c['slot'], c['size']) for c in table} >= {('PSParamBuffer1', 1, 64), ('PSParamBuffer1', 2, 128)}
    try:
        m.resolve(shader, {1: 128, 2: 128})
    except SystemExit as error:
        assert 'ambiguous' in str(error), f'wrong refusal: {error}'
    else:
        raise AssertionError('two binds of the declared size were resolved by guessing')


def check_camp_trap(m):
    """A draw that is not the sky may bind exactly 128 bytes at pcb1, the declared size of the sky's 128-byte
    PSParamBuffer1 (the desktop camp capture `frame_30632051` does: pcb1 112 on its sky draws, 128 elsewhere). The
    sky's own bindings must decide, or g_FogColor lands in slot 1 and the dump reads past what the sky draw bound."""
    lines = CAP.read_text().splitlines()
    header = [l for l in lines if l.startswith(('replay', 'size', 'shaders', 'cbblob'))]
    sky, filler = None, None
    block = []
    for l in lines:
        if l.startswith('draw '):
            block = []
        block.append(l)
        if l == 'end':
            if sky is None and block[0].endswith(f' {SKY_ID}'):
                sky = block[:-1]
            elif filler is None and not block[0].endswith(f' {SKY_ID}'):
                filler = block[:-1]
    assert sky and filler, 'fixture manifest lost its draws'
    trap = [l for l in filler if not l.startswith(('pcb ', 'vcb ', 'tex ', 'vb ', 'buffer ', 'el '))]
    WORK.mkdir(parents=True, exist_ok=True)
    fixture = WORK / 'camp-trap.manifest'
    fixture.write_text('\n'.join(header + sky + trap + ['pcb 1 736 128', 'end']) + '\n')
    records = m.dump(fixture)
    assert len(records) == 1 and records[0]['draw'] == 0, f'fixture holds {len(records)} sky draws'
    assert records[0]['registers']['g_FogColor'] == (2, 7), \
        f"a 128-byte non-sky pcb1 moved g_FogColor to {records[0]['registers'].get('g_FogColor')}"
    assert close(records[0]['values']['g_FogColor'], (FOG_COLOR,) * 3 + (0.0,)), 'camp-trap values wrong'
    assert records[0]['values']['g_IntensityParam'][1] == 1.0, 'camp-trap intensity wrong'


def check_manifest_errors(m):
    """Damaged manifests must fail with a message that names the problem, never with a traceback or silent zeros."""
    WORK.mkdir(parents=True, exist_ok=True)
    head = '\n'.join(l for l in CAP.read_text().splitlines() if l.startswith(('replay', 'size', 'shaders', 'cbblob')))
    block, sky = [], None
    for l in CAP.read_text().splitlines():
        if l.startswith('draw '):
            block = []
        block.append(l)
        if l == 'end' and sky is None and block[0].endswith(f' {SKY_ID}'):
            sky = block
    assert sky, 'fixture manifest lost its sky draw'
    full = '\n'.join(sky)
    only_slot1 = '\n'.join([l for l in sky if not l.startswith('pcb 2 ')])
    cases = {
        'short-draw': (head + '\n' + 'draw 900 0 0\nend\n', 'draw line'),
        'pcb-after-end': (head + '\n' + full + '\npcb 1 0 16\n', 'after'),
        'duplicate-pcb': (head + '\n' + '\n'.join(l for l in sky if l != 'end') + '\npcb 1 0 112\nend\n', 'duplicate'),
        'unbound-member': (head + '\n' + full + '\n' + only_slot1, 'does not bind'),
    }
    for name, (text, want) in cases.items():
        path = WORK / f'{name}.manifest'
        path.write_text(text)
        run = subprocess.run([sys.executable, str(TOOL), str(path)], capture_output=True, text=True)
        assert run.returncode != 0, f'{name}: damaged manifest accepted'
        assert want in run.stderr + run.stdout and 'Traceback' not in run.stderr, \
            f'{name}: no clear message ({run.stderr.strip().splitlines()[-1:]})'


def check_cli(m):
    run = subprocess.run([sys.executable, str(TOOL), str(CAP)], capture_output=True, text=True)
    assert run.returncode == 0, f'CLI failed: {run.stderr.strip()[:400]}'
    out = run.stdout
    assert f'0x{SKY:016x}' in out and 'draws 4/' in out, f'CLI header missing: {out.splitlines()[:2]}'
    assert 'g_IntensityParam b1[1]' in out, 'CLI does not name the register of g_IntensityParam'
    again = subprocess.run([sys.executable, str(TOOL), str(CAP)], capture_output=True, text=True)
    assert again.stdout == out, 'dump is not deterministic'
    bogus = subprocess.run([sys.executable, str(TOOL), str(CAP), '--ps', '0xdeadbeefdeadbeef'],
                           capture_output=True, text=True)
    assert bogus.returncode != 0 and 'no draw' in (bogus.stdout + bogus.stderr), 'unknown shader accepted'
    missing = WORK / 'missing-cbs.manifest'
    WORK.mkdir(parents=True, exist_ok=True)
    missing.write_text('replay 1\nsize 1 1\nshaders /nonexistent\ncbblob /nonexistent/cbs\n')
    bad = subprocess.run([sys.executable, str(TOOL), str(missing)], capture_output=True, text=True)
    assert bad.returncode != 0 and 'Traceback' not in bad.stderr, 'missing cbblob produced a traceback'


def check_program(m):
    m.dump(CAP, json_out=WORK / 'pond.json')
    got = json.loads((WORK / 'pond.json').read_text())
    assert got['ps'] == SKY and len(got['draws']) == 4, 'json out does not carry the dump'
    assert any(c['name'] == 'PSParamBuffer1' and c['slot'] == 1 for c in got['cbuffers']), 'cbuffer table missing'


def main():
    m = load()
    for name, fn in (('api', check_api), ('second_capture', check_second_capture), ('raw_bytes', check_raw_bytes),
                     ('resolve', check_resolve), ('camp_trap', check_camp_trap),
                     ('manifest_errors', check_manifest_errors), ('cli', check_cli), ('program', check_program)):
        try:
            fn(m)
        except SystemExit as error:
            print(f'FAIL {name}: {error}')
            return 1
        except Exception as error:
            print(f'FAIL {name}: {error}')
            return 1
        print(f'ok {name}')
    print('sky_cb_dump gate green')
    return 0


if __name__ == '__main__':
    sys.exit(main())
