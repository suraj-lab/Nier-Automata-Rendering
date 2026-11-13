#!/usr/bin/env python3
"""Gate for item T2's moving camera (camera_orbit.h): a yaw sweep and a dolly that keep the basis orthonormal.

Why: a replay is one frozen frame, so motion vectors, ghosting, upscaler stability and texture arrival while travelling
cannot be exercised at all. `NIER_REMIX_LIVE_CAMERA_ORBIT` turns the 14-float camera the proxy hands to Remix into a
sweep. What this pins, natively and without a GPU:
  - the three axes stay unit length and mutually perpendicular after any yaw (the decode's own invariant);
  - a 90 degree yaw turns forward from -Z to -X about +Y, i.e. it turns the way a right-handed yaw should;
  - the dolly moves the position along forward, and nothing else;
  - zero seconds, or both rates zero, changes nothing at all.
Limits: geometry of the camera vector only. Whether the picture moves is a replay, not a gate.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
HARNESS = r'''
#include "camera_orbit.h"
#include <array>
#include <cmath>
#include <cstdio>

static double len(const float v[3]) { return std::sqrt(double(v[0])*v[0] + double(v[1])*v[1] + double(v[2])*v[2]); }
static double dot(const float a[3], const float b[3]) { return double(a[0])*b[0] + double(a[1])*b[1] + double(a[2])*b[2]; }
static bool orthonormal(const std::array<float, 14>& c) {
    const float* f = &c[3]; const float* u = &c[6]; const float* r = &c[9];
    const double e = 1e-4;
    return std::fabs(len(f) - 1) < e && std::fabs(len(u) - 1) < e && std::fabs(len(r) - 1) < e &&
           std::fabs(dot(f, u)) < e && std::fabs(dot(f, r)) < e && std::fabs(dot(u, r)) < e;
}

int main() {
    std::array<float, 14> base{};
    // The decode's own convention: looking down -Z, up +Y, right +X, at the origin, 60 degrees, 16:9.
    base[0] = base[1] = base[2] = 0.f;   // position at the origin
    base[3] = 0.f; base[4] = 0.f; base[5] = -1.f;   // forward -Z
    base[6] = 0.f; base[7] = 1.f; base[8] = 0.f;    // up +Y
    base[9] = 1.f; base[10] = 0.f; base[11] = 0.f;  // right +X
    base[12] = 60.f; base[13] = 16.f / 9.f;

    // Nothing to do: identical, bit for bit.
    {
        auto c = base;
        if (camera_orbit::apply(c, 0.0, 90.0, 2.0)) { std::puts("FAIL zero seconds applied"); return 1; }
        if (c != base) { std::puts("FAIL zero seconds changed the camera"); return 1; }
        c = base;
        if (camera_orbit::apply(c, 5.0, 0.0, 0.0)) { std::puts("FAIL zero rates applied"); return 1; }
        if (c != base) { std::puts("FAIL zero rates changed the camera"); return 1; }
    }
    // A quarter turn to the left about +Y: forward -Z -> -X.
    {
        auto c = base;
        if (!camera_orbit::apply(c, 1.0, 90.0, 0.0)) { std::puts("FAIL yaw not applied"); return 1; }
        if (!orthonormal(c)) { std::puts("FAIL yaw broke the basis"); return 1; }
        if (std::fabs(c[3] + 1.f) > 1e-3 || std::fabs(c[4]) > 1e-3 || std::fabs(c[5]) > 1e-3) {
            std::printf("FAIL quarter yaw: forward %.3f %.3f %.3f\n", c[3], c[4], c[5]); return 1;
        }
        if (std::fabs(c[7] - 1.f) > 1e-3) { std::puts("FAIL quarter yaw moved up"); return 1; }
    }
    // A full turn returns to the start.
    {
        auto c = base;
        camera_orbit::apply(c, 1.0, 360.0, 0.0);
        for (int i = 3; i < 12; ++i)
            if (std::fabs(c[size_t(i)] - base[size_t(i)]) > 1e-3) { std::printf("FAIL full turn at %d\n", i); return 1; }
    }
    // Dolly: position moves along forward, the axes do not move, the fov and aspect are untouched.
    {
        auto c = base;
        if (!camera_orbit::apply(c, 2.0, 0.0, 1.5)) { std::puts("FAIL dolly not applied"); return 1; }
        if (std::fabs(c[0]) > 1e-4 || std::fabs(c[1]) > 1e-4 || std::fabs(c[2] + 3.f) > 1e-3) {
            std::printf("FAIL dolly position %.3f %.3f %.3f\n", c[0], c[1], c[2]); return 1;
        }
        for (int i = 3; i < 14; ++i)
            if (std::fabs(c[size_t(i)] - base[size_t(i)]) > 1e-5) { std::printf("FAIL dolly changed lane %d\n", i); return 1; }
    }
    // Both at once, over several steps: still a rigid frame.
    {
        auto c = base;
        for (int step = 1; step <= 24; ++step) {
            auto one = base;
            camera_orbit::apply(one, step * 0.25, 30.0, 0.5);
            if (!orthonormal(one)) { std::printf("FAIL step %d not orthonormal\n", step); return 1; }
        }
        (void)c;
    }
    std::puts("yaw keeps the basis rigid, a quarter turn faces -X, a full turn is identity, the dolly moves along forward only");
    return 0;
}
'''


def main():
    work = Path(tempfile.mkdtemp(prefix='camera-orbit-'))
    (work / 't.cpp').write_text(HARNESS)
    build = subprocess.run(['g++', '-std=c++17', '-O1', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                            '-I', str(C), str(work / 't.cpp'), '-o', str(work / 't')], capture_output=True, text=True)
    if build.returncode:
        print(json.dumps({'passed': False, 'error': 'compile:\n' + build.stderr[-1500:]}))
        return 1
    run = subprocess.run([str(work / 't')], capture_output=True, text=True)
    if run.returncode:
        print(json.dumps({'passed': False, 'error': (run.stdout + run.stderr)[-1500:]}))
        return 1
    print(json.dumps({'passed': True, 'checks': run.stdout.strip(),
                      'limits': 'camera vector geometry only; whether the picture moves needs a replay'}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
