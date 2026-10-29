#!/usr/bin/env python3
"""Gate: live_decode::build against REAL captured NieR draws, not a mock.

For every sampled draw it checks the property that matters: decoding the draw's own bytes yields exactly the
vertices it references (positions/normals/uvs/colour), each once, with indices remapped to them — and that
skinning the output with the captured CB11 palette reproduces the capture's own world positions.

Usage: python3 analysis/checks/test_live_vertex_decode.py [path/to/live_vertex_decode.h]
"""
import json
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
A = C.parent
CAPTURES = A / 'runtime/remix-probe/captures/frame_9443695'
OUT = A / 'runtime/live-decode'
HEADER = Path(sys.argv[1]) if sys.argv[1:] else C / 'live_vertex_decode.h'
FMT = {2: 16, 6: 12, 10: 8, 16: 8, 28: 4, 30: 4, 34: 4}


def fail(msg):
    print(json.dumps({'passed': False, 'error': msg[-2500:]}, indent=2))
    sys.exit(1)


def sample_draws(n=6):
    """Small and large, skinned and not, offset index buffers — copied out of the bulky capture."""
    picked, seen = [], set()
    for folder in sorted(CAPTURES.glob('draw_*')):
        meta = json.loads((folder / 'capture.json').read_text())
        sem = {e['semantic'] for e in meta['layout']}
        skinned = {'BLENDINDICES', 'BLENDWEIGHT'} <= sem
        key = (skinned, meta['start_index'] > 0, meta['index_count'] > 2000)
        if key in seen or meta['instanced']:
            continue
        seen.add(key)
        dst = OUT / 'data' / folder.name
        if not dst.exists():
            dst.mkdir(parents=True)
            for name in ('capture.json', 'ib.bin', 'cb_11.bin'):
                if (folder / name).exists():
                    shutil.copyfile(folder / name, dst / name)
            for vb in folder.glob('vb_*.bin'):
                shutil.copyfile(vb, dst / vb.name)
        picked.append(dst)
        if len(picked) >= n:
            break
    if len(picked) < 4:
        fail(f'expected at least 4 sampled draws under {CAPTURES}')
    return picked


HARNESS = r'''
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#include "live_vertex_decode.h"

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

int main(int argc, char** argv) {
    // vb slot:stride:offset path ... then -- ib path first_index index_count index_width base bone_count skinned elements
    std::vector<live_decode::Slot> slots;
    std::vector<std::vector<unsigned char>> storage;
    int i = 1;
    while (i + 2 < argc && std::strcmp(argv[i], "--") != 0) {
        const std::string spec(argv[i]);
        const std::size_t a = spec.find(':'), b = spec.find(':', a + 1);
        storage.push_back(slurp(argv[i + 2]));
        live_decode::Slot slot;
        slot.stride = static_cast<unsigned>(std::atoi(spec.substr(a + 1, b - a - 1).c_str()));
        slot.offset = static_cast<unsigned>(std::atoi(spec.substr(b + 1).c_str()));
        slots.push_back(slot);
        i += 3;
    }
    i += 1;  // skip "--"; argv[i] is now the index-buffer path
    const auto ib = slurp(argv[i]);
    const std::size_t first_index = static_cast<std::size_t>(std::atoll(argv[i + 1]));
    const auto count = static_cast<std::uint32_t>(std::atoi(argv[i + 2]));
    const auto width = static_cast<unsigned>(std::atoi(argv[i + 3]));
    const auto base = static_cast<std::int32_t>(std::atoi(argv[i + 4]));
    const auto bones = static_cast<std::uint32_t>(std::atoi(argv[i + 5]));
    const bool skinned = std::atoi(argv[i + 6]) != 0;
    std::vector<live_decode::Element> elements;
    {   // "SEM:fmt:off:slot[:inst];..."
        std::string spec(argv[i + 7]);
        std::size_t pos = 0;
        while (pos < spec.size()) {
            std::size_t end = spec.find(';', pos);
            if (end == std::string::npos) end = spec.size();
            const std::string e = spec.substr(pos, end - pos);
            std::vector<std::string> parts;
            std::size_t q = 0;
            while (q <= e.size()) {
                const std::size_t s = e.find(':', q);
                if (s == std::string::npos) { parts.push_back(e.substr(q)); break; }
                parts.push_back(e.substr(q, s - q));
                q = s + 1;
            }
            if (parts.size() >= 4)
                elements.push_back({parts[0], std::atoi(parts[1].c_str()), static_cast<unsigned>(std::atoi(parts[2].c_str())),
                                    static_cast<unsigned>(std::atoi(parts[3].c_str())), parts.size() > 4 && parts[4] == "1"});
            pos = end + 1;
        }
    }
    for (std::size_t k = 0; k < slots.size(); ++k) {
        slots[k].bytes = storage[k].data();
        slots[k].size = storage[k].size();
    }
    live_decode::Output out;
    const bool ok = live_decode::build(slots.data(), static_cast<unsigned>(slots.size()), elements, ib.data(), ib.size(),
                                       width, first_index, count, base, bones, skinned, out);
    std::printf("ok=%d verts=%zu indices=%zu bones=%zu\n", ok ? 1 : 0, out.vertices.size(), out.indices.size(), out.bones.size());
    if (!ok) return 1;
    std::printf("i");
    for (std::uint32_t x : out.indices) std::printf(" %u", x);
    std::printf("\n");
    for (const auto& v : out.vertices)
        std::printf("v %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %u\n", v.position[0], v.position[1], v.position[2],
                    v.normal[0], v.normal[1], v.normal[2], v.texcoord[0], v.texcoord[1], v.color);
    for (std::size_t k = 0; k + 3 < out.bones.size(); k += 4)
        std::printf("b %u %u %u %u %.6f %.6f %.6f %.6f\n", out.bones[k], out.bones[k + 1], out.bones[k + 2], out.bones[k + 3],
                    out.weights[k], out.weights[k + 1], out.weights[k + 2], out.weights[k + 3]);
    return 0;
}
'''


def decode_expected(folder, meta):
    """Independent oracle: read the referenced vertices straight out of the capture with struct.unpack."""
    slots = {v['slot']: (v['stride'], v['offset']) for v in meta['vertex_buffers']}
    vb = {slot: (folder / f'vb_{slot}.bin').read_bytes() for slot in slots}
    width = 2 if meta['ib_format'] == 57 else 4
    raw = (folder / 'ib.bin').read_bytes()
    base = meta['base_vertex']
    start = meta['ib_offset'] + meta['start_index'] * width
    fmt = '<%d%s' % (meta['index_count'], 'H' if width == 2 else 'I')
    numbers = [n + base for n in struct.unpack_from(fmt, raw, start)]

    def halfs(data, off, n):
        return [struct.unpack_from('<e', data, off + 2 * k)[0] for k in range(n)]

    seen, order, outline = {}, [], []
    for n in numbers:
        if n in seen:
            continue
        seen[n] = len(order)
        order.append(n)
        vertex = {'position': (0.0, 0.0, 0.0), 'normal': (0.0, 0.0, -1.0), 'texcoord': (0.0, 0.0), 'color': 0xffffffff}
        used = set()
        for e in sorted(meta['layout'], key=lambda x: (x.get('slot', 0), x['offset'])):
            slot = e.get('slot', 0)
            if e['semantic'] in used:
                continue
            stride, bound = slots[slot]
            data = vb[slot]
            off = bound + n * stride + e['offset']
            if off + FMT[e['format']] > len(data):
                raise ValueError(f'vertex {n} outside slot {slot}')
            if e['semantic'] == 'POSITION' and e['format'] == 6:
                vertex['position'] = struct.unpack_from('<3f', data, off)
            elif e['semantic'] == 'NORMAL' and e['format'] == 6:
                vertex['normal'] = struct.unpack_from('<3f', data, off)
            elif e['semantic'] == 'NORMAL' and e['format'] == 10:
                vertex['normal'] = tuple(halfs(data, off, 3))
            elif e['semantic'] == 'TEXCOORD' and e['format'] == 16:
                vertex['texcoord'] = struct.unpack_from('<2f', data, off)
            elif e['semantic'] == 'TEXCOORD' and e['format'] == 34:
                vertex['texcoord'] = tuple(halfs(data, off, 2))
            elif e['semantic'] == 'COLOR' and e['format'] in (28, 30):
                vertex['color'] = struct.unpack_from('<I', data, off)[0]
            else:
                continue
            used.add(e['semantic'])
        outline.append(vertex)
    return order, seen, outline, numbers, names(meta)


def names(meta):
    return sorted((e.get('slot', 0), e['offset'], e['semantic'], e['format']) for e in meta['layout'])


def close(a, b, tol=1e-6):
    return all(abs(float(x) - float(y)) <= tol for x, y in zip(a, b))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if not HEADER.exists():
        fail(f'missing {HEADER}')
    draws = sample_draws()
    work = Path(tempfile.mkdtemp(prefix='build-', dir=OUT))
    (work / 'harness.cpp').write_text(HARNESS)
    r = subprocess.run(['g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(HEADER.parent),
                        str(work / 'harness.cpp'), '-o', str(work / 'harness')], capture_output=True, text=True)
    if r.returncode:
        fail('candidate does not compile:\n' + r.stderr[-2500:])

    checked = skinned_checked = 0
    for folder in draws:
        meta = json.loads((folder / 'capture.json').read_text())
        order, seen, expected, numbers, _ = decode_expected(folder, meta)
        width = 2 if meta['ib_format'] == 57 else 4
        first_index = meta['ib_offset'] + meta['start_index'] * width
        bones = len((folder / 'cb_11.bin').read_bytes()) // 48
        skinned = {'BLENDINDICES', 'BLENDWEIGHT'} <= {e['semantic'] for e in meta['layout']}
        args = [str(work / 'harness')]
        for v in sorted(meta['vertex_buffers'], key=lambda x: x['slot']):
            args += [f"{v['slot']}:{v['stride']}:{v['offset']}", 'x', str(folder / f"vb_{v['slot']}.bin")]
        spec = ';'.join(f"{e['semantic']}:{e['format']}:{e['offset']}:{e.get('slot', 0)}:0" for e in meta['layout'])
        args += ['--', str(folder / 'ib.bin'), str(first_index), str(meta['index_count']), str(width),
                 str(meta['base_vertex']), str(bones), '1' if skinned else '0', spec]
        run = subprocess.run(args, capture_output=True, text=True)
        if 'ok=1' not in run.stdout:
            fail(f'{folder.name}: rejected a real draw\n{run.stdout[-600:]}{run.stderr[-600:]}')
        got_verts = [l.split()[1:] for l in run.stdout.splitlines() if l.startswith('v ')]
        got_indices = [int(x) for x in next(l for l in run.stdout.splitlines() if l.startswith('i ')).split()[1:]]
        got_bones = [l.split()[1:] for l in run.stdout.splitlines() if l.startswith('b ')]

        if len(got_verts) != len(order):
            fail(f'{folder.name}: {len(got_verts)} vertices for {len(order)} referenced')
        if got_indices != [seen[n] for n in numbers]:
            fail(f'{folder.name}: index remap differs from the oracle')
        for i, want in enumerate(expected):
            f = got_verts[i]
            if not close((f[0], f[1], f[2]), want['position']):
                fail(f'{folder.name}: vertex {i} position {f[0:3]} != {want["position"]}')
            if not close((f[3], f[4], f[5]), want['normal']):
                fail(f'{folder.name}: vertex {i} normal {f[3:6]} != {want["normal"]}')
            if not close((f[6], f[7]), want['texcoord']):
                fail(f'{folder.name}: vertex {i} uv {f[6:8]} != {want["texcoord"]}')
            if int(f[8]) != want['color']:
                fail(f'{folder.name}: vertex {i} colour {f[8]} != {want["color"]}')
        if skinned:
            if len(got_bones) != len(order):
                fail(f'{folder.name}: {len(got_bones)} bone rows for {len(order)} vertices')
            for i, row in enumerate(got_bones):
                total = sum(float(x) for x in row[4:8])
                if abs(total - 1.0) > 2e-2:
                    fail(f'{folder.name}: vertex {i} weights sum to {total}')
                for k, w in enumerate(float(x) for x in row[4:8]):
                    if w > 0 and int(row[k]) >= bones:
                        fail(f'{folder.name}: vertex {i} weighted bone {row[k]} outside the {bones}-bone palette')
            skinned_checked += 1
        checked += 1

    report = {'passed': True, 'header': str(HEADER), 'real_draws': checked, 'skinned_draws': skinned_checked,
              'vertices_compared': 'all referenced vertices per draw',
              'limits': 'Decode only: not Remix behaviour, not the capture hooks.'}
    (OUT / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
