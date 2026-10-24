// Native unit test for proxy_patch.h: verifies signatures, cave emission length, and the
// rip-relative disp32/rel32 arithmetic at each of the three cave fragments.
// Build: g++ -std=c++17 -Wall -Wextra -Werror -fsanitize=address,undefined
//        -fno-sanitize-recover=all proxy_patch_test.cpp -o proxy_patch_test
#include "proxy_patch.h"
#include <cassert>
#include <cstdio>
#include <vector>

using namespace proxy_patch;

int main()
{
    const std::uint64_t base = 0x180000000ULL;

    // 1. signatures
    {
        std::vector<std::uint8_t> img(kOutHeightPatchRva + 0x100, 0xcc);
        std::memcpy(img.data() + kOutWidthPatchRva, kOutWidthSig, sizeof(kOutWidthSig));
        std::memcpy(img.data() + kOutHeightPatchRva, kOutHeightSig, sizeof(kOutHeightSig));
        std::memcpy(img.data() + kOutputPatchRva, kOutputSig, sizeof(kOutputSig));
        assert(check_signatures(img.data(), img.size()));
        img[kOutWidthPatchRva + 1] ^= 1;
        assert(!check_signatures(img.data(), img.size()));
        img[kOutWidthPatchRva + 1] ^= 1;
        img[kOutHeightPatchRva + 3] ^= 1;
        assert(!check_signatures(img.data(), img.size()));
        img[kOutHeightPatchRva + 3] ^= 1;
        img[kOutputPatchRva + 2] ^= 1;
        assert(!check_signatures(img.data(), img.size()));
        assert(!check_signatures(nullptr, 0));
        assert(!check_signatures(img.data(), kOutHeightPatchRva)); // too small
    }

    // 2. cave emission
    {
        const std::uint64_t cave_va = 0x200000000ULL; // arbitrary, within +-2GB of 0x180000000
        std::uint8_t buf[kCaveSize];
        const std::size_t n = emit_cave(buf, sizeof(buf), cave_va, base);
        assert(n == 56);
        assert(emit_cave(buf, kCaveSize - 1, cave_va, base) == 0); // cap too small

        auto d32 = [&](std::size_t off) { std::int32_t v; std::memcpy(&v, buf + off, 4); return v; };

        // fragment 1: OutWidth  (mov r8d,[rbp+0x1048] @0; lea @7; jmp @14)
        assert(buf[0] == 0x44 && buf[1] == 0x8b && buf[2] == 0x85 && buf[3] == 0x48);
        assert(buf[7] == 0x48 && buf[8] == 0x8d && buf[9] == 0x15);
        assert(d32(10) == static_cast<std::int32_t>((base + kOutWidthStrRva) - (cave_va + 14)));
        assert(buf[14] == 0xe9);
        assert(d32(15) == static_cast<std::int32_t>((base + kOutWidthReturnRva) - (cave_va + 19)));

        // fragment 2: OutHeight (mov @19; lea @26; jmp @33)
        assert(buf[19] == 0x44 && buf[20] == 0x8b && buf[21] == 0x85 && buf[22] == 0x4c);
        assert(buf[26] == 0x48 && buf[27] == 0x8d && buf[28] == 0x15);
        assert(d32(29) == static_cast<std::int32_t>((base + kOutHeightStrRva) - (cave_va + 33)));
        assert(buf[33] == 0xe9);
        assert(d32(34) == static_cast<std::int32_t>((base + kOutHeightReturnRva) - (cave_va + 38)));

        // fragment 3: Output texture (mov r8d,[rip+H] @38; mov edx,[rip+W] @45; jmp @51)
        assert(buf[38] == 0x44 && buf[39] == 0x8b && buf[40] == 0x05);
        assert(d32(41) == static_cast<std::int32_t>((base + kNativeHRva) - (cave_va + 45)));
        assert(buf[45] == 0x8b && buf[46] == 0x15);
        assert(d32(47) == static_cast<std::int32_t>((base + kNativeWRva) - (cave_va + 51)));
        assert(buf[51] == 0xe9);
        assert(d32(52) == static_cast<std::int32_t>((base + kOutputReturnRva) - (cave_va + 56)));
    }

    // 3. jump emission
    {
        std::uint8_t j[5];
        const std::uint64_t from = 0x180018791ULL, to = 0x200000000ULL;
        assert(emit_jump(j, from, to) == 5);
        assert(j[0] == 0xe9);
        std::int32_t rel;
        std::memcpy(&rel, j + 1, 4);
        assert(static_cast<std::int64_t>(rel) == static_cast<std::int64_t>(to - (from + 5)));
    }

    std::puts("proxy_patch_test: all passed");
    return 0;
}
