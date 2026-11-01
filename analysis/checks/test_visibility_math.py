#!/usr/bin/env python3
"""Gate: the projection maths, then applied to a real captured frame.

Synthetic cases pin the arithmetic (behind the camera, off screen, degenerate, collapsed transform). The real-data case
projects every decodable draw of a captured NieR frame through that frame's own view/projection/world matrices and
reports how much of the screen the submitted geometry covers — the eyes-free version of "is the world there".
"""
import json
import math
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
A = C.parent
CAP = A / 'runtime/remix-probe/captures/frame_9443695'
BIN = A / 'runtime/visibility-math/probe'

HARNESS = r'''
#include "visibility_math.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <vector>
using namespace visibility_math;

static Mat4 identity() { Mat4 m; for (int i = 0; i < 4; ++i) m.m[i][i] = 1.f; return m; }

int main() {
    // A simple perspective: x,y in [-1,1] maps to the frame when w = -z_view.
    Mat4 proj; proj.m[0][0] = 1.f; proj.m[1][1] = 1.f; proj.m[2][2] = -1.f; proj.m[2][3] = -0.1f;
    proj.m[3][2] = -1.f;
    const Mat4 view = identity();
    const Mat4 vp = multiply(view, proj);

    Screen s = project(vp, Point3{0.f, 0.f, -10.f}, 100.f, 100.f);
    assert(s.finite && s.w > 0.f && std::fabs(s.x - 50.f) < 1e-3 && std::fabs(s.y - 50.f) < 1e-3);

    // Behind the camera: w <= 0, so the point must not be treated as on screen.
    Screen back = project(vp, Point3{0.f, 0.f, 10.f}, 100.f, 100.f);
    assert(back.w <= 0.f);

    // Off-screen to the right: x/proj.w lands past the frame edge.
    Screen right = project(vp, Point3{50.f, 0.f, -10.f}, 100.f, 100.f);
    assert(right.finite && right.x > 100.f);

    // Degenerate: three collinear projections cover no area.
    Coverage c;
    add_triangle(c, Screen{0, 0, 1, true}, Screen{10, 10, 1, true}, Screen{20, 20, 1, true}, 100, 100);
    assert(c.triangles == 1 && c.degenerate == 1 && c.on_screen == 0);

    // A triangle behind the camera is counted as behind, never as on screen.
    Coverage b;
    add_triangle(b, Screen{0, 0, -1, true}, Screen{10, 0, -1, true}, Screen{0, 10, -1, true}, 100, 100);
    assert(b.behind == 1 && b.on_screen == 0);

    // A real triangle on screen: area and frame fraction are what we expect.
    Coverage f;
    add_triangle(f, Screen{0, 0, 1, true}, Screen{100, 0, 1, true}, Screen{0, 100, 1, true}, 100, 100);
    assert(f.on_screen == 1 && std::fabs(f.area_px - 5000.0) < 1e-6);
    assert(std::fabs(screen_fraction(f, 100, 100) - 1.0) < 1e-9);

    // A collapsed transform is detectable before any projection.
    Mat4 flat = identity();
    flat.m[0][0] = flat.m[1][1] = flat.m[2][2] = 0.f;
    assert(determinant3(flat) == 0.0 && determinant3(identity()) == 1.0);
    Mat4 nan = identity(); nan.m[0][3] = std::nanf("");
    assert(!finite(nan) && finite(identity()));

    // Round trip of the 3x4 form: translation lands in the fourth column.
    const float w3[12] = {1,0,0,7, 0,1,0,8, 0,0,1,9};
    const Point3 p = transform_point(from_3x4(w3), Point3{0.f, 0.f, 0.f});
    assert(p.x == 7.f && p.y == 8.f && p.z == 9.f);

    // ---- Remix's own camera (position/forward/up/right/fovY/aspect) ------------------------------------------
    {   // Camera at the origin looking down -Z, 90 degrees vertical: a point 10 ahead fills the centre.
        float cam[14] = {0,0,0,  0,0,-1,  0,1,0,  1,0,0,  90.f, 0};
        const visibility_math::Cam c = visibility_math::camera_from(cam, 1.f);
        const Screen mid = visibility_math::project_camera(c, Point3{0.f, 0.f, -10.f}, 100.f, 100.f);
        assert(mid.finite && mid.w > 0.f && std::fabs(mid.x - 50.f) < 1e-3 && std::fabs(mid.y - 50.f) < 1e-3);
        // Behind the camera: w <= 0, never "on screen".
        assert(visibility_math::project_camera(c, Point3{0.f, 0.f, 10.f}, 100.f, 100.f).w <= 0.f);
        // Just inside the 45-degree half-angle at z=-10 -> x = 10 is the frame edge.
        const Screen edge = visibility_math::project_camera(c, Point3{9.9f, 0.f, -10.f}, 100.f, 100.f);
        assert(edge.x > 95.f && edge.x < 100.f);

        // A box in front covers the middle of the frame; the same box behind covers nothing.
        visibility_math::Bounds b;
        const float lo[3] = {-1.f, -1.f, -11.f}, hi[3] = {1.f, 1.f, -9.f};
        b.add(lo); b.add(hi);
        const Mat4 id = identity();
        const double inside = visibility_math::fraction_from_bounds(c, b, id, 100.f, 100.f);
        assert(inside > 0.01 && inside < 0.5);
        visibility_math::Bounds behind_box;
        const float blo[3] = {-1.f, -1.f, 9.f}, bhi[3] = {1.f, 1.f, 11.f};
        behind_box.add(blo); behind_box.add(bhi);
        unsigned on = 99, back = 0;
        assert(visibility_math::fraction_from_bounds(c, behind_box, id, 100.f, 100.f, &on, &back) == 0.0);
        assert(on == 0 && back == 8);

        // Scaling the world matrix to zero collapses the box: valid bounds, no coverage.
        Mat4 flat = identity();
        flat.m[0][0] = flat.m[1][1] = flat.m[2][2] = 0.f;
        const double collapsed = visibility_math::fraction_from_bounds(c, b, flat, 100.f, 100.f);
        assert(collapsed >= 0.0 && collapsed < 1e-9);
    }
    std::puts("projection, behind-camera, off-screen, degenerate, frame fraction, collapsed transform, remix camera");
}
'''


def harness_native():
    with tempfile.TemporaryDirectory(prefix='vis-math-') as d:
        d = Path(d)
        (d / 'test.cpp').write_text(HARNESS)
        p = subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                            '-I', str(C), str(d / 'test.cpp'), '-o', str(d / 'test')], capture_output=True, text=True)
        assert p.returncode == 0, 'compile:\n' + p.stderr[-3000:]
        p = subprocess.run([str(d / 'test')], capture_output=True, text=True)
        assert p.returncode == 0, 'run:\n' + (p.stdout + p.stderr)[-3000:]
        return p.stdout.strip()


PROBE = r'''
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include "visibility_math.h"
#include "live_vertex_decode.h"

using namespace visibility_math;

static std::vector<unsigned char> slurp(const char* p) {
    std::vector<unsigned char> b;
    if (FILE* f = std::fopen(p, "rb")) {
        std::fseek(f, 0, SEEK_END); const long n = std::ftell(f); std::fseek(f, 0, SEEK_SET);
        b.resize(n > 0 ? static_cast<std::size_t>(n) : 0);
        if (!b.empty() && std::fread(b.data(), 1, b.size(), f) != b.size()) b.clear();
        std::fclose(f);
    }
    return b;
}
static std::vector<float> as_floats(const std::vector<unsigned char>& b) {
    std::vector<float> f(b.size() / 4);
    if (!f.empty()) std::memcpy(f.data(), b.data(), f.size() * 4);
    return f;
}

int main(int argc, char** argv) {
    // <cb0 view+proj> <cb11 world> <width> <height> <vb spec path path ...> -- <ib> first count width base bones skinned elements
    if (argc < 10) return 2;
    const auto cb0 = as_floats(slurp(argv[1]));
    const auto cb11 = as_floats(slurp(argv[2]));
    const float width = static_cast<float>(std::atof(argv[3])), height = static_cast<float>(std::atof(argv[4]));
    if (cb0.size() < 32 || cb11.size() < 12) return 3;
    int i = 5;
    std::vector<live_decode::Slot> slots;
    std::vector<std::vector<unsigned char>> storage;
    while (i + 2 < argc && std::strcmp(argv[i], "--") != 0) {
        const std::string spec(argv[i]);
        const std::size_t a = spec.find(':'), b = spec.find(':', a + 1);
        storage.push_back(slurp(argv[i + 2]));
        slots.push_back({storage.back().data(), storage.back().size(),
                         static_cast<unsigned>(std::atoi(spec.substr(a + 1, b - a - 1).c_str())),
                         static_cast<unsigned>(std::atoi(spec.substr(b + 1).c_str()))});
        i += 3;
    }
    i += 1;
    const auto ib = slurp(argv[i]);
    const std::size_t first = static_cast<std::size_t>(std::atoll(argv[i + 1]));
    const auto count = static_cast<std::uint32_t>(std::atoi(argv[i + 2]));
    const auto iwidth = static_cast<unsigned>(std::atoi(argv[i + 3]));
    const auto base = static_cast<std::int32_t>(std::atoi(argv[i + 4]));
    const auto bones = static_cast<std::uint32_t>(std::atoi(argv[i + 5]));
    const bool skinned = std::atoi(argv[i + 6]) != 0;
    std::vector<live_decode::Element> elements;
    {   // "SEM:fmt:off:slot[:inst];..."
        std::string spec(argv[i + 7]);
        std::size_t pos = 0;
        while (pos < spec.size()) {
            std::size_t e = spec.find(';', pos);
            if (e == std::string::npos) e = spec.size();
            const std::string one = spec.substr(pos, e - pos);
            std::vector<std::string> parts;
            std::size_t q = 0;
            while (q <= one.size()) {
                const std::size_t c = one.find(':', q);
                if (c == std::string::npos) { parts.push_back(one.substr(q)); break; }
                parts.push_back(one.substr(q, c - q));
                q = c + 1;
            }
            if (parts.size() >= 4)
                elements.push_back({parts[0], std::atoi(parts[1].c_str()),
                                    static_cast<unsigned>(std::atoi(parts[2].c_str())),
                                    static_cast<unsigned>(std::atoi(parts[3].c_str())),
                                    parts.size() > 4 && parts[4] == "1"});
            pos = e + 1;
        }
    }

    live_decode::Output decoded;
    live_decode::Failure why = live_decode::Failure::None;
    if (!live_decode::build(slots.data(), static_cast<unsigned>(slots.size()), elements, ib.data(), ib.size(),
                            iwidth, first, count, base, bones, skinned, decoded, &why)) {
        std::printf("0 0 0 0 0 0 %s\n", live_decode::failure_name(why));
        return 0;
    }

    const Mat4 vp = multiply(from_rows(cb0.data() + 16), from_rows(cb0.data()));  // P * V, column vectors
    const Mat4 world = from_3x4(cb11.data());
    Coverage c;
    for (std::size_t t = 0; t + 2 < decoded.indices.size(); t += 3) {
        Point3 p[3];
        for (int k = 0; k < 3; ++k) {
            const auto& v = decoded.vertices[decoded.indices[t + k]];
            p[k] = transform_point(world, Point3{v.position[0], v.position[1], v.position[2]});
        }
        add_triangle(c, project(vp, p[0], width, height), project(vp, p[1], width, height),
                     project(vp, p[2], width, height), width, height);
    }
    std::printf("%u %u %u %u %.3f %.6f none %d\n", c.triangles, c.on_screen, c.degenerate, c.behind,
                c.area_px, screen_fraction(c, width, height), determinant3(world) == 0.0 ? 0 : 1);
    return 0;
}
'''


def build_probe():
    BIN.parent.mkdir(parents=True, exist_ok=True)
    src = BIN.parent / 'probe.cpp'
    src.write_text(PROBE)
    p = subprocess.run(['g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(C), str(src),
                        '-o', str(BIN)], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr[-2500:]
    return BIN


FMT = {2: 16, 6: 12, 10: 8, 16: 8, 28: 4, 30: 4, 34: 4}


def real_draws(limit=400):
    """Project real captured draws with that frame's own view/projection/world matrices."""
    rows = []
    for folder in sorted(CAP.glob('draw_*'))[:limit]:
        meta = json.loads((folder / 'capture.json').read_text())
        if not meta.get('layout_found') or meta.get('instanced'):
            continue
        sem = {e['semantic'] for e in meta['layout']}
        if 'POSITION' not in sem or {'BLENDINDICES', 'BLENDWEIGHT'} <= sem:
            continue
        slot_args = []
        for vb in meta['vertex_buffers']:
            p = folder / f"vb_{vb['slot']}.bin"
            slot_args += [f"v{vb['slot']}:{vb['stride']}:{vb['offset']}", str(p), str(p)]
        elements = ';'.join(f"{e['semantic']}:{e['format']}:{e['offset']}:{e['slot']}" for e in meta['layout'])
        iwidth = 2 if meta['ib_format'] == 41 else 4
        p = subprocess.run([str(BIN), str(folder / 'cb_0.bin'), str(folder / 'cb_11.bin'),
                            str(meta['vp_width']), str(meta['vp_height'])] + slot_args +
                           ['--', str(folder / 'ib.bin'), str(meta['start_index']), str(meta['index_count']),
                            str(iwidth), str(meta['base_vertex']), '0', '0', elements],
                           capture_output=True, text=True)
        if p.returncode or not p.stdout.strip():
            continue
        parts = p.stdout.split()
        if len(parts) < 7:
            continue
        tris, on, deg, behind, area, frac = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]), float(parts[4]), float(parts[5])
        if tris == 0:
            continue
        rows.append({'draw': folder.name, 'triangles': tris, 'on_screen': on, 'degenerate': deg,
                     'behind': behind, 'area_px': round(area, 1), 'frame_fraction': round(frac, 4)})
        if len(rows) >= 12:
            break
    return rows


def main():
    try:
        checks = harness_native()
        build_probe()
        draws = real_draws()
        assert len(draws) >= 4, f'only {len(draws)} decodable static draws found'
        on_screen = sum(1 for d in draws if d['on_screen'] > 0)
        assert on_screen >= len(draws) // 2, f'most sampled draws project off screen: {draws}'
        # Something real must cover real screen area: a decodable draw that projects to a few pixels only means the
        # matrices or the vertex space are wrong, not that the scene is sparse.
        best = max(d['frame_fraction'] for d in draws)
        assert best > 0.01, f'no sampled draw covers even 1% of the frame: {best}'
        print(json.dumps({'passed': True, 'checks': checks, 'real_draws': draws,
                          'on_screen_draws': f'{on_screen}/{len(draws)}', 'best_frame_fraction': best,
                          'limits': 'Projection maths and real matrices; not a pixel comparison.'}, indent=1))
    except Exception as e:
        print(json.dumps({'passed': False, 'error': str(e)[-2500:]}))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
