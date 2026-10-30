#!/usr/bin/env python3
"""Live-scene gate: the game's per-frame draw stream becomes the Remix scene, in the real proxy DLL.

Same isolated Wine/Xvfb/llvmpipe harness as test_live_camera.py. The mock game draws a moving mesh from a
DYNAMIC vertex buffer every frame (content changes once at frame 50), adds a second mesh from DEFAULT buffers
at frame 40, writes the world matrix into VS CB11 through Map, and binds one material texture.

What this gate actually pins (it fails on the obvious wrong implementations):
  - one Remix mesh per geometry key, not one per frame;
  - meshes rebuilt when a shadowed buffer is written (frame 50) and not otherwise;
  - DrawInstance transforms that follow CB11 every frame;
  - no vertex/index readback at all for buffers the game wrote through Map, and none late in the run;
  - no per-frame constant-buffer readback for world matrices (camera_reads stays ~1 per frame);
  - exactly one DDS and one material for one texture;
  - the live camera still arrives while the scene is live, and leaving NIER_REMIX_LIVE unset is unchanged.
Software mocks only: this is not evidence about real NieR draws, materials or playability.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

C = Path(__file__).resolve().parent
A = C.parent
OUT = A / 'runtime/live-geometry'
import test_remix_live as tr
import test_menu_overlay as tmo
import test_nscn_scene as ts

tr.ENV_KEYS = tuple(tr.ENV_KEYS) + ('NIER_REMIX_LIVE', 'NIER_REMIX_LIVE_TEX', 'NIER_REMIX_LIVE_BUDGET',
                                     'NIER_REMIX_LIVE_BUDGET_KB', 'NIER_REMIX_LIVE_SHADOW_KB', 'NIER_REMIX_LIVE_EXPIRE_FRAMES', 'NIER_REMIX_LIVE_FAIL_VB_READS', 'NIER_REMIX_LIVE_MAX_WRITE_KB', 'NIER_REMIX_LIVE_READ_BUDGET_KB',
                                     'FAKE_REMIX_INSTANCE_LOG', 'MOCK_LIVE_SPENDER_FROM', 'MOCK_LIVE_REWRITE_SAME')


CUTOUT = 1 << 15


def world_meshes(fake):
    """CreateMesh lines for world geometry: the background shell (|x| in the tens of thousands) is excluded."""
    out = []
    for line in fake.splitlines():
        if not line.startswith('CreateMesh'):
            continue
        m = re.search(r'v0=([-\d.]+),', line)
        if m and abs(float(m.group(1))) > 5000:
            continue
        out.append(line)
    return out

def inside():
    work = Path(tempfile.mkdtemp(prefix='run-', dir=OUT))
    results = {}
    try:
        tmo.build(work)
        subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-shared',
                        '-static', '-static-libgcc', '-static-libstdc++', '-isystem', str(A / 'remix-probe/vendor'),
                        str(C / 'remix_live_fake_runtime.cpp'), '-ld3d9', '-o', str(work / 'fake_remix.dll')], check=True)
        scene = work / 'scene'
        (scene / 'scene_textures').mkdir(parents=True)
        (scene / 'scene.bin').write_bytes(ts.scene_bytes(ts.CAMERA, ts.DRAWS, ts.TEXTURES, ts.TRIS))
        tex = work / 'live-textures'
        tex.mkdir()
        base = {'NIER_REMIX_RUNTIME': tr.win(work / 'fake_remix.dll'), 'NIER_REMIX_SCENE': tr.win(scene / 'scene.bin'),
                'MOCK_FRAME_MS': '40', 'MOCK_CAMERA': 'live'}
        on = {**base, 'NIER_REMIX': '1', 'NIER_REMIX_LIVE': '1', 'NIER_REMIX_LIVE_TEX': tr.win(tex),
              'FAKE_REMIX_INSTANCE_LOG': '1', 'FAKE_REMIX_CAMERA_LOG': '1'}
        off = {'MOCK_CAMERA': 'live'}

        _, r, log, fake = tr.run(work, 'off', off)
        assert fake is None and r['geometry_reads'] == '0' and r['camera_reads'] == '0', r
        assert not list(tex.iterdir()), 'Remix off must not capture textures.'
        # Normal launches: the write hooks must be pure pass-through. A boxed UpdateSubresource whose source ends at
        # a guard page crashes a hook that over-reads, and a never-bound buffer must not gain a reference.
        _, r, log, fake = tr.run(work, 'off-box', {'MOCK_CAMERA': 'live-box'})
        assert fake is None and r['unbound_refs'] == '1', f'Remix off holds a reference on a game buffer: {r}'
        results['off'] = 'Remix off: no readback, no textures, no buffer references, boxed updates pass through untouched.'

        d, r, log, fake = tr.run(work, 'live', on)
        assert fake and 'VIOLATION' not in fake, fake
        assert not any('disabled' in x for x in tr.remix_lines(log)), log
        # Static, IMMUTABLE and Map-written buffers: at most one read each, none for the dynamic mesh.
        assert int(r['geometry_reads']) <= 6, f'geometry readback crept in: {r}'  # one per unique static buffer
        assert r['geometry_reads_late'] == '0', f'geometry readback per frame: {r}'
        assert int(r['camera_reads']) <= 90, f'world matrices must come from the Map shadow, not readback: {r}'
        results['readback'] = 'No per-frame vertex/index/CB readback; dynamic mesh came from the Map shadow.'

        # The sky dome is now a mesh too (submitted with the SKY category); it is not part of the world-geometry
        # assertions below, so it is filtered out here rather than polluting them.
        meshes = [dict(kv.split('=', 1) for kv in re.findall(r'(\w+=\S+)', x)) for x in world_meshes(fake)]
        assert meshes, fake
        early = [m for m in meshes if int(m['presented']) < 35]
        mid = [m for m in meshes if 35 <= int(m['presented']) < 48]
        late = [m for m in meshes if int(m['presented']) >= 48]
        assert len(early) == 1, f'mesh A must be built once, not per frame: {early[:3]}'
        assert len(mid) == 1, f'mesh B built when it first appears: {[m["presented"] for m in mid]}'
        assert len(late) == 1, f'mesh A rebuilt once after its dynamic content changed: {[m["presented"] for m in late]}'
        assert all(int(m['indices']) == 192 for m in meshes), [m['indices'] for m in meshes]
        # Only the referenced vertices may be uploaded: 65 for this fan, not 192*3.
        assert all(int(m['verts']) <= 65 for m in meshes), [m['verts'] for m in meshes]
        results['meshes'] = 'One indexed mesh per geometry key; rebuilt only when a shadowed buffer was written.'

        draws = [x for x in fake.splitlines() if x.startswith('DrawInstance')]
        assert draws, 'Live scene must draw instances every frame.'
        row0 = []
        for match in re.findall(r'row0=([-\d.]+),([-\d.]+),([-\d.]+),([-\d.]+)', '\n'.join(draws)):
            try:
                row0.append(tuple(float(v) for v in match))
            except ValueError:
                continue
        translations = {f'{m[3]:.3f}' for m in row0 if (m[0], m[1], m[2]) == (1.0, 0.0, 0.0)}
        for f in ('40.000', '79.000'):
            assert f in translations, f'DrawInstance transform must follow CB11 every frame: missing {f}'
        results['transforms'] = 'DrawInstance world matrices follow the live CB11 values each frame.'

        mats = [x for x in fake.splitlines() if x.startswith('CreateMaterial')]
        assert len(mats) == 1 and '.dds' in mats[0], mats
        files = list(tex.iterdir())
        assert len(files) == 1 and files[0].suffix == '.dds' and files[0].stat().st_size > 148, files
        results['material'] = 'One texture written once and one material created for it.'

        poses = re.findall(r'Camera pos=([-\d.,]+)', fake)
        assert '10.000,2.000,30.000' in poses and '40.000,5.000,60.000' in poses, poses[:5]
        assert tmo.near(tr.rgb((d / 'capture-after.raw').read_bytes(), *tr.PROBE), tr.REMIX), 'Remix output lost'
        results['camera'] = 'Live camera still reaches SetupCamera while the scene is live.'
        # Independent review (2026-10-28): three draws in this run must never become meshes, and the game's CB11 must
        # not gain references while it keeps being drawn (the sky draw takes an early-return path every frame).
        for indices in ('186', '183', '180'):
            assert not any(f'indices={indices} ' in x for x in fake.splitlines() if x.startswith('CreateMesh')), \
                f'{indices}-index draw (zero instances / triangle strip / null slot) became a mesh'
        assert r['cb11_refs_20'] == r['cb11_refs_79'], f'CB11 references leak per draw: {r}'
        results['review'] = 'Zero-instance, strip and null-slot draws make no mesh; no CB11 reference leak.'

        # Skinned draws are CPU-baked: the actual runtime's weight stride corrupts four-weight API meshes.
        tex2 = work / 'live-textures-skinned'
        tex2.mkdir()
        _, r, log, fake = tr.run(work, 'skinned', {**base, 'MOCK_CAMERA': 'live-skinned', 'NIER_REMIX': '1',
                                                   'NIER_REMIX_LIVE': '1', 'NIER_REMIX_LIVE_TEX': tr.win(tex2),
                                                   'FAKE_REMIX_INSTANCE_LOG': '1', 'FAKE_REMIX_CAMERA_LOG': '1'})
        assert fake and 'VIOLATION' not in fake, fake
        skinned = [x for x in fake.splitlines() if x.startswith('CreateMesh') and 'indices=192 ' in x]
        assert len(skinned) == 1, world_meshes(fake)[:3]
        assert 'skinned=0 ' in skinned[0] and 'weights=0 ' in skinned[0], skinned[0]
        verts = int(re.search(r'verts=(\d+)', skinned[0]).group(1))
        assert verts <= 65 and 'v0=0.000,0.000,0.500' in skinned[0], skinned[0]
        assert all('bones=0 ' in x for x in fake.splitlines() if x.startswith('DrawInstance')), fake[-600:]
        assert int(r['geometry_reads']) <= 3, f'skinned path must not read geometry back per frame: {r}'
        assert tmo.near(tr.rgb((d / 'capture-after.raw').read_bytes(), *tr.PROBE), tr.REMIX)
        results['skinned'] = 'Skinned draw is CPU-baked once for an unchanged pose; no GPU palette or weights reach Remix.'

        # A draw with no CB11 has no world transform: screen-space/UI, so it must not enter the world scene.
        tex3 = work / 'live-textures-nocb'
        tex3.mkdir()
        _, r, log, fake = tr.run(work, 'nocb', {**base, 'MOCK_CAMERA': 'live-nocb', 'NIER_REMIX': '1',
                                                'NIER_REMIX_LIVE': '1', 'NIER_REMIX_LIVE_TEX': tr.win(tex3),
                                                'FAKE_REMIX_INSTANCE_LOG': '1'})
        assert fake and 'VIOLATION' not in fake, fake
        live_meshes = [x for x in world_meshes(fake) if 'verts=65' in x]
        assert not live_meshes, live_meshes[:2]
        instances = [x for x in fake.splitlines() if x.startswith('DrawInstance')]
        # No fallback scene any more: with every draw filtered there is nothing to compose, so nothing may be drawn.
        # If an untransformed draw slipped into the scene it would be here.
        assert not instances, instances[:2]
        assert any("no live draws yet" in x for x in tr.remix_lines(log)), tr.remix_lines(log)[-4:]
        results['nocb'] = 'Draws without a world transform are skipped instead of drawn at the origin.'

        # start_index and base_vertex: real NieR draws use non-zero start_index almost always. Both draws must
        # address the second half of the vertex buffer (z=2.5), not the first (z=0.5).
        tex4 = work / 'live-textures-offset'
        tex4.mkdir()
        _, r, log, fake = tr.run(work, 'offset', {**base, 'MOCK_CAMERA': 'live-offset', 'NIER_REMIX': '1',
                                                  'NIER_REMIX_LIVE': '1', 'NIER_REMIX_LIVE_TEX': tr.win(tex4)})
        assert fake and 'VIOLATION' not in fake, fake
        offset_meshes = world_meshes(fake)
        # 4 distinct geometries (start_index and base_vertex draws, from both vertex buffers) plus one rebuild
        # each for the two draws that use the rewritten dynamic buffer.
        assert len(offset_meshes) == 9, offset_meshes
        assert len({re.search(r'key=(\d+)', m).group(1) for m in offset_meshes}) == 6, offset_meshes
        for line in offset_meshes:
            assert 'verts=65' in line and 'indices=192' in line, line
            assert 'v0=0.000,0.000,2.500' in line, f'start_index/base_vertex ignored: {line}'
        results['offsets'] = 'start_index, base_vertex and the vertex-buffer offset all select the right vertices.'

        # A sky-dome-sized draw is not world geometry: it must be submitted with the SKY category, not dropped and not
        # ray traced as a shell around the camera. Before 2026-10-29 it was dropped, which is why the background was
        # simply missing from the picture.
        _, r, log, fake = tr.run(work, 'sky', {**base, 'NIER_REMIX': '1', 'NIER_REMIX_LIVE': '1',
                                               'NIER_REMIX_LIVE_TEX': tr.win(tex), 'FAKE_REMIX_INSTANCE_LOG': '1'})
        assert fake and 'VIOLATION' not in fake, fake
        sky = [x for x in fake.splitlines() if x.startswith('CreateMesh') and abs(float(re.search(r'v0=([-\d.]+),', x).group(1))) > 5000]
        assert sky, 'the sky dome never became a mesh, so it cannot be submitted as sky'
        drawn_sky = [x for x in fake.splitlines() if x.startswith('DrawInstance') and 'flags=' in x
                     and (int(re.search(r'flags=(\d+)', x).group(1)) & 4)]
        assert drawn_sky, 'the sky dome was never drawn with REMIXAPI_INSTANCE_CATEGORY_BIT_SKY'
        assert len([x for x in fake.splitlines() if x.startswith('CreateMesh')]) == 4, 'sky draw disturbed the live meshes'
        results['sky'] = 'Sky-sized draws become a mesh drawn with the SKY category, not world geometry and not dropped.'

        # Rollback switch for a wrong-looking sky: NIER_REMIX_LIVE_NO_SKY=1 drops the dome again (the pre-1.9 picture)
        # instead of submitting it, and the world draws are untouched.
        tex_ns = work / 'live-textures-nosky'
        tex_ns.mkdir()
        _, r, log, fake = tr.run(work, 'nosky', {**base, 'NIER_REMIX': '1', 'NIER_REMIX_LIVE': '1', 'NIER_REMIX_LIVE_NO_SKY': '1',
                                                 'NIER_REMIX_LIVE_TEX': tr.win(tex_ns), 'FAKE_REMIX_INSTANCE_LOG': '1'})
        assert fake and 'VIOLATION' not in fake, fake
        assert not [x for x in fake.splitlines() if x.startswith('DrawInstance') and 'flags=' in x
                    and (int(re.search(r'flags=(\d+)', x).group(1)) & 4)], 'NIER_REMIX_LIVE_NO_SKY still drew the sky'
        assert [x for x in fake.splitlines() if x.startswith('DrawInstance')], 'NIER_REMIX_LIVE_NO_SKY lost the world'
        results['nosky'] = 'NIER_REMIX_LIVE_NO_SKY drops the sky dome and keeps the world.'

        # Title screen: for the first 30 frames only the sky dome is drawn. A frame of sky instances alone has zero
        # ray-traced surfaces, which crashed the real runtime (divide by zero in updateSurfaceMaterials, 2026-10-29).
        # It must not be submitted; the world, once it appears, must be.
        tex_sf = work / 'live-textures-skyfirst'
        tex_sf.mkdir()
        _, r, log, fake = tr.run(work, 'skyfirst', {**base, 'NIER_REMIX': '1', 'NIER_REMIX_LIVE': '1', 'MOCK_SKY_ONLY_UNTIL': '30',
                                                    'NIER_REMIX_LIVE_TEX': tr.win(tex_sf), 'FAKE_REMIX_INSTANCE_LOG': '1'})
        assert fake and 'VIOLATION' not in fake, [x for x in fake.splitlines() if 'VIOLATION' in x][:3]
        drawn = [x for x in fake.splitlines() if x.startswith('DrawInstance') and 'flags=' in x]
        assert any(not (int(re.search(r'flags=(\d+)', x).group(1)) & 4) for x in drawn), 'the world never reached Remix'
        assert any(int(re.search(r'flags=(\d+)', x).group(1)) & 4 for x in drawn), 'the sky never reached Remix'
        results['skyfirst'] = 'Sky-only frames are held back (Remix crashes on them); the world and sky follow.'

        # Live on: a boxed UpdateSubresource must update only the boxed bytes of the shadow (no over-read crash), and
        # the partial write must reach the mesh it belongs to.
        tex5 = work / 'live-textures-box'
        tex5.mkdir()
        _, r, log, fake = tr.run(work, 'box', {**base, 'MOCK_CAMERA': 'live-box', 'NIER_REMIX': '1',
                                               'NIER_REMIX_LIVE': '1', 'NIER_REMIX_LIVE_TEX': tr.win(tex5)})
        assert fake and 'VIOLATION' not in fake, fake
        assert any('v0=7.000,8.000,9.000' in x for x in world_meshes(fake)), \
            world_meshes(fake)
        results['box'] = 'Boxed UpdateSubresource updates exactly the boxed bytes, and the change reaches its mesh.'

        # Eviction must not make geometry vanish: a mesh evicted while unused is rebuilt when it is drawn again, and a
        # mesh drawn in the current frame is never the victim. Budget fits two of the ~4.9 KB meshes.
        tex6 = work / 'live-textures-evict'
        tex6.mkdir()
        _, r, log, fake = tr.run(work, 'evict', {**base, 'MOCK_CAMERA': 'live-evict', 'NIER_REMIX': '1',
                                                 'NIER_REMIX_LIVE': '1', 'NIER_REMIX_LIVE_TEX': tr.win(tex6),
                                                 'NIER_REMIX_LIVE_BUDGET_KB': '12'})
        assert fake and 'VIOLATION' not in fake, fake
        made = [(re.search(r'key=(\d+)', x).group(1), int(re.search(r'presented=(\d+)', x).group(1)))
                for x in world_meshes(fake)]
        # B is the mesh first built when it appears (frames 40-45). It is never rewritten, so a second build can only
        # mean it was evicted while unused (C arrived at 55) and uploaded again when drawn from 65.
        b = [h for h, at in made if 35 <= at < 50 and h not in {x for x, a in made if a < 35}]
        assert len(set(b)) == 1, f'expected exactly one mesh first built at B\'s appearance: {made}'
        assert any(h == b[0] and at >= 60 for h, at in made), f'an evicted mesh never came back: {made}'
        results['evict'] = 'An evicted mesh is rebuilt when drawn again; meshes in use are never evicted.'

        # Shadow trim: with a shadow budget far below the working set, already-built geometry must need no further
        # readback at all, and a rewrite must still rebuild exactly once.
        tex7 = work / 'live-textures-trim'
        tex7.mkdir()
        _, r, log, fake = tr.run(work, 'trim', {**base, 'NIER_REMIX': '1', 'NIER_REMIX_LIVE': '1',
                                                'NIER_REMIX_LIVE_TEX': tr.win(tex7), 'NIER_REMIX_LIVE_SHADOW_KB': '1'})
        assert fake and 'VIOLATION' not in fake, fake
        # The budget must really have been hit, or this scenario proves nothing.
        assert any('live shadow budget reached' in x for x in tr.remix_lines(log)), tr.remix_lines(log)[-8:]
        assert r['geometry_reads_late'] == '0', f'readbacks every frame once shadows are trimmed: {r}'
        assert int(r['camera_reads']) <= 90, f'constant buffers re-read every frame once shadows are trimmed: {r}'
        made = world_meshes(fake)
        assert len(made) == 3, f'expected A, B and one rebuild of A after its rewrite: {made}'
        results['trim'] = 'A tiny shadow budget causes no per-frame readback and no extra rebuilds.'

        # Expiry must release only buffers that are really unused: geometry drawn every frame keeps its identity (no
        # rebuild, no readback), while B's buffers, unused for 19 frames, are released.
        tex8 = work / 'live-textures-expire'
        tex8.mkdir()
        _, r, log, fake = tr.run(work, 'expire', {**base, 'MOCK_CAMERA': 'live-evict', 'NIER_REMIX': '1',
                                                  'NIER_REMIX_LIVE': '1', 'NIER_REMIX_LIVE_TEX': tr.win(tex8),
                                                  'NIER_REMIX_LIVE_EXPIRE_FRAMES': '10'})
        assert fake and 'VIOLATION' not in fake, fake
        assert any('live released' in x for x in tr.remix_lines(log)), tr.remix_lines(log)[-8:]
        made = [(re.search(r'key=(\d+)', x).group(1), int(re.search(r'presented=(\d+)', x).group(1)))
                for x in world_meshes(fake)]
        a = made[0][0]
        assert sum(1 for h, _ in made if h == a) == 2, f'mesh A drawn every frame was rebuilt by expiry: {made}'
        # Review round 2, N1: a texture unused for a while and then drawn again must keep its file and material, not be
        # exported again under a new id (that exhausts the disk budget and untextures the rest of the session).
        dds = sorted(x.name for x in tex8.iterdir() if x.suffix == '.dds')
        assert len(dds) == 2, f'expected one DDS each for A and B, got {dds}'
        results['expire'] = 'Expiry releases unused buffers only; textures keep their file; drawn geometry is never rebuilt by it.'

        # Failed GPU readbacks (device busy/lost, staging creation failing): the index buffer reads but a vertex buffer
        # does not. The draw must be retried later, never decoded from a missing buffer (independent review P0-1).
        tex9 = work / 'live-textures-readfail'
        tex9.mkdir()
        _, r, log, fake = tr.run(work, 'readfail', {**base, 'NIER_REMIX': '1', 'NIER_REMIX_LIVE': '1',
                                                    'NIER_REMIX_LIVE_TEX': tr.win(tex9),
                                                    'NIER_REMIX_LIVE_FAIL_VB_READS': '45'})
        assert fake and 'VIOLATION' not in fake, fake
        assert any('injected' in x and 'read failures' in x for x in tr.remix_lines(log)), tr.remix_lines(log)[-8:]
        made = world_meshes(fake)
        assert len(made) == 3, f'after the failures stop, A, B and A\'s rebuild must still be built: {made}'
        results['readfail'] = 'Failed vertex-buffer readbacks are retried later instead of crashing the game.'

        # Review round 3, P1: with every write skipped (threshold 0) and the per-frame read budget nearly nil, a
        # geometry whose content changed must still be rebuilt in that frame. Deferring it would leave the previous
        # mesh on screen for as long as the budget stays spent: a frozen object, not a slow frame.
        _, r, log, fake = tr.run(work, 'changed', {**on, 'NIER_REMIX_LIVE_MAX_WRITE_KB': '0',
                                                   'NIER_REMIX_LIVE_READ_BUDGET_KB': '1',
                                                   'MOCK_LIVE_SPENDER_FROM': '41'})
        made = [dict(kv.split('=', 1) for kv in re.findall(r'(\w+=\S+)', x))
                for x in world_meshes(fake)]
        seen = [int(m['presented']) for m in made]
        # A at the start, B when it appears, A again after its content changes: three builds, the last well after the
        # first. If the spent read budget is allowed to suppress a changed rebuild there are only two, and A stays
        # frozen on screen while its buffers hold new vertices.
        # This configuration is deliberately extreme (every write skipped, budget 1 KB), so the early build count is
        # noisy. What must hold: A is built at the start, B when it appears, and A is rebuilt AFTER its content change
        # at mock frame 50 even though the sky's per-frame read has spent the budget. Without that, seen[-1] stays
        # below 45 and the object on screen keeps its old vertices.
        assert seen[0] < 5 and any(30 <= v < 45 for v in seen) and seen[-1] >= 45, seen
        assert made[-1]['key'] == made[0]['key'], f'must be A rebuilt, not another mesh: {made}'

        results['changed'] = 'Spent read budget never leaves changed geometry showing its old mesh.'

        # The same with no shadow bytes at all (every write skipped) and the first staging reads failing: the geometry
        # must be built once the failures stop. If a failed or deferred read were recorded as built, it would be
        # frozen or absent for the rest of the session (review round 3 P1 claim, tested rather than argued).
        _, r, log, fake = tr.run(work, 'readfail2', {**on, 'NIER_REMIX_LIVE_MAX_WRITE_KB': '0',
                                                    'NIER_REMIX_LIVE_FAIL_VB_READS': '6'})
        made = world_meshes(fake)
        parsed = [dict(kv.split('=', 1) for kv in re.findall(r'(\w+=\S+)', x)) for x in made]
        # A, B, and A again after its content change: not zero (never retried), not one per frame (no bounding).
        assert len(parsed) == 3 and parsed[0]['key'] == parsed[2]['key'] != parsed[1]['key'], \
            f'expected A, B, A-rebuilt: {[p["key"] for p in parsed]}'
        assert 'VIOLATION' not in fake, fake[:300]
        results['readfail2'] = 'Failed reads on a shadowed buffer are retried; nothing is recorded as built.'

        # Standing still in the real game rebuilt ~96 meshes a second: NieR rewrites dynamic buffers with identical
        # bytes, and every rewrite became a new mesh (budget pinned, evictions cycling, picture tearing). Same decoded
        # content must keep the uploaded mesh.
        tex10 = work / 'live-textures-same'
        tex10.mkdir()
        _, r, log, fake = tr.run(work, 'same', {**on, 'MOCK_LIVE_REWRITE_SAME': '1',
                                                'NIER_REMIX_LIVE_TEX': tr.win(tex10)})
        made = [dict(kv.split('=', 1) for kv in re.findall(r'(\w+=\S+)', x))
                for x in world_meshes(fake)]
        # A, B, A after the frame-50 change, and A again when frame 51 restores the original bytes. Without the
        # content check the same run builds ~80, so the bound only has to exclude per-frame rebuilding.
        assert 2 <= len(made) <= 5, f'identical rewrites must not rebuild: {len(made)} meshes'
        stats = [x for x in tr.remix_lines(log) if 'identical=' in x]
        assert stats and int(stats[-1].split('identical=')[1].split()[0]) > 0, stats[-3:]
        # ... and the draw must still be emitted every frame. Skipping the upload once dropped the instance as well,
        # which made the object vanish; the mesh count alone cannot see that.
        drawn = [dict(kv.split('=', 1) for kv in re.findall(r'(\w+=\S+)', x))
                 for x in fake.splitlines() if x.startswith('DrawInstance') and 'mesh=' in x]
        assert drawn, 'nothing was drawn at all'
        frames = {int(d['presented']) for d in drawn}
        assert len(frames) >= 40, f'the rewritten mesh must be drawn on nearly every frame, saw {len(frames)}'
        # A is rebuilt after its frame-50 content change: last build repeats A's key, and differs from B's.
        assert made[-1]['key'] == made[0]['key'] != made[1]['key'], [m['key'] for m in made]
        results['same'] = 'Rewriting a buffer with identical bytes keeps the uploaded mesh.'
    except Exception as exc:
        (OUT / 'validation.json').write_text(json.dumps({'passed': False, 'error': str(exc)[-3000:], 'results': results,
                                                         'work': str(work)}, indent=2) + '\n')
        raise
    finally:
        subprocess.run(['wineserver', '-k'], env=os.environ, capture_output=True)
    report = {'passed': True, 'results': results, 'dll_sha256': hashlib.sha256((tmo.DLL / 'd3d11.dll').read_bytes()).hexdigest(),
              'limits': 'Software-only Wine mock, fake Remix; not real NieR draws, materials or playability.'}
    (OUT / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


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
