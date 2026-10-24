// Native unit test for proxy_patch.h (frozen gate for the upscale cave).
//  1. signatures (all four sites, incl. the 56-byte gate block)
//  2. cave layout + rip-relative disp32/rel32 arithmetic for every fragment and data slot
//  3. jump emission and the apply-order table (gate last)
//  4. EXECUTES both gate fragments (dispatch gate 0, depth-capture gate 0b) on x86-64 Linux: a
//     trampoline fakes rbp/rsp, pass/skip stubs report the branch taken. Checks tolerance (<1px),
//     shared scale slot, NaN -> skip.
// Build: g++ -std=c++17 -Wall -Wextra -Werror -fsanitize=address,undefined
//        -fno-sanitize-recover=all proxy_patch_test.cpp -o proxy_patch_test
#include "proxy_patch.h"
#include <cassert>
#include <cmath>
#include <cstdio>
#include <sys/mman.h>
#include <vector>

using namespace proxy_patch;

static std::int32_t rd32(const std::uint8_t* p) { std::int32_t v; std::memcpy(&v, p, 4); return v; }
static bool rel_to(const std::uint8_t* buf, std::size_t off, std::uint64_t cave_va, std::uint64_t target)
{   // disp32 at buf[off] is relative to the end of the 4-byte field (all our uses end at off+4)
    return static_cast<std::int64_t>(rd32(buf + off)) == static_cast<std::int64_t>(target - (cave_va + off + 4));
}

// --- exit-hook target: MS x64 ABI like the setter's on_dispatch_exit ---
static void* g_seen_ctx = nullptr;
static std::uintptr_t g_seen_frame = 0;
static int g_calls = 0;
__attribute__((ms_abi, noinline, no_sanitize("address")))
static void fake_on_dispatch_exit(void* ctx)
{
    g_seen_ctx = ctx;
    g_seen_frame = reinterpret_cast<std::uintptr_t>(__builtin_frame_address(0));
    ++g_calls;
    // clobber every MS-volatile GPR the cave promises to preserve
    asm volatile("mov $0xdead, %%rax; mov $0xdead, %%rcx; mov $0xdead, %%rdx;"
                 "mov $0xdead, %%r8; mov $0xdead, %%r9; mov $0xdead, %%r10; mov $0xdead, %%r11"
                 ::: "rax", "rcx", "rdx", "r8", "r9", "r10", "r11", "memory");
}

// --- execution harness ---
struct Exec {
    std::uint8_t* region = nullptr;
    static constexpr std::size_t kSize = 0x8000;   // top 0x3000 bytes double as a fake stack
    static constexpr std::size_t kTramp = 0x0;     // trampoline + stubs
    static constexpr std::size_t kCave  = 0x1000;  // 16-aligned
    static constexpr std::size_t kTramp2 = 0x80;   // trampoline for the depth gate
    // fake image base so all pass/skip RVAs land inside the region:
    // gate 0 at +0x5f2/+0x680, depth gate at +0x36dc/+0x378f (cave lives at +0x1000..+0x1140)
    std::uint64_t image_base() const { return reinterpret_cast<std::uint64_t>(region) - 0x17000; }
    using Fn = int (*)(void* frame_rbp, void* fake_rsp);
    Fn fn = nullptr, fn_depth = nullptr;
    static constexpr std::size_t kTramp3 = 0xc0;   // trampoline for the exit hook
    using ExitFn = std::uint64_t (*)(void* frame_rbp, void* fake_rsp, void* ctx, std::uint64_t sentinel);
    ExitFn fn_exit = nullptr;

    bool init()
    {
        void* p = mmap(nullptr, kSize, PROT_READ | PROT_WRITE | PROT_EXEC, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (p == MAP_FAILED) return false;
        region = static_cast<std::uint8_t*>(p);
        std::memset(region, 0xcc, kSize);
        const std::uint64_t rva_base = reinterpret_cast<std::uint64_t>(region);
        const std::uint64_t pass = image_base() + kGatePassRva, skip = image_base() + kGateSkipRva;
        const std::uint64_t dpass = image_base() + kDepthGatePassRva, dskip = image_base() + kDepthGateSkipRva;
        assert(pass > rva_base + 0x100 && skip + 8 < rva_base + kCave);
        assert(dpass > rva_base + kCave + kCaveSize && dskip + 8 < rva_base + kSize);
        const std::uint64_t done = rva_base + 0x40;
        auto put = [&](std::uint64_t at, std::initializer_list<std::uint8_t> xs) {
            std::uint8_t* d = reinterpret_cast<std::uint8_t*>(at);
            for (auto x : xs) *d++ = x;
            return at + xs.size();
        };
        auto jmp = [&](std::uint64_t at, std::uint64_t to) {
            const std::int32_t r = static_cast<std::int32_t>(to - (at + 5));
            std::uint8_t* d = reinterpret_cast<std::uint8_t*>(at);
            d[0] = 0xe9; std::memcpy(d + 1, &r, 4);
        };
        // trampoline (SysV: rdi=frame rbp, rsi=fake rsp)
        std::uint64_t at = put(rva_base + kTramp, {0x55, 0x53,             // push rbp; push rbx
                                                   0x48, 0x89, 0xe3,       // mov rbx,rsp
                                                   0x48, 0x89, 0xfd,       // mov rbp,rdi
                                                   0x48, 0x89, 0xf4});     // mov rsp,rsi
        jmp(at, rva_base + kCave + kFragGate);
        at = put(rva_base + kTramp2, {0x55, 0x53, 0x48, 0x89, 0xe3, 0x48, 0x89, 0xfd, 0x48, 0x89, 0xf4});
        jmp(at, rva_base + kCave + kFragDepthGate);
        put(done, {0x48, 0x89, 0xdc, 0x5b, 0x5d, 0xc3});                    // mov rsp,rbx; pop rbx; pop rbp; ret
        for (std::uint64_t p : {pass, dpass}) { at = put(p, {0xb8, 0x01, 0x00, 0x00, 0x00}); jmp(at, done); } // eax=1
        for (std::uint64_t s : {skip, dskip}) { at = put(s, {0x31, 0xc0}); jmp(at, done); }                   // eax=0
        fn = reinterpret_cast<Fn>(region + kTramp);
        fn_depth = reinterpret_cast<Fn>(region + kTramp2);

        // exit hook: rdi=frame rbp, rsi=fake rsp, rdx=ctx, rcx=sentinel -> rbp, rsp, rdi=ctx, r8=sentinel
        at = put(rva_base + kTramp3, {0x55, 0x53, 0x48, 0x89, 0xe3, 0x48, 0x89, 0xfd, 0x48, 0x89, 0xf4,
                                      0x48, 0x89, 0xd7,            // mov rdi,rdx
                                      0x49, 0x89, 0xc8});          // mov r8,rcx
        jmp(at, rva_base + kCave + kFragExitHook);
        // stub at the original continuation (call __security_check_cookie): return rcx ^ r8
        const std::uint64_t ret = image_base() + kExitReturnRva;
        assert(ret > skip + 8 && ret + 16 < rva_base + kCave);
        at = put(ret, {0x48, 0x89, 0xc8, 0x4c, 0x31, 0xc0});           // mov rax,rcx; xor rax,r8
        jmp(at, done);
        fn_exit = reinterpret_cast<ExitFn>(region + kTramp3);
        return true;
    }

    bool load_cave(float scale, std::uint64_t exit_fn = 1)
    {
        std::uint8_t* cave = region + kCave;
        if (emit_cave(cave, kCaveSize, reinterpret_cast<std::uint64_t>(cave), image_base(), exit_fn) != kCaveSize)
            return false;
        std::memcpy(cave + kScaleOff, &scale, 4);
        return true;
    }

    // returns 1 = pass (dispatch FSR4), 0 = skip
    int gate(std::uint32_t scene_w, std::uint32_t scene_h, float cam_w, float cam_h)
    {
        alignas(16) std::uint8_t frame[0x40] = {};
        alignas(16) std::uint8_t stack[0x100] = {};
        std::memcpy(frame + 0x20, &scene_w, 4);
        std::memcpy(frame + 0x24, &scene_h, 4);
        std::memcpy(stack + 0x78, &cam_w, 4);
        std::memcpy(stack + 0x7c, &cam_h, 4);
        return fn(frame, stack);
    }

    // depth-capture gate: texture W/H at [rsp+0x48/0x4c], camera W/H at [rbp-0x78/-0x74]
    int depth_gate(std::uint32_t tex_w, std::uint32_t tex_h, float cam_w, float cam_h)
    {
        alignas(16) std::uint8_t frame[0x100] = {};
        alignas(16) std::uint8_t stack[0x100] = {};
        std::uint8_t* rbp = frame + 0x80;
        std::memcpy(stack + 0x48, &tex_w, 4);
        std::memcpy(stack + 0x4c, &tex_h, 4);
        std::memcpy(rbp - 0x78, &cam_w, 4);
        std::memcpy(rbp - 0x74, &cam_h, 4);
        return fn_depth(rbp, stack);
    }
};

int main()
{
    const std::uint64_t base = 0x180000000ULL;

    // 1. signatures
    {
        std::vector<std::uint8_t> img(kDepthGatePatchRva + 0x100, 0xcc);
        std::memcpy(img.data() + kOutWidthPatchRva, kOutWidthSig, sizeof(kOutWidthSig));
        std::memcpy(img.data() + kOutHeightPatchRva, kOutHeightSig, sizeof(kOutHeightSig));
        std::memcpy(img.data() + kOutputPatchRva, kOutputSig, sizeof(kOutputSig));
        std::memcpy(img.data() + kGatePatchRva, kGateSig, sizeof(kGateSig));
        std::memcpy(img.data() + kDepthGatePatchRva, kDepthGateSig, sizeof(kDepthGateSig));
        std::memcpy(img.data() + kExitPatchRva, kExitSig, sizeof(kExitSig));
        std::memcpy(img.data() + kCopyBackPatchRva, kCopyBackSig, sizeof(kCopyBackSig));
        assert(check_signatures(img.data(), img.size()));
        for (std::size_t rva : {kOutWidthPatchRva + 1, kOutHeightPatchRva + 3, kOutputPatchRva + 2,
                                kGatePatchRva + 0, kGatePatchRva + 0x2b /* last ucomiss disp */,
                                kDepthGatePatchRva + 3, kDepthGatePatchRva + 0x2b,
                                kExitPatchRva + 3, kExitPatchRva + 6, kCopyBackPatchRva + 2}) {
            img[rva] ^= 1;
            assert(!check_signatures(img.data(), img.size()));
            img[rva] ^= 1;
        }
        assert(check_signatures(img.data(), img.size()));
        assert(!check_signatures(nullptr, 0));
        assert(!check_signatures(img.data(), kOutHeightPatchRva)); // too small
        assert(!check_signatures(img.data(), kDepthGatePatchRva + sizeof(kDepthGateSig) - 1)); // last sig cut off
    }

    // 2. cave layout
    {
        const std::uint64_t cave_va = 0x200000000ULL;
        std::uint8_t buf[kCaveSize];
        const std::uint64_t exit_fn = 0x7ff612345678ULL;
        assert(emit_cave(buf, sizeof(buf), cave_va, base, exit_fn) == kCaveSize);
        assert(emit_cave(buf, kCaveSize - 1, cave_va, base, exit_fn) == 0);   // cap too small
        assert(emit_cave(buf, kCaveSize, cave_va + 8, base, exit_fn) == 0);   // misaligned cave
        assert(emit_cave(buf, kCaveSize, cave_va, base, 0) == 0);             // no exit function
        assert(emit_cave(buf, sizeof(buf), cave_va, base, exit_fn) == kCaveSize);

        // 3a exit hook: pushes, sub, mov rcx,rdi, call [exit_fn], add, pops, replay, jmp back
        const std::uint8_t eh_pre[] = {0x50,0x51,0x52,0x41,0x50,0x41,0x51,0x41,0x52,0x41,0x53,
                                       0x48,0x83,0xec,0x28, 0x48,0x89,0xf9, 0xff,0x15};
        assert(std::memcmp(buf + kFragExitHook, eh_pre, sizeof(eh_pre)) == 0);
        assert(rel_to(buf, kFragExitHook + 20, cave_va, cave_va + kExitFnOff));
        const std::uint8_t eh_post[] = {0x48,0x83,0xc4,0x28, 0x41,0x5b,0x41,0x5a,0x41,0x59,0x41,0x58,0x5a,0x59,0x58,
                                        0x48,0x8b,0x4d,0x50,0x48,0x33,0xcc, 0xe9};
        assert(std::memcmp(buf + kFragExitHook + 24, eh_post, sizeof(eh_post)) == 0);
        assert(rel_to(buf, kFragExitHook + 47, cave_va, base + kExitReturnRva));
        std::uint64_t fnv; std::memcpy(&fnv, buf + kExitFnOff, 8); assert(fnv == exit_fn);
        assert(kExitFnOff % 8 == 0 && kFragExitHook + 51 <= kFragCopySkip);
        // replayed bytes == the overwritten original bytes
        assert(std::memcmp(buf + kFragExitHook + 39, kExitSig, sizeof(kExitSig)) == 0);

        // 3b copy-back skip: jmp 0x180018e07
        assert(buf[kFragCopySkip] == 0xe9 && rel_to(buf, kFragCopySkip + 1, cave_va, base + kCopyBackReturnRva));
        assert(kFragCopySkip + 5 <= kAbsMaskOff);

        // fragment 1: cvttss2si r8d,[rbp+0x1048] ; lea rdx,"OutWidth" ; jmp back
        const std::uint8_t f1[] = {0xf3,0x44,0x0f,0x2c,0x85,0x48,0x10,0x00,0x00,0x48,0x8d,0x15};
        assert(std::memcmp(buf + kFragOutW, f1, sizeof(f1)) == 0);
        assert(rel_to(buf, kFragOutW + 12, cave_va, base + kOutWidthStrRva));
        assert(buf[kFragOutW + 16] == 0xe9 && rel_to(buf, kFragOutW + 17, cave_va, base + kOutWidthReturnRva));

        // fragment 2: cvttss2si r8d,[rbp+0x104c] ; lea rdx,"OutHeight" ; jmp back
        const std::uint8_t f2[] = {0xf3,0x44,0x0f,0x2c,0x85,0x4c,0x10,0x00,0x00,0x48,0x8d,0x15};
        assert(std::memcmp(buf + kFragOutH, f2, sizeof(f2)) == 0);
        assert(rel_to(buf, kFragOutH + 12, cave_va, base + kOutHeightStrRva));
        assert(buf[kFragOutH + 16] == 0xe9 && rel_to(buf, kFragOutH + 17, cave_va, base + kOutHeightReturnRva));

        // fragment 3: cvttss2si r8d,[rip+H] ; cvttss2si edx,[rip+W] ; jmp back
        const std::uint8_t f3a[] = {0xf3,0x44,0x0f,0x2c,0x05}, f3b[] = {0xf3,0x0f,0x2c,0x15};
        assert(std::memcmp(buf + kFragOutput, f3a, 5) == 0);
        assert(rel_to(buf, kFragOutput + 5, cave_va, base + kNativeHRva));
        assert(std::memcmp(buf + kFragOutput + 9, f3b, 4) == 0);
        assert(rel_to(buf, kFragOutput + 13, cave_va, base + kNativeWRva));
        assert(buf[kFragOutput + 17] == 0xe9 && rel_to(buf, kFragOutput + 18, cave_va, base + kOutputReturnRva));

        // gates 0 and 0b: two 53-byte halves then jmp pass
        for (int site = 0; site < 2; ++site) {
            const std::size_t g = site == 0 ? kFragGate : kFragDepthGate;
            for (std::size_t k = 0; k < 2; ++k) {
                const std::size_t h = g + 53 * k;
                if (site == 0) {
                    assert(buf[h] == 0x8b && buf[h + 1] == 0x45 && buf[h + 2] == 0x20 + 4 * k);  // mov eax,[rbp+0x20]
                    assert(buf[h + 11] == 0xf3 && buf[h + 14] == 0x4c && buf[h + 16] == 0x78 + 4 * k); // movss xmm1,[rsp+0x78]
                } else {
                    assert(buf[h] == 0x8b && buf[h + 1] == 0x44 && buf[h + 2] == 0x24 && buf[h + 3] == 0x48 + 4 * k);
                    assert(buf[h + 12] == 0xf3 && buf[h + 15] == 0x4d && buf[h + 16] == 0x88 + 4 * k); // movss xmm1,[rbp-0x78]
                }
                assert(rel_to(buf, h + 21, cave_va, cave_va + kScaleOff));              // mulss [scale]
                assert(rel_to(buf, h + 32, cave_va, cave_va + kAbsMaskOff));            // andps [absmask]
                assert(rel_to(buf, h + 40, cave_va, cave_va + kOneOff));                // movss [1.0]
                assert(buf[h + 47] == 0x0f && buf[h + 48] == 0x86);                     // jbe
                assert(rel_to(buf, h + 49, cave_va, base + (site == 0 ? kGateSkipRva : kDepthGateSkipRva)));
            }
            assert(buf[g + 106] == 0xe9 &&
                   rel_to(buf, g + 107, cave_va, base + (site == 0 ? kGatePassRva : kDepthGatePassRva)));
        }
        assert(kFragGate + 111 <= kFragDepthGate && kFragDepthGate + 111 <= kFragExitHook);

        // data
        float f; std::uint32_t u;
        std::memcpy(&f, buf + kScaleOff, 4); assert(f == 1.0f);
        std::memcpy(&f, buf + kOneOff, 4);   assert(f == 1.0f);
        for (int i = 0; i < 4; ++i) { std::memcpy(&u, buf + kAbsMaskOff + 4 * i, 4); assert(u == 0x7fffffffu); }
        assert(kAbsMaskOff % 16 == 0 && kScaleOff % 4 == 0);
    }

    // 3. jump emission + apply order
    {
        std::uint8_t j[5];
        const std::uint64_t from = 0x180018791ULL, to = 0x200000000ULL;
        assert(emit_jump(j, from, to) == 5);
        assert(j[0] == 0xe9);
        assert(static_cast<std::int64_t>(rd32(j + 1)) == static_cast<std::int64_t>(to - (from + 5)));

        constexpr std::size_t nsites = sizeof(kSites) / sizeof(kSites[0]);
        static_assert(nsites == 7, "seven patch sites");
        // the copy-back skip must never go live without the redirect hook before it
        std::size_t i_exit = nsites, i_copy = nsites;
        for (std::size_t i = 0; i < nsites; ++i) {
            if (kSites[i].rva == kExitPatchRva) i_exit = i;
            if (kSites[i].rva == kCopyBackPatchRva) i_copy = i;
        }
        assert(i_exit < i_copy && i_copy < nsites - 2);
        assert(kSites[nsites - 1].rva == kGatePatchRva);   // dispatch gate goes live last
        assert(kSites[nsites - 2].rva == kDepthGatePatchRva);
        for (const auto& s : kSites) assert(s.len >= 5 && s.cave_off < kAbsMaskOff);
    }

    // 4. execute the gate fragment
    {
        Exec ex;
        assert(ex.init());
        assert(ex.load_cave(1.0f));                              // default slot = original behaviour
        assert(ex.gate(3440, 1440, 3440.f, 1440.f) == 1);
        assert(ex.gate(2580, 1080, 3440.f, 1440.f) == 0);
        assert(ex.gate(3440, 1439, 3440.f, 1440.f) == 0);

        assert(ex.load_cave(0.75f));
        assert(ex.gate(2580, 1080, 3440.f, 1440.f) == 1);        // exact reduced scene
        assert(ex.gate(3440, 1440, 3440.f, 1440.f) == 0);        // native no longer passes
        assert(ex.gate(2579, 1080, 3440.f, 1440.f) == 0);        // |d| == 1 -> skip (strict)
        assert(ex.gate(2580, 1081, 3440.f, 1440.f) == 0);        // H checked too
        assert(ex.gate(256, 256, 3440.f, 1440.f) == 0);          // unrelated texture
        assert(ex.gate(1024, 576, 1366.f, 768.f) == 1);          // 1024.5 -> floor within tolerance
        assert(ex.gate(1025, 576, 1366.f, 768.f) == 1);          // 1024.5 -> ceil within tolerance
        assert(ex.gate(2580, 1080, std::nanf(""), 1440.f) == 0); // NaN camera -> skip
        assert(ex.gate(2580, 1080, 3440.f, std::nanf("")) == 0);

        // depth-capture gate (0b): same semantics, different operands/targets
        assert(ex.load_cave(1.0f));
        assert(ex.depth_gate(3440, 1440, 3440.f, 1440.f) == 1);
        assert(ex.depth_gate(2580, 1080, 3440.f, 1440.f) == 0);   // the in-game failure at scale 1.0
        assert(ex.load_cave(0.75f));
        assert(ex.depth_gate(2580, 1080, 3440.f, 1440.f) == 1);   // reduced linear depth is captured
        assert(ex.depth_gate(3440, 1440, 3440.f, 1440.f) == 0);
        assert(ex.depth_gate(2580, 1079, 3440.f, 1440.f) == 0);
        assert(ex.depth_gate(1290, 540, 3440.f, 1440.f) == 0);    // half-res depth must not be captured
        assert(ex.depth_gate(2580, 1080, std::nanf(""), 1440.f) == 0);
        // both gates share one scale slot
        assert(ex.gate(2580, 1080, 3440.f, 1440.f) == 1);

        // 3a: execute the exit hook
        assert(ex.load_cave(0.75f, reinterpret_cast<std::uint64_t>(&fake_on_dispatch_exit)));
        std::uint8_t* stack = ex.region + 0x7f00;                 // 16-aligned fake rsp
        alignas(16) std::uint8_t frame[0x80] = {};
        const std::uint64_t cookie = 0x0123456789abcdefULL, sentinel = 0x5a5a5a5a12345678ULL;
        std::memcpy(frame + 0x50, &cookie, 8);
        void* const ctx = reinterpret_cast<void*>(0x11223344ULL);
        const std::uint64_t r = ex.fn_exit(frame, stack, ctx, sentinel);
        assert(g_calls == 1 && g_seen_ctx == ctx);                // ctx passed in rcx (from rdi)
        assert(g_seen_frame % 16 == 0);                           // rsp 16-aligned at the call
        assert(g_seen_frame < reinterpret_cast<std::uintptr_t>(stack) - 0x60); // below the saved regs
        // replay computed rcx = [rbp+0x50] ^ rsp with rsp restored; r8 (volatile) restored
        assert(r == ((cookie ^ reinterpret_cast<std::uint64_t>(stack)) ^ sentinel));
        munmap(ex.region, Exec::kSize);
    }

    std::puts("proxy_patch_test: all passed");
    return 0;
}
