#!/usr/bin/env python3
"""Frozen gate: skinned draw bytes -> bind-pose vertices + Remix per-vertex bone data.

The candidate (analysis/checks/skinning_convert.h) must turn a captured skinned draw into
  - raw bind-pose POSITION/NORMAL/TEXCOORD/COLOR per vertex, and
  - 4 bone indices + 4 normalised weights per vertex,
in the exact order Remix's `remixapi_MeshInfoSkinning` wants (flat, bonesPerVertex*vertexCount).
Bone transforms are handed to Remix as the game's own 3x4 palette (`remixapi_Transform`), untouched.

Independent oracle, not derived from the candidate: skinning the candidate's output with the captured
palette with NieR's own arithmetic (sum_k w_k * M_k * [p,1], 3x4 row-major at a 48-byte stride) must
reproduce numpy's skinning of the raw capture. That ties the output to real data, not to prose.

Usage: python3 analysis/checks/test_skinning_convert.py [path/to/skinning_convert.h]
"""
import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path

C = Path(__file__).resolve().parent
A = C.parent
OUT = A / 'runtime/skinning-gate'
CAPTURES = A / 'runtime/remix-probe/captures/frame_9443695'
HEADER = Path(sys.argv[1]) if sys.argv[1:] else C / 'skinning_convert.h'
FMT = {2: 16, 6: 12, 10: 8, 16: 8, 28: 4, 30: 4, 34: 4, 57: 2, 42: 4}


def fail(msg):
    print(json.dumps({'passed': False, 'error': msg[-2500:]}, indent=2))
    sys.exit(1)


def palette_ok(folder, meta):
    """The offline converter rejects draws whose weighted bone index escapes CB11; the gate needs draws that
    are actually renderable, otherwise a 'skinned draw' here is really a world matrix in disguise."""
    raw = (folder / 'cb_11.bin').read_bytes()
    bones = len(raw) // 48
    bi = next((e['offset'] for e in meta['layout'] if e['semantic'] == 'BLENDINDICES'), None)
    bw = next((e['offset'] for e in meta['layout'] if e['semantic'] == 'BLENDWEIGHT'), None)
    stride = meta['vertex_buffers'][0]['stride']
    vb = (folder / 'vb_0.bin').read_bytes()
    if bi is None or bw is None or not bones:
        return False
    for i in range(len(vb) // stride):
        for k in range(4):
            if vb[i * stride + bw + k] > 0 and vb[i * stride + bi + k] >= bones:
                return False
    return True


def pick_draws(n=4):
    """Small real skinned draws (BLENDINDICES/BLENDWEIGHT present), copied out of the bulky capture."""
    picked = []
    for folder in sorted(CAPTURES.glob('draw_*')):
        meta = json.loads((folder / 'capture.json').read_text())
        sem = {e['semantic'] for e in meta['layout']}
        if not {'POSITION', 'BLENDINDICES', 'BLENDWEIGHT'} <= sem or not (folder / 'cb_11.bin').exists():
            continue
        if not 300 <= meta['index_count'] <= 2400 or meta['instanced'] or not palette_ok(folder, meta):
            continue
        dst = OUT / 'data' / folder.name
        if not dst.exists():
            dst.mkdir(parents=True)
            for name in ('capture.json', 'ib.bin', 'cb_11.bin'):
                shutil.copyfile(folder / name, dst / name)
            for vb in folder.glob('vb_*.bin'):
                shutil.copyfile(vb, dst / vb.name)
        picked.append(dst)
        if len(picked) == n:
            break
    if len(picked) < 2:
        fail(f'expected at least 2 real skinned draws under {CAPTURES}')
    return picked


def halves(data, off, count):
    return [struct.unpack_from('<e', data, off + 2 * i)[0] for i in range(count)]


def read_vertices(folder):
    """numpy-free decode of POSITION/NORMAL/TEXCOORD/COLOR + bone indices/weights from the capture."""
    meta = json.loads((folder / 'capture.json').read_text())
    lay = [(e['semantic'], e['format'], e['offset'], e.get('slot', 0)) for e in meta['layout']]
    stride = {v['slot']: v['stride'] for v in meta['vertex_buffers']}[0]
    vb = (folder / 'vb_0.bin').read_bytes()
    n = len(vb) // stride
    out = []
    for i in range(n):
        base = i * stride
        pos = normal = uv = (0.0, 0.0, 0.0)
        color = 0xffffffff
        bones = [0, 0, 0, 0]
        weights = [0.0, 0.0, 0.0, 0.0]
        for sem, fmt, off, slot in lay:
            if slot != 0:
                continue
            p = base + off
            if sem == 'POSITION' and fmt == 6:
                pos = struct.unpack_from('<3f', vb, p)
            elif sem == 'NORMAL' and fmt == 6:
                normal = struct.unpack_from('<3f', vb, p)
            elif sem == 'NORMAL' and fmt == 10:
                normal = tuple(halves(vb, p, 3))
            elif sem == 'TEXCOORD' and fmt == 34:
                uv = tuple(halves(vb, p, 2))
            elif sem == 'TEXCOORD' and fmt == 16:
                uv = struct.unpack_from('<2f', vb, p)
            elif sem == 'COLOR' and fmt in (28, 30):
                color = struct.unpack_from('<I', vb, p)[0]
            elif sem == 'BLENDINDICES' and fmt == 30:
                bones = list(struct.unpack_from('<4B', vb, p))
            elif sem == 'BLENDWEIGHT' and fmt == 28:
                weights = [c / 255.0 for c in struct.unpack_from('<4B', vb, p)]
        out.append((pos, normal, uv, color, bones, weights))
    return out


def indices_of(folder):
    meta = json.loads((folder / 'capture.json').read_text())
    raw = (folder / 'ib.bin').read_bytes()
    off = meta['ib_offset'] + meta['start_index'] * FMT[meta['ib_format']]
    count = meta['index_count']
    if meta['ib_format'] == 57:
        return list(struct.unpack_from('<%dH' % count, raw, off))
    return list(struct.unpack_from('<%dI' % count, raw, off))


def palette_of(folder):
    raw = (folder / 'cb_11.bin').read_bytes()
    return [struct.unpack_from('<12f', raw, 48 * i) for i in range(len(raw) // 48)]


def skin(vertex, palette):
    pos, _n, _uv, _c, bones, weights = vertex
    x, y, z = pos
    out = [0.0, 0.0, 0.0]
    for k in range(4):
        w = weights[k]
        if w == 0.0:
            continue
        m = palette[bones[k]]
        for r in range(3):
            out[r] += w * (m[4 * r] * x + m[4 * r + 1] * y + m[4 * r + 2] * z + m[4 * r + 3])
    return out


def close(a, b, tol=2e-4):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


HARNESS = r'''
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#include "skinning_convert.h"

static std::vector<unsigned char> slurp(const char* p) {
    std::vector<unsigned char> b;
    if (FILE* f = std::fopen(p, "rb")) {
        std::fseek(f, 0, SEEK_END); long n = std::ftell(f); std::fseek(f, 0, SEEK_SET);
        b.resize(n > 0 ? static_cast<std::size_t>(n) : 0);
        if (!b.empty() && std::fread(b.data(), 1, b.size(), f) != b.size()) b.clear();
        std::fclose(f);
    }
    return b;
}

int main(int argc, char** argv) {
    // argv: vb ib layout stride start_index index_count bone_count format
    if (argc < 9) return 2;
    const auto vb = slurp(argv[1]), ib = slurp(argv[2]);
    const auto stride = static_cast<unsigned>(std::atoi(argv[4]));
    const auto start = static_cast<std::uint32_t>(std::atoi(argv[5]));
    const auto count = static_cast<std::uint32_t>(std::atoi(argv[6]));
    const auto bones = static_cast<std::uint32_t>(std::atoi(argv[7]));
    const int fmt = std::atoi(argv[8]);
    std::vector<skinning_convert::Element> elements;
    {   // "SEMANTIC:format:offset" triples on one line
        std::string spec(argv[3]);
        std::size_t i = 0;
        while (i < spec.size()) {
            std::size_t j = spec.find(';', i);
            if (j == std::string::npos) j = spec.size();
            const std::string e = spec.substr(i, j - i);
            const std::size_t a = e.find(':'), b = e.find(':', a + 1);
            if (a != std::string::npos && b != std::string::npos)
                elements.push_back({e.substr(0, a), std::atoi(e.substr(a + 1, b - a - 1).c_str()),
                                    static_cast<unsigned>(std::atoi(e.substr(b + 1).c_str()))});
            i = j + 1;
        }
    }
    std::vector<skinning_convert::SkinVertex> out;
    std::vector<std::uint32_t> indices;
    const bool ok = skinning_convert::build(vb.data(), vb.size(), stride, elements, ib.data(), ib.size(), fmt,
                                            start, count, bones, out, indices);
    std::printf("ok=%d count=%zu indices=%zu\n", ok ? 1 : 0, out.size(), indices.size());
    std::printf("i");
    for (std::uint32_t x : indices) std::printf(" %u", x);
    std::printf("\n");
    for (const auto& v : out) {
        std::printf("v %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %u %u %u %u %u %.6f %.6f %.6f %.6f\n",
                    v.position[0], v.position[1], v.position[2], v.normal[0], v.normal[1], v.normal[2],
                    v.texcoord[0], v.texcoord[1], v.color, v.bone[0], v.bone[1], v.bone[2], v.bone[3],
                    v.weight[0], v.weight[1], v.weight[2], v.weight[3]);
    }
    return ok ? 0 : 1;
}
'''


REJECT_HARNESS = r'''
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#include "skinning_convert.h"

int main() {
    // Three vertices, stride 20: POSITION(R32G32B32)@0, BLENDINDICES(R8G8B8A8_UINT)@12, BLENDWEIGHT(R8G8B8A8_UNORM)@16.
    std::vector<unsigned char> vb(60, 0);
    for (int i = 0; i < 3; ++i) {
        float* p = reinterpret_cast<float*>(vb.data() + 20 * i);
        p[0] = float(i); p[1] = 2.f; p[2] = 3.f;
        vb[20 * i + 12] = 0; vb[20 * i + 13] = 1;
        vb[20 * i + 16] = 255;
    }
    std::uint32_t ib[3] = {0, 1, 2};
    std::uint32_t bad_index[3] = {0, 1, 99};
    const std::vector<skinning_convert::Element> full = {
        {"POSITION", 6, 0}, {"BLENDINDICES", 30, 12}, {"BLENDWEIGHT", 28, 16}};
    const auto accepted = [&](const std::vector<unsigned char>& v, unsigned stride,
                              const std::vector<skinning_convert::Element>& e, const void* idx,
                              int fmt, std::uint32_t start, std::uint32_t count, std::uint32_t bones) {
        std::vector<skinning_convert::SkinVertex> out;
        std::vector<std::uint32_t> used;
        const bool ok = skinning_convert::build(v.data(), v.size(), stride, e, static_cast<const unsigned char*>(idx),
                                                sizeof(std::uint32_t) * 3, fmt, start, count, bones, out, used);
        return ok && !out.empty() && !used.empty();
    };
    int failures = 0;
    const auto must_reject = [&](const char* what, bool ok) {
        if (ok) { std::printf("VIOLATION accepted: %s\n", what); ++failures; }
    };

    must_reject("zero stride", accepted(vb, 0, full, ib, 42, 0, 3, 2));
    must_reject("index count not a multiple of 3", accepted(vb, 20, full, ib, 42, 0, 4, 2));
    must_reject("start index beyond the buffer", accepted(vb, 20, full, ib, 42, 8, 3, 2));
    must_reject("unknown index format", accepted(vb, 20, full, ib, 99, 0, 3, 2));
    must_reject("no POSITION", accepted(vb, 20, {{"BLENDINDICES", 30, 12}, {"BLENDWEIGHT", 28, 16}}, ib, 42, 0, 3, 2));
    must_reject("no BLENDINDICES", accepted(vb, 20, {{"POSITION", 6, 0}, {"BLENDWEIGHT", 28, 16}}, ib, 42, 0, 3, 2));
    must_reject("no BLENDWEIGHT", accepted(vb, 20, {{"POSITION", 6, 0}, {"BLENDINDICES", 30, 12}}, ib, 42, 0, 3, 2));
    must_reject("index beyond the vertex buffer", accepted(vb, 20, full, bad_index, 42, 0, 3, 2));
    {
        std::vector<unsigned char> bad = vb;
        bad[12] = 7;  // weighted bone index 7 with a 2-bone palette (unweighted slots are ignored)
        must_reject("bone index beyond the palette", accepted(bad, 20, full, ib, 42, 0, 3, 2));
    }
    must_reject("stride smaller than the declared elements", accepted(vb, 8, full, ib, 42, 0, 3, 2));
    {
        std::vector<skinning_convert::SkinVertex> out;
        std::vector<std::uint32_t> used;
        const bool ok = skinning_convert::build(nullptr, 0, 20, full, reinterpret_cast<const unsigned char*>(ib),
                                                sizeof ib, 42, 0, 3, 2, out, used);
        must_reject("null vertex bytes", ok && !out.empty());
    }
    std::printf("failures=%d\n", failures);
    return failures ? 1 : 0;
}
'''


def run_harness(work, folder):
    meta = json.loads((folder / 'capture.json').read_text())
    spec = ';'.join(f"{e['semantic']}:{e['format']}:{e['offset']}" for e in meta['layout'] if e.get('slot', 0) == 0)
    stride = {v['slot']: v['stride'] for v in meta['vertex_buffers']}[0]
    bones = len((folder / 'cb_11.bin').read_bytes()) // 48
    exe = work / 'harness'
    r = subprocess.run([str(exe), str(folder / 'vb_0.bin'), str(folder / 'ib.bin'), spec, str(stride),
                        str(meta['start_index']), str(meta['index_count']), str(bones), str(meta['ib_format'])],
                       capture_output=True, text=True)
    if 'ok=1' not in r.stdout:
        fail(f'{folder.name}: build() rejected a real skinned draw\n{r.stdout[-800:]}{r.stderr[-800:]}')
    lines = [x for x in r.stdout.splitlines() if x.startswith('v ')]
    compact = [int(x) for x in next(x for x in r.stdout.splitlines() if x.startswith('i ')).split()[1:]]
    verts = []
    for line in lines:
        f = line.split()[1:]
        verts.append(([float(f[0]), float(f[1]), float(f[2])], [float(f[3]), float(f[4]), float(f[5])],
                      [float(f[6]), float(f[7])], int(f[8]), [int(x) for x in f[9:13]],
                      [float(x) for x in f[13:17]]))
    return verts, compact


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if not HEADER.exists():
        fail(f'missing candidate header: {HEADER}')
    draws = pick_draws()
    work = OUT / 'build'
    work.mkdir(exist_ok=True)
    (work / 'harness.cpp').write_text(HARNESS)
    (work / 'reject.cpp').write_text(REJECT_HARNESS)
    r = subprocess.run(['g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(HEADER.parent),
                        str(work / 'harness.cpp'), '-o', str(work / 'harness')], capture_output=True, text=True)
    if r.returncode:
        fail('candidate does not compile:\n' + r.stderr[-2500:])

    checked = 0
    for folder in draws:
        ref = read_vertices(folder)
        idx = indices_of(folder)
        pal = palette_of(folder)
        got, compact = run_harness(work, folder)
        # Only referenced vertices may be uploaded, one copy each, and every triangle must survive.
        assert len(compact) == len(idx), f'{folder.name}: {len(compact)} indices for a {len(idx)}-index draw'
        assert len(got) <= len(set(idx)), f'{folder.name}: {len(got)} vertices for {len(set(idx))} referenced'
        assert len(got) <= len(ref), f'{folder.name}: more vertices than the buffer holds'
        for j in sorted({0, len(idx) // 2, len(idx) - 1}):
            o = idx[j]
            v = got[compact[j]]
            # bind pose must be the raw positions, untouched by any bone or world transform
            if not close(v[0], ref[o][0], 1e-6):
                fail(f'{folder.name}: index {j} (vertex {o}) position is not the raw bind pose: {v[0]} vs {ref[o][0]}')
            # skin data must survive the conversion exactly
            if v[4] != ref[o][4] or not close(v[5], ref[o][5], 1e-6):
                fail(f'{folder.name}: vertex {o} skin data changed: {v[4:]} vs {ref[o][4:]}')
            # independent check: skinning the candidate output reproduces NieR's skinning of the capture
            want, have = skin(ref[o], pal), skin(v, pal)
            if not close(want, have):
                fail(f'{folder.name}: vertex {o} skins to {have}, capture skins to {want}')
            checked += 1
        for k, v in enumerate(got):
            if not close([sum(v[5])], [1.0], 2e-2):
                fail(f'{folder.name}: vertex {k} weights do not sum to 1: {sum(v[5])}')
            if any(b >= len(pal) for b, w in zip(v[4], v[5]) if w > 0.0):
                fail(f'{folder.name}: vertex {k} weighted bone index out of range')

    rejects = OUT / 'build' / 'reject'
    r = subprocess.run(['g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(HEADER.parent),
                        str(work / 'reject.cpp'), '-o', str(rejects)], capture_output=True, text=True)
    if r.returncode:
        fail('candidate cannot be used with the malformed-input harness:\n' + r.stderr[-2500:])
    bad = subprocess.run([str(rejects)], capture_output=True, text=True)
    if bad.returncode or 'VIOLATION' in bad.stdout:
        fail('malformed input was accepted:\n' + (bad.stdout + bad.stderr)[-2000:])
    report = {'passed': True, 'header': str(HEADER), 'real_draws': len(draws), 'skinned_vertices_checked': checked,
              'limits': 'Bind-pose conversion checked against NieR arithmetic on real draws; no GPU, no Remix runtime.'}
    (OUT / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
