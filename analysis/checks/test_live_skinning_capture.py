#!/usr/bin/env python3
"""Wine mock gate: CPU skinning updates with CB11 and keeps two simultaneous poses of shared geometry distinct.

Key rule (changed 2026-10-30): a skinned mesh is keyed by its draw and its occurrence in the frame, not by its pose.
Keying by pose made every animation frame a new mesh: live 2026-10-29 built ~29 meshes per Remix frame and evicted
56915 of 59917, which is the churn behind the falling fps. Two characters drawn in one frame must still get two keys;
a new pose must replace the mesh under the same key.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
A = C.parent
OUT = A / 'runtime/live-skinning-capture'
import test_live_geometry as tg
tr, tmo, ts = tg.tr, tg.tmo, tg.ts
tr.ENV_KEYS = tuple(tr.ENV_KEYS) + ('MOCK_SKIN_SPLIT', 'MOCK_SKIN_ANIMATE')


def inside():
    work = Path(tempfile.mkdtemp(prefix='run-', dir=OUT))
    try:
        tmo.build(work)
        subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-shared',
                        '-static', '-static-libgcc', '-static-libstdc++', '-isystem', str(A / 'remix-probe/vendor'),
                        str(C / 'remix_live_fake_runtime.cpp'), '-ld3d9', '-o', str(work / 'fake_remix.dll')], check=True)
        scene = work / 'scene'
        (scene / 'scene_textures').mkdir(parents=True)
        (scene / 'scene.bin').write_bytes(ts.scene_bytes(ts.CAMERA, ts.DRAWS, ts.TEXTURES, ts.TRIS))
        tex = work / 'textures'
        tex.mkdir()
        base = {'NIER_REMIX_RUNTIME': tr.win(work / 'fake_remix.dll'),
            'NIER_REMIX_SCENE': tr.win(scene / 'scene.bin'), 'MOCK_FRAME_MS': '40', 'MOCK_CAMERA': 'live-skin-poses',
            'NIER_REMIX': '1', 'NIER_REMIX_LIVE': '1', 'NIER_REMIX_LIVE_TEX': tr.win(tex), 'FAKE_REMIX_INSTANCE_LOG': '1'}
        rigid_base = dict(base)
        # The bake cases below need a mesh that really blends bones; a one-bone mesh now takes the rigid path.
        base = {**base, 'MOCK_SKIN_SPLIT': '1'}
        _, r, log, fake = tr.run(work, 'poses', base)
        assert fake and 'VIOLATION' not in fake, (fake or log)[-2000:]
        meshes = [l for l in fake.splitlines() if l.startswith('CreateMesh') and 'indices=192 ' in l]
        assert meshes and all('skinned=0 ' in l for l in meshes), 'GPU skinning data still submitted: ' + str(meshes[:2])
        by_pose = {}
        for l in meshes:
            x = float(re.search(r'v0=([-\d.]+),', l).group(1))
            by_pose.setdefault(x, set()).add(re.search(r'key=(\d+)', l).group(1))
        assert set(by_pose) == {0, 10, 20, 30}, f'pose updates or simultaneous characters lost: {by_pose}'
        assert all(len(h) == 1 for h in by_pose.values()), f'one pose built under several keys: {by_pose}'
        first, second = by_pose[0] | by_pose[10], by_pose[20] | by_pose[30]
        assert len(first) == 1 and len(second) == 1, f'a pose change made a new key instead of replacing: {by_pose}'
        assert first != second, 'two characters drawn in one frame share a mesh key'
        assert len(meshes) <= 5, f'unchanged poses rebuilt every frame: {len(meshes)}'
        draws = [l for l in fake.splitlines() if l.startswith('DrawInstance')]
        assert draws and all('bones=0 ' in l and 'row0=1.000,0.000,0.000,0.000' in l for l in draws), 'double transform/GPU palette'
        assert int(r['geometry_reads']) <= 3, f'CPU skinning introduced per-frame geometry readback: {r}'

        # Animated: both characters change pose every frame. The resident set must stay at two keys, each always
        # holding the same character (vertex 0 follows bone 0: x < 20 is the first character, x > 20 the second).
        tex_anim = work / 'textures-animate'
        tex_anim.mkdir()
        _, r, log, fake = tr.run(work, 'animate', {**base, 'NIER_REMIX_LIVE_TEX': tr.win(tex_anim), 'MOCK_SKIN_ANIMATE': '1',
                                                   'NIER_REMIX_LIVE_STATS_EVERY': '10'})
        assert fake and 'VIOLATION' not in fake, (fake or log)[-2000:]
        animated = [l for l in fake.splitlines() if l.startswith('CreateMesh') and 'indices=192 ' in l]
        side = {}
        for l in animated:
            x = float(re.search(r'v0=([-\d.]+),', l).group(1))
            side.setdefault(re.search(r'key=(\d+)', l).group(1), set()).add(x > 20)
        assert len(animated) >= 20, f'poses were not rebuilt while animating: {len(animated)} builds'
        assert len(side) == 2, f'animated characters made {len(side)} mesh keys, expected 2'
        assert all(len(s) == 1 for s in side.values()), f'a key switched between characters: {side}'
        # Animation with unchanged buffers is a pose rebuild, not a buffer write: the live laptop picture popped while
        # meshes were rebuilt constantly, and this counter is how the cause is told apart (rebuild reasons line).
        why_lines = [x for x in tr.remix_lines(log) if x.startswith('remix: live rebuilds ')]
        assert why_lines, tr.remix_lines(log)[-6:]
        why = {k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', why_lines[-1])}
        assert why['pose'] >= 10 and why['pose'] > why['buffer'], f'animation not counted as pose rebuilds: {why}'
        # Rigid: every vertex on bone 0 (NieR draws most of its static world like this, 2026-10-30). Two characters share
        # VB/IB and get different bone-0 translations (0/10 and 20/30). They must share one mesh built in its own space,
        # with the bone as the instance transform -- not a rebuild per pose or per draw order.
        rigid_counts = {}
        for name, extra in (('rigid-poses', {}), ('rigid-animate', {'MOCK_SKIN_ANIMATE': '1'})):
            tex_r = work / f'textures-{name}'
            tex_r.mkdir()
            _, r, log, fake = tr.run(work, name, {**rigid_base, 'NIER_REMIX_LIVE_TEX': tr.win(tex_r), **extra,
                                                  'NIER_REMIX_LIVE_STATS_EVERY': '10'})
            assert fake and 'VIOLATION' not in fake, (fake or log)[-2000:]
            built = [l for l in fake.splitlines() if l.startswith('CreateMesh') and 'indices=192 ' in l]
            assert built and len(built) <= 4, f'{name}: a rigid skinned mesh was rebuilt {len(built)} times'
            rigid_mesh = [l for l in built if re.search(r'v0=0\.000,', l)]
            assert rigid_mesh, f'{name}: no mesh in its own space (v0 at the origin): {built}'
            per_frame = {}
            for l in fake.splitlines():
                if not l.startswith('DrawInstance'):
                    continue
                m = re.search(r'presented=(\d+) mesh=(\d+) .*row0=([-\d.]+),[-\d.]+,[-\d.]+,([-\d.]+)', l)
                if m and int(m.group(1)) >= 10:
                    per_frame.setdefault(int(m.group(1)), []).append((m.group(2), float(m.group(4))))
            assert len(per_frame) >= 30, f'{name}: rigid instances not drawn: {len(per_frame)} frames'
            firsts = []
            for f in sorted(per_frame):
                inst = per_frame[f]
                xs = sorted(x for _, x in inst)
                assert len(inst) >= 2 and len({mesh for mesh, _ in inst}) == 1, f'{name} frame {f}: {inst}'
                assert abs((xs[-1] - xs[0]) - 20.0) < 1e-3, f'{name} frame {f}: the two characters are not 20 apart: {xs}'
                firsts.append(xs[0])
            if name == 'rigid-poses':
                # The mock switches the pose once (0 -> 10); presented frames trail mock frames, so only the values count.
                assert set(round(x, 3) for x in firsts) == {0.0, 10.0}, f'{name}: translations seen {sorted(set(firsts))}'
            else:
                steps = {round(b - a, 3) for a, b in zip(firsts, firsts[1:])}
                assert steps <= {0.25, 0.5, 0.75}, f'{name}: transform does not follow the animation: steps {sorted(steps)}'
            why = {k: int(v) for k, v in re.findall(r'(\w+)=(\d+)',
                   [x for x in tr.remix_lines(log) if x.startswith('remix: live rebuilds ')][-1])}
            assert why['pose'] <= 2, f'{name}: rigid skinned draws still rebuild per pose: {why}'
            rigid_counts[name] = len(built)
        gpu_bone = {}

        # Phase 4: a blended skinned mesh is built ONCE in bind space and moved by per-frame bone transforms, so a pose
        # costs an instance update instead of a mesh rebuild (82% of the rebuilds measured live were `pose`).
        # Three weight slots per vertex is the only layout the runtime reads exactly (UPSTREAM_SKINNING_STRIDE.md).
        for name, extra in (('gpu-bone-poses', {}), ('gpu-bone-animate', {'MOCK_SKIN_ANIMATE': '1'})):
            tex_g = work / f'textures-{name}'
            tex_g.mkdir()
            _, r, log, fake = tr.run(work, name, {**base, 'NIER_REMIX_LIVE_GPU_SKIN': '1',
                                                  'NIER_REMIX_LIVE_TEX': tr.win(tex_g), **extra})
            assert fake and 'VIOLATION' not in fake, (fake or log)[-2000:]
            built = [l for l in fake.splitlines() if l.startswith('CreateMesh') and 'indices=192 ' in l]
            assert len(built) == 1, f'{name}: a pose must not rebuild the mesh, saw {len(built)} builds'
            mesh = built[0]
            assert 'skinned=1 ' in mesh and 'bonesPerVertex=4 ' in mesh, mesh
            verts = int(re.search(r'verts=(\d+)', mesh).group(1))
            weights = int(re.search(r'weights=(\d+)', mesh).group(1))
            # verts is the padded 3V; three weights per real vertex plus the 4-float tail the probe proved on 1.6.1.
            assert weights == verts + 4, f'{name}: expected the proven 3V+4 weight layout, {weights} for {verts} slots'
            assert 'v0=0.000,0.000,0.500' in mesh, f'{name}: mesh is not in bind space, it was baked: {mesh}'
            draws = [l for l in fake.splitlines() if l.startswith('DrawInstance')]
            assert len(draws) >= 30, f'{name}: only {len(draws)} frames drawn'
            assert all('bones=0 ' not in l for l in draws), f'{name}: no bone transforms reached the instance'
            bones = [l for l in fake.splitlines() if l.startswith('Bones count=')]
            assert bones, f'{name}: the runtime never saw a bone palette'
            # Bone 0's translation is the fourth field of row 0. One Bones line follows each DrawInstance, which carries
            # presented=, and every frame draws both characters: group per frame and take the first palette, so the steps
            # below are the animation's own and not the 20 the mock puts between the two actors.
            per_frame, presented = {}, None
            for l in fake.splitlines():
                m = re.match(r'DrawInstance presented=(\d+)', l)
                if m:
                    presented = int(m.group(1))
                elif l.startswith('Bones count='):
                    pal = [float(x) for x in re.findall(r'b[01]=[-\d.]+,[-\d.]+,[-\d.]+,([-\d.]+)', l)]
                    assert presented is not None and len(pal) == 2, f'{name}: no b0/b1 palette on frame {presented}: {l}'
                    per_frame.setdefault(presented, []).append((pal[0], pal[1]))
            frames = [v for _, v in sorted(per_frame.items())]
            assert frames and all(len(p) == 2 for p in frames), f'{name}: both characters were not drawn: {len(frames)} frames'
            assert {round(b1, 3) for p in frames for _, b1 in p} == {5.0}, f'{name}: bone 1 is not the palette\'s own'
            assert {round(p[1][0] - p[0][0], 3) for p in frames} == {20.0}, f'{name}: the two characters shared a palette'
            xs = [p[0][0] for p in frames]
            if name == 'gpu-bone-poses':
                assert set(round(x, 3) for x in xs) == {0.0, 10.0}, f'{name}: bone 0 does not follow the pose: {sorted(set(xs))}'
            else:
                steps = {round(b - a, 3) for a, b in zip(xs, xs[1:])}
                assert steps <= {0.25, 0.5, 0.75}, f'{name}: bone 0 does not follow the animation: {sorted(steps)}'
            assert int(r['geometry_reads']) <= 3, f'{name}: GPU skinning must not read geometry back: {r}'
            gpu_bone[name] = f'{len(draws)} frames, {len(bones)} palettes, {verts} vertices -> {weights} weights, one mesh'
        report = {'passed': True, 'work': str(work), 'poses': sorted(by_pose), 'meshes': len(meshes),
                  'animated_builds': len(animated), 'animated_keys': len(side), 'rigid_builds': rigid_counts, 'gpu_bone': gpu_bone,
                  'limits': 'Real proxy in a software Wine mock, not the real Remix runtime or live game.'}
        (OUT / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report))
    except Exception as exc:
        (OUT / 'validation.json').write_text(json.dumps({'passed': False, 'work': str(work), 'error': str(exc)[-2200:]}) + '\n')
        raise
    finally:
        subprocess.run(['wineserver', '-k'], env=os.environ, capture_output=True)


def main():
    if sys.argv[1:] == ['--inside']:
        return inside()
    for name in ('prefix', 'home', 'cache', 'xdg'):
        (OUT / name).mkdir(parents=True, exist_ok=True)
    (OUT / 'xdg').chmod(0o700)
    assert not (OUT / 'prefix').is_symlink()
    env = os.environ.copy()
    for k in tr.ENV_KEYS:
        env.pop(k, None)
    env.update(WINEPREFIX=str(OUT / 'prefix'), HOME=str(OUT / 'home'), XDG_CACHE_HOME=str(OUT / 'cache'),
        XDG_RUNTIME_DIR=str(OUT / 'xdg'), WINEDEBUG='-all', WAYLAND_DISPLAY='', LIBGL_ALWAYS_SOFTWARE='1',
        GALLIUM_DRIVER='llvmpipe', WINEDLLOVERRIDES='d3d11=n,b;winemenubuilder.exe=d;mscoree,mshtml=')
    subprocess.run(['xvfb-run', '-a', '-s', '-screen 0 1920x1080x24', sys.executable, str(Path(__file__).resolve()), '--inside'],
                   cwd=OUT, env=env, check=True)


if __name__ == '__main__':
    main()
