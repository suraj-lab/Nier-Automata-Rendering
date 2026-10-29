#!/usr/bin/env python3
"""Frozen gate: verified NieR VS CB0 -> Remix camera; no GPU/game/Windows calls.
Usage: test_camera_decode.py <camera_decode.h>. Real captures are optional outside this checkout.
"""
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

C = Path(__file__).resolve().parent
CAPTURES = C.parent / 'runtime/remix-probe/captures'
HARNESS = r'''
#include "camera_decode.h"
#include <array>
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iterator>
#include <limits>
#include <vector>
using Camera = std::array<float,14>;
static std::array<float,32> base() {
    std::array<float,32> f{};
    f[0]=f[5]=f[10]=f[15]=1;
    f[16]=.5f;f[21]=1;f[26]=-1.00001f;f[27]=-.1f;f[30]=-1;
    return f;
}
static unsigned rejects=0;
static void reject(const void* b,std::size_t n) {
    Camera out;out.fill(123.25f);const auto before=out;
    assert(!camera_decode::decode(b,n,out));assert(out==before);++rejects;
}
static bool near(float a,float b) { return std::fabs(a-b)<1e-4f; }
int main(int argc,char** argv) {
    if(argc==2) {
        std::ifstream file(argv[1],std::ios::binary);
        std::vector<unsigned char> b{std::istreambuf_iterator<char>(file),{}};
        Camera camera{};assert(camera_decode::decode(b.data(),b.size(),camera));
        std::printf("[");for(unsigned i=0;i<14;++i)std::printf("%s%.9g",i?",":"",camera[i]);std::puts("]");return 0;
    }
    auto f=base();Camera c{};
    assert(camera_decode::decode(f.data(),sizeof f,c));
    Camera expected{0,0,0,0,0,-1,0,1,0,1,0,0,90,2};
    for(unsigned i=0;i<14;++i)assert(near(c[i],expected[i]));
    f[3]=2;f[7]=-3;f[11]=5;assert(camera_decode::decode(f.data(),sizeof f,c));
    assert(near(c[0],-2)&&near(c[1],3)&&near(c[2],-5));
    f=base();f[0]=0;f[2]=1;f[8]=-1;f[10]=0;f[3]=-30;f[7]=-2;f[11]=10;
    assert(camera_decode::decode(f.data(),sizeof f,c));
    assert(near(c[0],10)&&near(c[1],2)&&near(c[2],30)&&near(c[3],1)&&near(c[11],1));
    unsigned char unaligned[129];std::memcpy(unaligned+1,f.data(),128);
    assert(camera_decode::decode(unaligned+1,128,c));
    for(std::size_t n=0;n<128;++n)reject(f.data(),n);
    reject(nullptr,128);reject(nullptr,0);
    for(unsigned i=0;i<32;++i)for(float bad:{std::numeric_limits<float>::quiet_NaN(),
            std::numeric_limits<float>::infinity(),-std::numeric_limits<float>::infinity()}) {
        f=base();f[i]=bad;reject(f.data(),sizeof f);
    }
    for(unsigned i:{12u,13u,14u,15u}) {f=base();f[i]+=.01f;reject(f.data(),sizeof f);}
    for(unsigned i:{16u,21u})for(float bad:{0.f,-1.f}) {f=base();f[i]=bad;reject(f.data(),sizeof f);}
    for(unsigned i:{26u,27u}) {f=base();f[i]=0;reject(f.data(),sizeof f);}
    for(unsigned i:{30u,31u}) {f=base();f[i]+=.01f;reject(f.data(),sizeof f);}
    f=base();f[0]=1.01f;reject(f.data(),sizeof f);
    f=base();f[1]=.05f;reject(f.data(),sizeof f);
    f=base();f[0]=-1;reject(f.data(),sizeof f); // reflected rather than proper rotation
    f=base();f[0]=0;reject(f.data(),sizeof f);
    f=base();f[16]=std::numeric_limits<float>::min();f[21]=std::numeric_limits<float>::max();reject(f.data(),sizeof f);
    f=base();f[0]=f[2]=f[10]=std::sqrt(.5f);f[8]=-std::sqrt(.5f);
    f[3]=f[11]=std::numeric_limits<float>::max();reject(f.data(),sizeof f);
    f=base();f[0]=1.0001f;assert(camera_decode::decode(f.data(),sizeof f,c)); // tolerate measured float noise
    std::printf("{\"passed\":true,\"rejected_cases\":%u}\n",rejects);
}
'''


def reference(data):
    f = struct.unpack_from('<32f', data)
    rows = [f[i:i + 3] for i in (0, 4, 8)]
    t = [f[i] for i in (3, 7, 11)]
    position = [-sum(rows[r][j] * t[r] for r in range(3)) for j in range(3)]
    return position + [-x for x in rows[2]] + list(rows[1]) + list(rows[0]) + [math.degrees(2 * math.atan(1 / f[21])), f[21] / f[16]]


def run(candidate):
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / 'camera_decode.h').write_bytes(Path(candidate).read_bytes())
        (root / 'gate.cpp').write_text(HARNESS)
        (root / 'second.cpp').write_text('#include "camera_decode.h"\nbool second(const void* b, std::size_t n, std::array<float,14>& c) { return camera_decode::decode(b,n,c); }\n')
        result = subprocess.run(['g++', '-std=c++17', '-O1', '-Wall', '-Wextra', '-Werror',
                                 '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                                 str(root / 'gate.cpp'), str(root / 'second.cpp'), '-o', str(root / 'gate')], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr[-2500:]
        result = subprocess.run([str(root / 'gate')], capture_output=True, text=True)
        assert result.returncode == 0, (result.stdout + result.stderr)[-2500:]
        report = json.loads(result.stdout)
        fixtures = []
        if CAPTURES.is_dir():
            for folder in sorted(CAPTURES.iterdir()):
                paths = sorted(folder.rglob('cb_0.bin'))
                if paths:
                    fixtures.append(paths[0])
        for path in fixtures:
            result = subprocess.run([str(root / 'gate'), str(path)], capture_output=True, text=True)
            assert result.returncode == 0, str(path) + ': ' + (result.stdout + result.stderr)[-1500:]
            got, want = json.loads(result.stdout), reference(path.read_bytes())
            assert len(got) == 14 and all(math.isfinite(x) for x in got)
            assert all(math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-4) for a, b in zip(got, want)), (path, got, want)
            extra = path.with_name('cb_13.bin')
            if extra.exists():
                position = struct.unpack_from('<3f', extra.read_bytes(), 16)
                assert all(abs(a - b) < 1e-3 for a, b in zip(got[:3], position)), 'independent CB13 position check'
        report['real_captures'] = len(fixtures)
        return report


if __name__ == '__main__':
    try:
        print(json.dumps(run(sys.argv[1])))
    except Exception as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        sys.exit(1)
