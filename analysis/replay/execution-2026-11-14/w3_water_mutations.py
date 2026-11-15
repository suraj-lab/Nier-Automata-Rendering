#!/usr/bin/env python3
"""W3 step 2 mutation run: each patch must make checks/test_live_water.py fail, and each file is restored byte-identically
(SHA-256 before/after). 'native' scope runs only the classifier/material harness; 'full' runs the whole gate."""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

A = Path('/home/suraj/Projects/Nier-Automata-Rendering/analysis')
C = A / 'checks'
sys.path.insert(0, str(C))

MUTATIONS = [
    ('water_class.h', 'classify every blend as water (the plan\'s mutation)',
     '    if (!d.albedo) return kNoAlbedo;\n    if (!d.translucent_declared) return kNoTranslucentDecl;\n    return kWater;',
     '    if (!d.albedo) return kNoAlbedo;\n    return kWater;', 'native'),
    ('water_class.h', 'accept an alpha-tested card (foliage, hair)',
     '    if (d.alpha_test) return kAlphaTested;\n', '', 'native'),
    ('water_class.h', 'accept a skinned draw (hair)',
     '    if (d.skinned) return kSkinned;\n', '', 'native'),
    ('water_class.h', 'accept a non-alpha blend state (additive, ONE/ZERO)',
     '    if (d.alpha_to_coverage || d.op != kD3D11BlendOpAdd || d.src != kD3D11BlendSrcAlpha || d.dst != kD3D11BlendInvSrcAlpha)\n        return kBlendNotAlpha;\n',
     '    if (d.op == 99) return kBlendNotAlpha;\n', 'native'),
    ('water_class.h', 'accept a draw with no albedo', '    if (!d.albedo) return kNoAlbedo;\n', '', 'native'),
    ('water_class.h', 'accept a sky draw', '    if (d.sky) return kSky;\n', '', 'native'),
    ('live_scene.h', 'retain the forced cutout on selected water (the plan\'s mutation)',
     'if (item.blended && !blend_chain && !item.water)', 'if (item.blended && !blend_chain)', 'full'),
    ('live_scene.h', 'drop the ANIMATED_WATER category bit',
     '            if (item.water && !s.bare.count(item.geometry))\n                instance.categoryFlags |= REMIXAPI_INSTANCE_CATEGORY_BIT_ANIMATED_WATER;\n',
     '', 'full'),
    ('live_scene.h', 'send the material without its translucent extension',
     '        ext.pNext = &trans;', '        ext.pNext = nullptr;', 'full'),
    ('live_scene.h', 'let a water material share the cutout material\'s hash',
     '    if (water) hash = hash * 0x9e3779b97f4a7c15ull ^ 0x77617465725f6d61ull;\n', '', 'full'),
    ('live_scene.h', 'let a water material be the cutout material itself',
     '    if (water) key = key * 0x9e3779b97f4a7c15ull ^ 0x77617465725f6d61ull;\n', '', 'full'),
    ('live_scene.h', 'a guessed refractive index', '        trans.refractiveIndex = 1.33f;', '        trans.refractiveIndex = 1.30f;', 'full'),
    ('live_scene.h', 'drop the diffuse layer', '        trans.useDiffuseLayer = 1;', '        trans.useDiffuseLayer = 0;', 'full'),
    ('live_scene.h', 'refresh a water material as a cutout one',
     '                     m.draw_call_alpha, m.water);', '                     m.draw_call_alpha, false);', 'native'),
    ('live_capture.h', 'treat the declaration as always present',
     '      water_input.translucent_declared = pixel.water_decl;', '      water_input.translucent_declared = true;', 'full'),
    ('live_capture.h', 'skip the classifier for every blended draw',
     'const bool water_draw = water_on && !ui_pass && water_class::water(water_input);',
     'const bool water_draw = water_on && !ui_pass && draw_blend.enable;', 'full'),
    ('live_capture.h', 'drop the water geometry key',
     '        geometry = hash_value(geometry ^ 0x77617465725f7375ull);   // "water_su": its own mesh key\n', '', 'full'),
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_native():
    import importlib
    import test_live_water as t
    importlib.reload(t)
    try:
        t.native(Path(tempfile.mkdtemp(prefix='mut-native-', dir=A / 'runtime')))
    except AssertionError as e:
        return False, str(e).splitlines()[-1][:200]
    return True, 'the harness stayed green'


def run_full():
    p = subprocess.run(['python3', 'checks/test_live_water.py'], cwd=A, capture_output=True, text=True,
                       env={**__import__('os').environ, 'TMPDIR': str(A / 'runtime/tmp')})
    tail = (p.stdout + p.stderr).strip().splitlines()
    return p.returncode == 0, (tail[-1] if tail else '')[:200]


def main():
    report = []
    for fname, what, old, new, scope in MUTATIONS:
        path = C / fname
        before = sha(path)
        text = path.read_text()
        assert text.count(old) == 1, f'{fname}: mutation target appears {text.count(old)}x: {what}'
        path.write_text(text.replace(old, new, 1))
        try:
            green, detail = run_native() if scope == 'native' else run_full()
        finally:
            path.write_text(text)
        after = sha(path)
        assert before == after, f'{fname}: NOT restored byte-identically'
        report.append({'file': fname, 'mutation': what, 'scope': scope, 'gate_green': green,
                       'evidence': detail, 'restored_sha256': after})
        print(f'{"RED " if not green else "GREEN!"} {fname}: {what} [{scope}] -> {detail}')
    out = A / 'runtime/live-water/mutations.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1) + '\n')
    bad = [r for r in report if r['gate_green']]
    print(f'{len(report)} mutations, {len(bad)} did not fail the gate')
    if bad:
        for r in bad:
            print('  stayed green:', r['file'], r['mutation'])
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
