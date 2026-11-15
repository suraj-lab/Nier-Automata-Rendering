#!/usr/bin/env python3
"""C3b reuse real native scene harness: opt-in cache keys, files and material references."""
from pathlib import Path
import sys

import test_terrain_bake as base

EXTRA = r'''
        const auto legacy_handle = live_scene::baked_material_for(api, s, 1, 2, 7, 0.01f);
        const auto legacy_id = static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(legacy_handle));
        const std::wstring legacy_path = made[legacy_id].path;
        std::vector<unsigned char> legacy_bytes;
        check("legacy file exists", live_scene::read_whole(legacy_path, legacy_bytes));
        live_scene::terrain_mips = true;
        const auto mip_handle = live_scene::baked_material_for(api, s, 1, 2, 7, 0.01f);
        const auto mip_id = static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(mip_handle));
        const std::wstring mip_path = made[mip_id].path;
        check("mip material gets distinct cache identity", mip_handle && mip_handle != legacy_handle && mip_path != legacy_path);
        std::vector<unsigned char> mip_bytes, unchanged;
        check("mip file created", live_scene::read_whole(mip_path, mip_bytes));
        unsigned levels = 0;
        if (mip_bytes.size() >= 148) std::memcpy(&levels, mip_bytes.data() + 28, 4);
        check("mip material references full fresh asset", levels == 2 && mip_bytes.size() == 168);
        check("legacy cached asset not overwritten", live_scene::read_whole(legacy_path, unchanged) && unchanged == legacy_bytes);
        check("mip material cache reused", live_scene::baked_material_for(api, s, 1, 2, 7, 0.01f) == mip_handle);
        live_scene::terrain_mips = false;
        check("legacy material restored by switch", live_scene::baked_material_for(api, s, 1, 2, 7, 0.01f) == legacy_handle);
'''

if __name__ == '__main__':
    anchor = '        live_scene::destroy(api, s);'
    assert anchor in base.HARNESS
    base.HARNESS = base.HARNESS.replace(anchor, EXTRA + '\n' + anchor, 1)
    work = Path(__file__).resolve().parents[1] / 'runtime/c3b-mip-integration'
    work.mkdir(parents=True, exist_ok=True)
    base.tempfile.tempdir = str(work)
    sys.exit(base.main())
