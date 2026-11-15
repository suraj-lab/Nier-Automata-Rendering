#!/usr/bin/env python3
"""C3b review regressions: terminal bad landed inputs and string lifetime cleanup."""
from pathlib import Path
import sys
import test_terrain_bake as base

EXTRA = r'''
    for (bool mips : {false, true}) {
        live_scene::terrain_mips = mips;
        check("write corrupt landed DDS", live_scene::write_whole(p1, {1,2,3}));
        live_scene::State bad;
        bad.texture_paths = {p1, p2}; bad.landed = {1, 1};
        const auto handle = live_scene::baked_material_for(api, bad, 1, 2, 0, 0.01f);
        check("bad landed input retains grey material", handle != nullptr);
        check("bad landed input is terminal and counted", bad.pending_bakes.empty() && bad.bakes_failed == 1);
        const auto destroyed_before = destroyed.size();
        for (unsigned i=0; i<3; ++i) live_scene::refresh_incomplete_materials(api, bad);
        check("no perpetual grey material churn", destroyed.size() == destroyed_before && bad.bakes_failed == 1);
        bad.baked_paths.push_back(L"retained-name");
        live_scene::destroy(api, bad);
        check("path strings released after materials destroyed", bad.baked_paths.empty());
        live_scene::State late;
        late.texture_paths = {L"", L""}; late.landed = {0, 0};
        check("missing input initially pending", live_scene::baked_material_for(api, late, 1, 2, 0, 0.01f) != nullptr && late.pending_bakes.size() == 1);
        late.texture_paths = {p1, p2}; late.landed = {1, 1};
        live_scene::refresh_incomplete_materials(api, late);
        check("late corrupt input becomes terminal", late.pending_bakes.empty() && late.bakes_failed == 1);
        const auto after_refresh = destroyed.size();
        live_scene::refresh_incomplete_materials(api, late);
        check("late corrupt input not retried", destroyed.size() == after_refresh);
        live_scene::destroy(api, late);
    }
    live_scene::terrain_mips = false;
    live_scene::State invalid;
    check("zero texture id not queued", !live_scene::baked_material_for(api, invalid, 0, 2, 0, 0.01f) && invalid.pending_bakes.empty());
'''

if __name__ == '__main__':
    anchor = r'    std::printf("failures=%d\n", failures);'
    assert anchor in base.HARNESS
    base.HARNESS = base.HARNESS.replace(anchor, EXTRA + '\n' + anchor)
    work = Path(__file__).resolve().parents[1] / 'runtime/c3b-mip-hidden'
    work.mkdir(parents=True, exist_ok=True)
    base.tempfile.tempdir = str(work)
    sys.exit(base.main())
