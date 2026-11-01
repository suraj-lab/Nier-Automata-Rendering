#!/usr/bin/env python3
"""Gate: pbr_trace.py names albedo, metalness, gloss and normal maps exactly as hand-traced in the game's shaders.

Synthetic shader (always): the patterns of ps_1874571568 in miniature, including a constant override inside a branch
(must not erase the texture source) and screen-space AO multiplied into the albedo (must not count as material).
Real shaders (when analysis/runtime/pbr-re holds their disassembly): the table in analysis/PBR_MAPPING.md.
"""
import json
import sys
from pathlib import Path

C = Path(__file__).resolve().parent
sys.path.insert(0, str(C))
import pbr_trace  # noqa: E402

LIT = """ps_5_0
dcl_resource_texture2d (float,float,float,float) t0
sample_indexable(texture2d) r1.xyzw, v1.xyxx, t0.xyzw, s0
lt r2.x, r1.w, l(8.00000012e-01)
discard_nz r2.x
sample_indexable(texture2d) r7.xyzw, v1.xyxx, t2.zxyw, s2
ne r0.x, l(0.00000000e+00), cb1[0].y
if_nz r0.x
  mov r7.y, cb1[5].y
endif
sample_indexable(texture2d) r0.xyz, v1.xyxx, t3.xyzw, s3
add r0.xyz, r0.xyzx, l(-5.00000000e-01, -5.00000000e-01, -5.00000000e-01, 0.00000000e+00)
sample_indexable(texture2d) r6.zw, v1.xyxx, t4.zwxy, s4
mad r6.zw, r6.zzzw, l(0.00000000e+00, 0.00000000e+00, 2.00000000e+00, 2.00000000e+00), l(0.00000000e+00, 0.00000000e+00, -1.00000000e+00, -1.00000000e+00)
sample_indexable(texture2d) r9.x, v0.xyxx, t17.xyzw, s11
mul r1.xyz, r1.xyzx, r9.x
add r7.zw, -r7.zzzy, l(0.00000000e+00, 0.00000000e+00, 1.00000000e+00, 1.00000000e+00)
mad r11.xyz, r1.xyzx, cb4[0].xyzx, l(-2.99999993e-02, -2.99999993e-02, -2.99999993e-02, 0.00000000e+00)
mad r11.xyz, r7.y, r11.xyzx, l(2.99999993e-02, 2.99999993e-02, 2.99999993e-02, 0.00000000e+00)
mul r13.y, r7.z, r7.z
max r13.z, r13.y, l(1.00000005e-03)
ret
"""
# The same shader as Microsoft's D3DDisassemble prints it (the disassembler the game process uses on Windows): scalar
# swizzles replicated (r7.yyyy) and literals in fixed notation (0.030000). pbr-diag1 (2026-11-01): the tracer, tuned on
# Wine's output, found no albedo or metal in any live shader because of the replicated swizzle.
LIT_MS = """ps_5_0
dcl_resource_texture2d (float,float,float,float) t0
sample_indexable(texture2d)(float,float,float,float) r1.xyzw, v1.xyxx, t0.xyzw, s0
lt r2.x, r1.w, l(0.800000)
discard_nz r2.x
sample_indexable(texture2d)(float,float,float,float) r7.xyzw, v1.xyxx, t2.zxyw, s2
ne r0.x, l(0.000000), cb1[0].y
if_nz r0.x
  mov r7.y, cb1[5].y
endif
sample_indexable(texture2d)(float,float,float,float) r0.xyz, v1.xyxx, t3.xyzw, s3
add r0.xyz, r0.xyzx, l(-0.500000, -0.500000, -0.500000, 0.000000)
sample_indexable(texture2d)(float,float,float,float) r6.zw, v1.xyxx, t4.zwxy, s4
mad r6.zw, r6.zzzw, l(0.000000, 0.000000, 2.000000, 2.000000), l(0.000000, 0.000000, -1.000000, -1.000000)
sample_indexable(texture2d)(float,float,float,float) r9.x, v0.xyxx, t17.xyzw, s11
mul r1.xyz, r1.xyzx, r9.xxxx
add r7.zw, -r7.zzzy, l(0.000000, 0.000000, 1.000000, 1.000000)
mad r11.xyz, r1.xyzx, cb4[0].xyzx, l(-0.030000, -0.030000, -0.030000, 0.000000)
mad r11.xyz, r7.yyyy, r11.xyzx, l(0.030000, 0.030000, 0.030000, 0.000000)
mul r13.y, r7.z, r7.z
max r13.z, r13.y, l(0.001000)
ret
"""
# Terrain-style UVs (ps_550777957256): layers sampled at uv * cb1[5].xy / .zw; an offset-only coordinate and a
# transform written inside a branch must not be reported as a scale.
TERRAIN_UV = """ps_5_0
mad r6.xyzw, v2.xyzw, cb1[5].xyzw, cb3[1].xyxy
sample_indexable(texture2d) r7.xyzw, r6.xyxx, t0.xyzw, s0
sample_indexable(texture2d) r8.xyzw, r6.zwzz, t1.xyzw, s1
add r0.zw, v1.xxxy, cb3[1].xxxy
sample_indexable(texture2d) r9.xyzw, r0.zwzz, t2.xyzw, s2
if_nz r1.x
  mad r3.xy, v2.xyxx, cb1[6].xyxx, l(0.000000, 0.000000, 0.000000, 0.000000)
endif
sample_indexable(texture2d) r4.xyzw, r3.xyxx, t3.xyzw, s3
ret
"""
EFFECT = """ps_5_0
sample_indexable(texture2d) r1.xy, v3.xyxx, t4.xyzw, s4
sample_indexable(texture2d) r2.xyzw, r1.xyxx, t0.xyzw, s0
sample_indexable(texture2d) r0.x, v3.xyxx, t2.wxyz, s2
mul r0.y, r0.x, r0.x
mul r0.xyzw, r2.xyzw, v1.xyzw
mov_sat o0.w, r0.w
ret
"""
WANT_SYNTH = {'metal': {'slot': 2, 'channels': 'x'}, 'albedo': {'slot': 0, 'channels': 'xyz'},
              'gloss': {'slot': 2, 'channels': 'y', 'invert': True}, 'normal': {'slot': 3, 'channels': 'xyz'},
              'detail_normal': {'slot': 4, 'channels': 'xy'}}
MAIN = dict(WANT_SYNTH)
CHARACTER = {**WANT_SYNTH, 'metal': {'slot': 1, 'channels': 'x'}, 'gloss': {'slot': 1, 'channels': 'y', 'invert': True}}
REAL = {'lit/ps_1874571568': MAIN, 'lit/ps_1872570064': MAIN, 'lit/ps_1840406672': MAIN,
        'named/ps_550294968008': CHARACTER, 'named/ps_550384631240': {}}


def main():
    checks = []
    got = pbr_trace.roles(LIT)
    assert got == WANT_SYNTH, f'synthetic lit shader: {got}'
    checks.append('synthetic lit shader')
    got = pbr_trace.roles(LIT_MS)
    assert got == WANT_SYNTH, f"the same shader in Microsoft's disassembly format: {got}"
    checks.append("Microsoft disassembly format")
    uv = pbr_trace.roles(TERRAIN_UV).get('uv_scale')
    assert uv == {0: {'cb': 1, 'register': 5, 'lanes': 'xy'}, 1: {'cb': 1, 'register': 5, 'lanes': 'zw'}}, uv
    checks.append('terrain UV scale from constants; offset-only and branch-written coordinates refused')
    terrain = C.parent / 'runtime' / 'pbr-re' / 'paired_diag1' / 'wine' / 'ps_550777957256.asm'
    if terrain.exists():
        uv = pbr_trace.roles(terrain.read_text(errors='replace')).get('uv_scale', {})
        assert uv.get(0) == {'cb': 1, 'register': 5, 'lanes': 'xy'} and uv.get(1) == {'cb': 1, 'register': 5, 'lanes': 'zw'} \
            and uv.get(2) == {'cb': 1, 'register': 6, 'lanes': 'xy'}, uv
        checks.append('real terrain shader: layers 0/1/2 at cb1[5].xy, cb1[5].zw, cb1[6].xy')
    assert pbr_trace.roles(EFFECT) == {}, f'an effects shader was given material roles: {pbr_trace.roles(EFFECT)}'
    checks.append('effects shader has no material roles')
    real = C.parent / 'runtime' / 'pbr-re'
    present = [k for k in REAL if (real / f'{k}.asm').exists()]
    for k in present:
        got = pbr_trace.roles((real / f'{k}.asm').read_text(errors='replace'))
        assert got == REAL[k], f'{k}: {got} != {REAL[k]}'
    checks.append(f'{len(present)}/{len(REAL)} hand-traced game shaders')
    print(json.dumps({'passed': True, 'checks': checks}))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except AssertionError as e:
        print(json.dumps({'passed': False, 'error': str(e)}))
        sys.exit(1)
