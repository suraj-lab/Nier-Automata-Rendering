#!/usr/bin/env python3
"""Hidden cases for nscn_scene.h (kept from the implementer until acceptance). Usage: test_nscn_scene_hidden.py <nscn_scene.h>"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
sys.path.insert(0, str(C))
import test_nscn_scene as ts  # noqa: E402

HARNESS = r'''
#include <cstdio>
#include <fstream>
#include <iterator>
#include "nscn_scene.h"
static int calls = 0;
static unsigned long long h = 0x100;
static remixapi_ErrorCode REMIXAPI_CALL mat(const remixapi_MaterialInfo*, remixapi_MaterialHandle* o) { ++calls; *o = (remixapi_MaterialHandle)h++; return REMIXAPI_ERROR_CODE_SUCCESS; }
static remixapi_ErrorCode REMIXAPI_CALL mesh(const remixapi_MeshInfo*, remixapi_MeshHandle* o) { ++calls; *o = (remixapi_MeshHandle)h++; return REMIXAPI_ERROR_CODE_SUCCESS; }
static remixapi_ErrorCode REMIXAPI_CALL light(const remixapi_LightInfo*, remixapi_LightHandle* o) { ++calls; *o = (remixapi_LightHandle)h++; return REMIXAPI_ERROR_CODE_SUCCESS; }
static remixapi_ErrorCode REMIXAPI_CALL any_m(remixapi_MaterialHandle) { ++calls; return REMIXAPI_ERROR_CODE_SUCCESS; }
static remixapi_ErrorCode REMIXAPI_CALL any_s(remixapi_MeshHandle) { ++calls; return REMIXAPI_ERROR_CODE_SUCCESS; }
static remixapi_ErrorCode REMIXAPI_CALL any_l(remixapi_LightHandle) { ++calls; return REMIXAPI_ERROR_CODE_SUCCESS; }
static remixapi_ErrorCode REMIXAPI_CALL cam(const remixapi_CameraInfo*) { ++calls; return REMIXAPI_ERROR_CODE_SUCCESS; }
static remixapi_ErrorCode REMIXAPI_CALL inst(const remixapi_InstanceInfo*) { ++calls; return REMIXAPI_ERROR_CODE_SUCCESS; }
static std::vector<unsigned char> rd(const char* p) { std::ifstream f(p, std::ios::binary); return {std::istreambuf_iterator<char>(f), {}}; }
int main(int, char** argv) {
    remixapi_Interface a{};
    a.CreateMaterial = mat; a.CreateMesh = mesh; a.CreateLight = light; a.DestroyMaterial = any_m; a.DestroyMesh = any_s;
    a.DestroyLight = any_l; a.SetupCamera = cam; a.DrawInstance = inst; a.DrawLightInstance = any_l;
    nscn::Scene s;
    const bool first = nscn::parse(rd(argv[1]), s);           // two textures
    const bool second = nscn::parse(rd(argv[2]), s);          // one texture: reuse must not keep the old table
    const std::size_t reused_textures = s.textures.size();
    nscn::Scene u; const bool unref = nscn::parse(rd(argv[3]), u);  // 3 textures, draws reference one
    nscn::Built b; calls = 0;
    const int rc = nscn::build(a, u, L"D:\\t\\", nscn::Options{}, b);
    const int mats = calls - 3;  // minus mesh + 2 lights
    nscn::destroy(a, b); calls = 0;
    const int after = nscn::submit(a, u, b, 1.f);
    std::printf("{\"first\":%d,\"second\":%d,\"reused_textures\":%zu,\"unref\":%d,\"rc\":%d,\"materials\":%d,\"submit_after_destroy\":%d,\"submit_calls\":%d}\n",
                first, second, reused_textures, unref, rc, mats, after, calls);
}
'''


def main():
    checks = []
    try:
        cand = Path(sys.argv[1]).resolve()
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / 'nscn_scene.h').write_text(cand.read_text())
            (d / 'h.cpp').write_text(HARNESS)
            r = subprocess.run(['g++', '-std=c++17', '-O1', '-Wall', '-Wextra', '-Werror', '-Wno-int-to-pointer-cast',
                                '-DREMIX_WINAPI_NO_INCLUDE', '-DREMIX_WINAPI_NO_LIBRARY_LOADER', '-D_WIN64=1', '-D__stdcall=',
                                '-D__declspec(x)=', '-isystem', str(ts.VENDOR), '-I', str(d), str(d / 'h.cpp'), '-o', str(d / 'h')],
                               capture_output=True, text=True)
            assert r.returncode == 0, r.stderr[-2000:]
            two = ts.scene_bytes(ts.CAMERA, ts.DRAWS, ts.TEXTURES, ts.TRIS)
            one = ts.scene_bytes(ts.CAMERA, [(1, 0, 1, 0, 41)], [(41, 'tex_41.dds')], ts.TRIS)
            three = ts.scene_bytes(ts.CAMERA, [(1, 0, 1, 0, 9)], [(41, 'a.dds'), (9, 'b.dds'), (7, 'c.dds')], ts.TRIS)
            for n, data in (('two', two), ('one', one), ('three', three)):
                (d / f'{n}.bin').write_bytes(data)
            r = subprocess.run([str(d / 'h'), str(d / 'two.bin'), str(d / 'one.bin'), str(d / 'three.bin')], capture_output=True, text=True, timeout=60)
            o = json.loads(r.stdout)
            assert o['first'] == 1 and o['second'] == 1 and o['reused_textures'] == 1, f'parse into a reused Scene kept stale textures: {o}'
            checks.append('parse into a reused Scene replaces the texture table')
            assert o['unref'] == 1 and o['rc'] == 0 and o['materials'] == 6, f'every table texture gets its pair, referenced or not: {o}'
            checks.append('unreferenced textures still get opaque + cutout materials')
            assert o['submit_after_destroy'] == 1 and o['submit_calls'] == 0, f'submit on an emptied Built must refuse without calls: {o}'
            checks.append('submit after destroy: GENERAL_FAILURE, no API call')
    except Exception as e:  # noqa: BLE001
        print(json.dumps({'passed': False, 'checks': checks, 'error': f'{type(e).__name__}: {e}'[:3000]}, indent=1))
        return 1
    print(json.dumps({'passed': True, 'checks': checks}, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
