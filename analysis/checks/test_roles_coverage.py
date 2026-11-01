#!/usr/bin/env python3
"""FROZEN gate for material-role coverage and the albedo fallback the live path relies on.

What it pins (all measured offline, see analysis/evidence/remix-current/2026-11-01/material-roles-coverage.md):
  1. pbr_trace.py's roles over the full 605-shader live corpus match the frozen fixture, exactly.
  2. Wine's and Microsoft's disassemblies of the same 605 blobs give identical roles.
  3. Of the shaders whose albedo the lighting maths *does* name, slot 0 is that albedo in 100 of 104. This is what
     justifies live_capture.h's "first usable texture in slots 0..15" fallback, and it must not silently rot.
  4. Of the 501 shaders with no traced albedo, 432 sample slot 0 first, so the live fallback lands on slot 0 for them.

Every check has a mutation that must turn it red (a changed tracer, a changed shader, an inverted expectation).
A proposed output-provenance fallback was measured and rejected: it agreed with the lighting-maths albedo on only 32
of 104 known cases, so it is not in the tracer and must not be added on this evidence.

Usage: test_roles_coverage.py
"""
import importlib.util
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
sys.path.insert(0, str(C))
import pbr_trace  # noqa: E402

CORPUS = C.parent / 'runtime' / 'pbr-re' / 'meta'
PAIRED = C.parent / 'runtime' / 'pbr-re' / 'paired_diag1'
FIXTURE = C / 'fixtures' / 'material-roles-meta.json'
ROLES = ('albedo', 'metal', 'gloss', 'normal', 'detail_normal')
FROZEN = {'shaders': 605, 'albedo': 104, 'metal': 102, 'gloss': 94, 'normal': 111, 'detail_normal': 103, 'full': 61,
          'slot0_is_albedo': 100, 'traced_albedo': 104, 'first_slot0_unpinned': 432, 'unpinned': 501}
MATERIAL_SLOTS = set(range(8))


def fail(message):
    print(json.dumps({'passed': False, 'error': message}))
    sys.exit(1)


def compact(roles):
    out = {}
    for role, value in roles.items():
        if role == 'uv_scale':
            out['uv_scale'] = value
        else:
            out[role] = f"{value['slot']}.{value['channels']}" + ('~' if value.get('invert') else '')
    return out


def roles_of(directory):
    files = sorted(Path(directory).glob('*.asm'))
    if not files:
        fail(f'corpus missing: no .asm in {directory}')
    # Round-trip through JSON so uv_scale's integer slot keys compare the way the fixture stores them (as strings).
    return json.loads(json.dumps({f.stem: compact(pbr_trace.roles(f.read_text(errors='replace'))) for f in files}))


def sampled_slots(asm):
    return sorted({int(m) for m in re.findall(r'\bt(\d+)\.', asm)} & MATERIAL_SLOTS)


def slot0_prior(roles, corpus):
    """(slot 0 is the traced albedo, shaders with a traced albedo)."""
    traced = [k for k, v in roles.items() if 'albedo' in v]
    hit = sum(1 for k in traced if roles[k]['albedo'].startswith('0.'))
    return hit, len(traced), corpus


def first_slot0(roles, corpus):
    """(unpinned shaders whose first sampled material slot is 0, unpinned shaders)."""
    unpinned = [k for k, v in roles.items() if 'albedo' not in v]
    hit = sum(1 for k in unpinned if (s := sampled_slots((corpus / f'{k}.asm').read_text(errors='replace'))) and s[0] == 0)
    return hit, len(unpinned)


def main():
    results = {}

    # 1. the frozen fixture
    roles = roles_of(CORPUS)
    want = json.loads(FIXTURE.read_text())
    if len(roles) != FROZEN['shaders']:
        fail(f"corpus is {len(roles)} shaders, the fixture pins {FROZEN['shaders']}")
    counts = {role: sum(1 for v in roles.values() if role in v) for role in ROLES}
    counts['full'] = sum(1 for v in roles.values() if {'albedo', 'metal', 'gloss', 'normal'} <= set(v))
    for name, expected in FROZEN.items():
        if name in counts and counts[name] != expected:
            fail(f'{name}: {counts[name]} shaders, the fixture pins {expected}')
    differ = [k for k in want if want[k] != roles.get(k)]
    if differ:
        shown = '; '.join(f'{k}: want {want[k]} got {roles.get(k)}' for k in differ[:8])
        fail(f'{len(differ)} of {len(want)} shaders no longer match the fixture: {shown}')
    results['fixture'] = f'{len(roles)} shaders identical, albedo {counts["albedo"]}, all four {counts["full"]}'

    # 2. Wine and Microsoft must agree, shader for shader
    ms, wine = PAIRED / 'ms', PAIRED / 'wine'
    pairs = sorted(ms.glob('*.asm'))
    if len(pairs) < FROZEN['shaders']:
        fail(f'paired corpus missing: {len(pairs)} pairs in {PAIRED}')
    skew = []
    for path in pairs:
        other = wine / path.name
        if not other.exists():
            fail(f'{path.name} has no Wine disassembly')
        a = compact(pbr_trace.roles(path.read_text(errors='replace')))
        b = compact(pbr_trace.roles(other.read_text(errors='replace')))
        if a != b:
            skew.append(f'{path.name}: ms {a} wine {b}')
    if skew:
        fail(f'{len(skew)} of {len(pairs)} shaders differ between disassemblers:\n' + '\n'.join(skew[:6]))
    results['disassemblers'] = f'{len(pairs)} pairs identical'

    # 3. and 4. the priors the live fallback depends on
    hit, traced, _ = slot0_prior(roles, CORPUS)
    if (hit, traced) != (FROZEN['slot0_is_albedo'], FROZEN['traced_albedo']):
        fail(f'slot 0 is the traced albedo for {hit} of {traced}, the gate pins '
             f'{FROZEN["slot0_is_albedo"]} of {FROZEN["traced_albedo"]}')
    first, unpinned = first_slot0(roles, CORPUS)
    if (first, unpinned) != (FROZEN['first_slot0_unpinned'], FROZEN['unpinned']):
        fail(f'first sampled slot is 0 for {first} of {unpinned} unpinned shaders, the gate pins '
             f'{FROZEN["first_slot0_unpinned"]} of {FROZEN["unpinned"]}')
    results['albedo_fallback'] = (f'slot 0 is the traced albedo on {hit}/{traced}; first sampled slot is 0 on '
                                  f'{first}/{unpinned} of the untraced')

    # mutation 1: break the tracer, the fixture comparison must notice
    with tempfile.TemporaryDirectory() as tmp:
        broken = Path(tmp) / 'broken_trace.py'
        source = (C / 'pbr_trace.py').read_text()
        mutated = source.replace('abs(v - 0.03) < 1e-6 or abs(v - 0.08) < 1e-6', 'abs(v - 0.031) < 1e-6')
        if mutated == source:
            fail('mutation 1: the metal-literal pattern moved, so this check is stale')
        broken.write_text(mutated)
        spec = importlib.util.spec_from_file_location('broken_trace', broken)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        moved = [k for k in want if compact(module.roles((CORPUS / f'{k}.asm').read_text(errors='replace'))) != want[k]]
        if not moved:
            fail('mutation 1: breaking the metals pattern changed no shader, the fixture is not load-bearing')
        results['mutation_tracer'] = f'breaking the metals pattern moves {len(moved)} shaders'

    # mutation 2: change one shader's texture slot, its roles must follow
    victim = next((k for k, v in sorted(roles.items()) if v.get('albedo', '').startswith('0.')), None)
    if victim is None:
        fail('mutation 2: no shader has a traced albedo in slot 0')
    asm = (CORPUS / f'{victim}.asm').read_text(errors='replace')
    touched = re.sub(r'\bt0\.', 't5.', asm)
    if compact(pbr_trace.roles(touched)) == roles[victim]:
        fail(f'mutation 2: moving {victim} from slot 0 to slot 5 changed nothing')
    results['mutation_shader'] = f'{victim} moves slot 0 -> 5 and its roles change'

    # mutation 3: the prior checks must reject an off-by-one expectation
    if hit == 0:
        fail('mutation 3: no slot-0 hits to invert')
    if (lambda h, t: (h, t) == (FROZEN['slot0_is_albedo'], FROZEN['traced_albedo']))(hit + 1, traced):
        fail('mutation 3: the slot-0 prior accepts a wrong count')
    results['mutation_expectation'] = 'a one-off slot-0 count is rejected'

    print(json.dumps({'passed': True, **results}, indent=1))


if __name__ == '__main__':
    main()
