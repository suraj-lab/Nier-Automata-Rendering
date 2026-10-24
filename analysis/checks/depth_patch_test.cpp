// Native unit test for depth_patch.h: emits the cave + jump and checks the fixed opcodes,
// the EFLAGS-preservation pushfq/popfq, the rel8 branch targets, and the variable
// rel32/disp32 displacements. Also verifies signature checks.
// Build: g++ -std=c++17 -Wall -Wextra -Werror -fsanitize=address,undefined
//        -fno-sanitize-recover=all depth_patch_test.cpp -o depth_patch_test
#include "depth_patch.h"
#include <cassert>
#include <cstdio>
#include <vector>

using namespace depth_patch;

int main()
{
    // 1. signatures
    {
        std::vector<std::uint8_t> img(kReturnRva + 0x100, 0xcc);
        std::memcpy(img.data() + kPrologueRva, kPrologueSig, sizeof(kPrologueSig));
        std::memcpy(img.data() + kPatchRva, kPatchSig, sizeof(kPatchSig));
        assert(check_signatures(img.data(), img.size()));
        img[kPatchRva + 1] ^= 1;                          // corrupt patch point
        assert(!check_signatures(img.data(), img.size()));
        img[kPatchRva + 1] ^= 1;
        img[kPrologueRva + 3] ^= 1;                       // corrupt prologue
        assert(!check_signatures(img.data(), img.size()));
        assert(!check_signatures(nullptr, 0));
        assert(!check_signatures(img.data(), kPatchRva)); // too small
    }

    // 2. cave emission with small, clean addresses
    {
        const std::uint64_t cave_va = 0x1000, renderer_va = 0x2000, return_va = 0x3000;
        std::uint8_t buf[kCaveSize];
        const std::size_t n = emit_cave(buf, sizeof(buf), cave_va, renderer_va, return_va);
        assert(n == 96);
        assert(emit_cave(buf, kCaveSize - 1, cave_va, renderer_va, return_va) == 0); // cap too small

        // EFLAGS preservation
        assert(buf[0] == 0x9c);   // pushfq
        assert(buf[90] == 0x9d);  // popfq
        assert(buf[91] == 0xe9);  // jmp

        // fixed opcodes (spot checks at key offsets)
        assert(buf[1] == 0x48 && buf[2] == 0x8b && buf[3] == 0x15);       // mov rdx,[rip+disp32]
        assert(buf[8] == 0x48 && buf[9] == 0x85 && buf[10] == 0xd2);      // test rdx,rdx
        assert(buf[11] == 0x74 && buf[12] == 0x47);                       // je .skip
        assert(buf[13] == 0xf3 && buf[14] == 0x0f && buf[15] == 0x10);    // movss xmm1,[rdx+0x80]
        assert(buf[16] == 0x8a && buf[17] == 0x80);                       //  [rdx+disp32=0x80]
        assert(buf[55] == 0xf3 && buf[56] == 0x0f && buf[57] == 0x2a);    // cvtsi2ss xmm2,ecx
        assert(buf[79] == 0x89 && buf[80] == 0x0b);                       // mov [rbx],ecx
        assert(buf[84] == 0x89 && buf[85] == 0x4d && buf[86] == 0xc0);    // mov [rbp-0x40],ecx

        // rel8 branch targets (decode each: next_off + rel8 == label offset)
        auto rel8_target = [&](std::size_t rel8_off) {
            return (int)rel8_off + 1 + (int)(std::int8_t)buf[rel8_off];
        };
        assert(rel8_target(12) == 84);  // je  .skip
        assert(rel8_target(25) == 31);  // jne .try_half
        assert(rel8_target(30) == 55);  // je  .scale
        assert(rel8_target(42) == 84);  // jne .skip
        assert(rel8_target(54) == 84);  // jne .skip

        // disp32 at offset 4 -> renderer_va - (cave_va+8)
        std::int32_t disp;
        std::memcpy(&disp, buf + 4, 4);
        assert(static_cast<std::int64_t>(disp) == static_cast<std::int64_t>(renderer_va - (cave_va + 8)));
        // rel32 at offset 92 -> return_va - (cave_va+96)
        std::int32_t rel;
        std::memcpy(&rel, buf + 92, 4);
        assert(static_cast<std::int64_t>(rel) == static_cast<std::int64_t>(return_va - (cave_va + 96)));
    }

    // 3. jump emission
    {
        std::uint8_t j[5];
        const std::uint64_t from = 0x14025904eULL, to = 0x142000000ULL;
        assert(emit_jump(j, from, to) == 5);
        assert(j[0] == 0xe9);
        std::int32_t rel;
        std::memcpy(&rel, j + 1, 4);
        assert(static_cast<std::int64_t>(rel) == static_cast<std::int64_t>(to - (from + 5)));
    }

    std::puts("depth_patch_test: all passed");
    return 0;
}
