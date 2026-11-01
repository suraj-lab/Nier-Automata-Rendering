#!/usr/bin/env python3
"""Gate: a refused decode names its cause, and transient causes are distinguished from structural ones.

Live evidence this exists for: `decode_failed` ran 100-375 per window and each one *permanently* removed an object
(the capture marked it built and never retried). Which refusal it was decides the fix, so the refusal must be named.
"""
import json
import subprocess
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
HARNESS = r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include "live_vertex_decode.h"

using namespace live_decode;

// One POSITION-only slot, 3 vertices of 12 bytes, and a triangle index buffer.
struct Fixture {
    std::vector<unsigned char> vb;   // 3 x float3
    std::vector<unsigned char> ib;   // 3 x uint32
    std::vector<Element> elements;
    Slot slots[1];
    Fixture() {
        vb.resize(36);
        for (int i = 0; i < 3; ++i) {
            const float p[3] = {static_cast<float>(i), 0.f, 0.f};
            std::memcpy(vb.data() + i * 12, p, 12);
        }
        ib.resize(12);
        for (unsigned i = 0; i < 3; ++i) std::memcpy(ib.data() + i * 4, &i, 4);
        elements = {Element{"POSITION", 6, 0, 0, false}};
        slots[0] = Slot{vb.data(), vb.size(), 12, 0};
    }
    bool build(Output& out, Failure& why, unsigned width = 4, std::size_t first = 0,
               std::uint32_t count = 3, std::int32_t base = 0, std::uint32_t bones = 0, bool skinned = false) {
        return live_decode::build(slots, 1, elements, ib.data(), ib.size(), width, first, count, base, bones, skinned,
                                  out, &why);
    }
};

int main() {
    Failure why = Failure::None;
    Output out;
    {
        Fixture f;
        assert(f.build(out, why) && why == Failure::None && out.vertices.size() == 3 && out.indices.size() == 3);
    }
    {   // The index buffer is shorter than the draw claims: what a buffer caught mid-write looks like.
        Fixture f;
        assert(!f.build(out, why, 4, 0, 300));
        assert(why == Failure::IndexBytesShort && transient(why));
    }
    {   // A vertex the index buffer points at is past the end of the bound slot.
        Fixture f;
        std::uint32_t big = 99;
        std::memcpy(f.ib.data() + 4, &big, 4);
        assert(!f.build(out, why));
        assert(why == Failure::VertexOutOfRange && transient(why));
    }
    {   // Structural refusals: never transient, so the capture may stop retrying them.
        Fixture f;
        f.elements = {Element{"POSITION", 999, 0, 0, false}};
        assert(!f.build(out, why) && why == Failure::UnsupportedFormat && !transient(why));
        f = Fixture{};
        f.elements = {Element{"TEXCOORD", 34, 0, 0, false}};
        assert(!f.build(out, why) && why == Failure::NoPosition && !transient(why));
        f = Fixture{};
        f.elements = {Element{"POSITION", 6, 8, 0, false}};   // 12-byte element at offset 8 of a 12-byte stride
        assert(!f.build(out, why) && why == Failure::BadStride && !transient(why));
    }
    {   // Bad arguments keep their own names instead of collapsing into one anonymous false.
        Fixture f;
        assert(!f.build(out, why, 3));
        assert(why == Failure::BadIndexWidth && !transient(why));
        assert(!f.build(out, why, 4, 0, 4));                  // 4 indices is not triangles
        assert(why == Failure::InvalidInput);
        assert(!f.build(out, why, 4, 0, 3, -99));             // base_vertex drives the index negative
        assert(why == Failure::IndexBaseOutOfRange);
    }
    {   // A null slot is transient: the binding can be wrong for one frame while the game rebuilds it.
        Fixture f;
        f.slots[0].bytes = nullptr;
        assert(!f.build(out, why) && why == Failure::SlotMissing && transient(why));
    }

    {   // The family that produced every no_position refusal live: float4 POSITION/TEXCOORD/COLOR, stride 48.
        Fixture f;
        f.vb.assign(3 * 48, 0);
        for (int i = 0; i < 3; ++i) {
            float pos[4] = {static_cast<float>(i), 2.f, 3.f, 1.f};
            float uv[4] = {0.25f, 0.75f, 0.f, 0.f};
            float col[4] = {1.f, 0.5f, 0.f, 1.f};
            std::memcpy(f.vb.data() + i * 48 + 0, pos, 16);
            std::memcpy(f.vb.data() + i * 48 + 16, uv, 16);
            std::memcpy(f.vb.data() + i * 48 + 32, col, 16);
        }
        f.slots[0] = Slot{f.vb.data(), f.vb.size(), 48, 0};
        f.elements = {Element{"POSITION", 2, 0, 0, false}, Element{"TEXCOORD", 2, 16, 0, false},
                      Element{"COLOR", 2, 32, 0, false}};
        assert(f.build(out, why) && why == Failure::None);
        assert(out.vertices.size() == 3);
        assert(out.vertices[1].position[0] == 1.f && out.vertices[1].position[1] == 2.f);
        assert(out.vertices[0].texcoord[0] == 0.25f && out.vertices[0].texcoord[1] == 0.75f);
        assert(out.vertices[0].color == 0xff0080ffu);   // float4 RGBA -> bytes, little-endian
    }
    {   // The rare half4 variant of the same family.
        Fixture f;
        f.vb.assign(3 * 32, 0);
        for (int i = 0; i < 3; ++i) {
            const std::uint16_t half_ones[4] = {0x3C00, 0x3C00, 0x3C00, 0x3C00};  // 1.0h
            std::memcpy(f.vb.data() + i * 32, half_ones, 8);
            std::memcpy(f.vb.data() + i * 32 + 16, half_ones, 4);
        }
        f.slots[0] = Slot{f.vb.data(), f.vb.size(), 32, 0};
        f.elements = {Element{"POSITION", 10, 0, 0, false}, Element{"TEXCOORD", 10, 16, 0, false}};
        assert(f.build(out, why) && why == Failure::None);
        assert(out.vertices[0].position[0] == 1.f && out.vertices[0].texcoord[1] == 1.f);
    }
    {   // Every reason has a stable non-empty label, and None is not called a failure.
        for (unsigned i = 0; i < static_cast<unsigned>(Failure::Count); ++i)
            assert(failure_name(static_cast<Failure>(i))[0]);
        assert(std::strcmp(failure_name(Failure::None), "none") == 0);
        assert(std::strcmp(failure_name(Failure::VertexOutOfRange), "vertex_out_of_range") == 0);
    }
    std::puts("named refusals, transient vs structural, argument checks, labels");
}
'''


def main():
    try:
        with tempfile.TemporaryDirectory(prefix='decode-fail-') as d:
            d = Path(d)
            (d / 'test.cpp').write_text(HARNESS)
            p = subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                                '-I', str(C), str(d / 'test.cpp'), '-o', str(d / 'test')],
                               capture_output=True, text=True)
            assert p.returncode == 0, 'compile:\n' + p.stderr[-3000:]
            p = subprocess.run([str(d / 'test')], capture_output=True, text=True)
            assert p.returncode == 0, 'run:\n' + (p.stdout + p.stderr)[-3000:]
        # Real captured draws must still decode, and now report why if they do not.
        real = subprocess.run(['python3', str(C / 'test_live_vertex_decode.py')], capture_output=True, text=True)
        assert real.returncode == 0, 'real captured draws regressed:\n' + (real.stdout + real.stderr)[-2000:]
        print(json.dumps({'passed': True, 'checks': p.stdout.strip(),
                          'real_data': 'test_live_vertex_decode.py still passes'}))
    except Exception as e:
        print(json.dumps({'passed': False, 'error': str(e)[-2500:]}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
