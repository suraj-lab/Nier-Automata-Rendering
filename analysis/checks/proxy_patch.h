// Upscale code-cave patch for NIER_DLAA_1.1.dll (the closed d3d11 proxy, image base 0x180000000).
// Pure logic, no Windows calls, so it is unit-tested natively (proxy_patch_test.cpp).
//
// Makes FSR4 upscale (reduced scene input -> native output) instead of native-AA (input == output):
//   1. NGX create "OutWidth"/"OutHeight" = native W/H (camera constants on the caller's stack).
//   2. The NGX "Output" texture (global 0x1800abf70) = native W/H (camera globals).
//   0. The pre-dispatch gate in FUN_1800173c0 accepts scene == camera * scale (within 1px)
//      instead of scene == camera. scale lives in a cave data slot (init 1.0 = original
//      behaviour); the setter writes the real scale only after the renderer scale is applied.
//  0b. The identical gate in the linear-depth capture (0x18001a6a4) uses the same rule and slot;
//      without it dispatch skips with "linear depth target not found yet".
// Width/Height (input) and the evaluate "Render.Subrect" params stay scene-sized, which is correct.
// Jitter needs no patch: the evaluate path already scales native-pixel jitter by sceneW/nativeW.
//
// Native W/H are FLOATS (FUN_180016cdc: movss [0x1800abc14],xmm0; the proxy reads them with
// ucomiss/divss), so fragments 1-2 convert with cvttss2si.
//
// Evidence: analysis/offline-camera/dlaa-render-dispatch-function.decoded.c,
//           analysis/offline-camera/camera-getter-function.decoded.c, and objdump of
//           FUN_1800173c0 / FUN_180018210 / FUN_180017e20.
#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <initializer_list>

namespace proxy_patch {

// --- RVAs are relative to the proxy image base (0x180000000) ---

// Patch 1/2: NGX create OutWidth/OutHeight (inside FUN_180018210). Each patch replaces a
// 10-byte pair `mov r8d,r13d/r12d; lea rdx,[rip+"OutWidth"/"OutHeight"]` with `jmp cave; nop*5`.
constexpr std::size_t kOutWidthPatchRva  = 0x18791;  // mov r8d,r13d ; lea rdx,"OutWidth"
constexpr std::size_t kOutWidthReturnRva = 0x1879b;  // next: mov rcx,rbx ; call FUN_18001fd00
constexpr std::size_t kOutHeightPatchRva = 0x187a3;  // mov r8d,r12d ; lea rdx,"OutHeight"
constexpr std::size_t kOutHeightReturnRva= 0x187ad;  // next: mov rcx,rbx ; call FUN_18001fd00
constexpr std::size_t kOutWidthStrRva    = 0x525d0;  // "OutWidth"
constexpr std::size_t kOutHeightStrRva   = 0x525e0;  // "OutHeight"

// Patch 3: Output texture creation (inside FUN_180017e20). Replaces a 5-byte pair
// `mov r8d,edi; mov edx,esi` (scene H,W) with `jmp cave` (exact fit, no NOPs).
constexpr std::size_t kOutputPatchRva  = 0x18006;  // mov r8d,edi ; mov edx,esi
constexpr std::size_t kOutputReturnRva = 0x1800b;  // next: mov rcx,rbx ; call FUN_180019c50
constexpr std::size_t kNativeWRva      = 0xabe28;  // camera W (float)
constexpr std::size_t kNativeHRva      = 0xabe2c;  // camera H (float)

// Patch 0: the size gate in FUN_1800173c0 (0x1800175ba..0x1800175f2). Replaces the first
// 6 bytes `mov eax,[rbp+0x20]; xorps xmm0,xmm0` with `jmp cave; nop`. No branch targets inside
// the block. xmm0/xmm1 are dead here (clobbered by the call at 0x1800175ad); flags are reset
// by `test r14b,r14b` at the pass target.
constexpr std::size_t kGatePatchRva  = 0x175ba;
constexpr std::size_t kGatePassRva   = 0x175f2;  // test r14b,r14b -> FSR4 dispatch path
constexpr std::size_t kGateSkipRva   = 0x17680;  // original jp/jne target (skip dispatch)

// native W/H on the FUN_180018210 stack (camera copy at [rbp+0x1040]; W@+0x08, H@+0x0c)
constexpr std::int32_t kStackNativeW = 0x1048;
constexpr std::int32_t kStackNativeH = 0x104c;

// Original bytes at each patch point (for signature verification).
constexpr unsigned char kOutWidthSig[]  = {0x45,0x8b,0xc5,0x48,0x8d,0x15,0x35,0x9e,0x03,0x00};
constexpr unsigned char kOutHeightSig[] = {0x45,0x8b,0xc4,0x48,0x8d,0x15,0x33,0x9e,0x03,0x00};
constexpr unsigned char kOutputSig[]    = {0x44,0x8b,0xc7,0x8b,0xd6};
// The whole 56-byte gate block, so a changed comparison is never silently replaced.
constexpr unsigned char kGateSig[] = {
    0x8b,0x45,0x20,0x0f,0x57,0xc0,0xf3,0x48,0x0f,0x2a,0xc0,0x0f,0x2e,0x44,0x24,0x78,
    0x0f,0x8a,0xb0,0x00,0x00,0x00,0x0f,0x85,0xaa,0x00,0x00,0x00,0x8b,0x45,0x24,0x0f,
    0x57,0xc0,0xf3,0x48,0x0f,0x2a,0xc0,0x0f,0x2e,0x44,0x24,0x7c,0x0f,0x8a,0x94,0x00,
    0x00,0x00,0x0f,0x85,0x8e,0x00,0x00,0x00};
static_assert(sizeof(kGateSig) == kGatePassRva - kGatePatchRva, "gate block size");

// Patch 0b: the same size gate in the linear-depth capture (FUN at 0x18001a6a4..0x18001a6dc):
// only a texture whose W/H ([rsp+0x48]/[rsp+0x4c]) equals camera W/H ([rbp-0x78]/[rbp-0x74]) is
// stored in global 0x1800abf40. Without this, FUN_180018210 logs "linear depth target not found
// yet, skipping" at reduced scale (seen in-game 2026-10-24). Patch 7 bytes
// `mov eax,[rsp+0x48]; xorps xmm0,xmm0` -> `jmp cave; nop; nop`. No branch targets inside;
// both targets write their registers/flags before reading them.
constexpr std::size_t kDepthGatePatchRva = 0x1a6a4;
constexpr std::size_t kDepthGatePassRva  = 0x1a6dc;  // lea rsi,[lock] -> store into 0x1800abf40
constexpr std::size_t kDepthGateSkipRva  = 0x1a78f;  // release desc'd texture, no capture
constexpr unsigned char kDepthGateSig[] = {
    0x8b,0x44,0x24,0x48,0x0f,0x57,0xc0,0xf3,0x48,0x0f,0x2a,0xc0,0x0f,0x2e,0x45,0x88,
    0x0f,0x8a,0xd5,0x00,0x00,0x00,0x0f,0x85,0xcf,0x00,0x00,0x00,0x8b,0x44,0x24,0x4c,
    0x0f,0x57,0xc0,0xf3,0x48,0x0f,0x2a,0xc0,0x0f,0x2e,0x45,0x8c,0x0f,0x8a,0xb9,0x00,
    0x00,0x00,0x0f,0x85,0xb3,0x00,0x00,0x00};
static_assert(sizeof(kDepthGateSig) == kDepthGatePassRva - kDepthGatePatchRva, "depth gate block size");

// Part 3a: exit hook in FUN_1800173c0. Every path (incl. early outs) ends at 0x1800176ac with
// rdi = ID3D11DeviceContext*, rsp 16-aligned, flags dead, rax unused by the 8 callers.
// `mov rcx,[rbp+0x50]; xor rcx,rsp` (7 bytes) -> `jmp cave; nop; nop`; the cave saves the
// volatile GPRs, calls on_dispatch_exit(ctx) (MS x64 ABI), replays the 7 bytes, jumps to 0x1800176b3.
constexpr std::size_t kExitPatchRva  = 0x176ac;
constexpr std::size_t kExitReturnRva = 0x176b3;  // call __security_check_cookie
constexpr unsigned char kExitSig[] = {0x48,0x8b,0x4d,0x50,0x48,0x33,0xcc};

// Part 3b: skip the copy-back `call [rax+0x178]` (CopyResource scene <- Output) at 0x180018e01;
// the redirect above makes the scene copy unnecessary (and it is size-invalid at reduced scale).
constexpr std::size_t kCopyBackPatchRva  = 0x18e01;
constexpr std::size_t kCopyBackReturnRva = 0x18e07;  // mov [0x1800adff4],0 (kept)
constexpr unsigned char kCopyBackSig[] = {0xff,0x90,0x78,0x01,0x00,0x00};

// Proxy globals read by the setter's on_dispatch_exit (RVAs).
constexpr std::size_t kCurFrameRva      = 0xabc08;  // u32, FUN_1800159a0 returns it
constexpr std::size_t kDispatchFrameRva = 0x6a288;  // u32, set to the frame just before FSR dispatch
constexpr std::size_t kImmediateCtxRva  = 0xabfc8;  // ID3D11DeviceContext* the proxy acts on
constexpr std::size_t kOutputTexRva     = 0xabf70;  // ID3D11Texture2D* FSR Output (bind SRV|UAV)

// Cave layout (cave base must be 16-byte aligned for the andps operand).
constexpr std::size_t kFragOutW    = 0;    // 21 bytes
constexpr std::size_t kFragOutH    = 21;   // 21 bytes
constexpr std::size_t kFragOutput  = 42;   // 22 bytes
constexpr std::size_t kFragGate    = 64;   // 111 bytes
constexpr std::size_t kFragDepthGate = 176; // 111 bytes
constexpr std::size_t kFragExitHook  = 288; // 51 bytes
constexpr std::size_t kFragCopySkip  = 340; // 5 bytes
constexpr std::size_t kAbsMaskOff  = 352;  // 16 bytes: 0x7fffffff x4
constexpr std::size_t kScaleOff    = 368;  // float scale (written by the setter)
constexpr std::size_t kOneOff      = 372;  // float 1.0 (tolerance)
constexpr std::size_t kExitFnOff   = 376;  // u64 address of the setter's on_dispatch_exit(ctx)
constexpr std::size_t kCaveSize    = 384;

// Patch table in apply order. The gate goes LAST: until it is live FSR4 never runs at reduced
// scale, so a partial failure leaves only parts 1-2 and 0b applied (all inert while the scale
// slot is 1.0, which it stays unless every site applied).
struct Site { std::size_t rva; std::size_t len; std::size_t cave_off; };
constexpr Site kSites[] = {
    { kOutWidthPatchRva,  10, kFragOutW   },
    { kOutHeightPatchRva, 10, kFragOutH   },
    { kOutputPatchRva,     5, kFragOutput },
    { kExitPatchRva,       7, kFragExitHook  },  // before the copy-back skip: never skip without redirect
    { kCopyBackPatchRva,   6, kFragCopySkip  },
    { kDepthGatePatchRva,  7, kFragDepthGate },
    { kGatePatchRva,       6, kFragGate   },
};

enum class Result { Applied, BadImage, SigMismatch, NoMemory, BadRange };

inline bool check_signatures(const std::uint8_t* image, std::size_t size)
{
    if (!image) return false;
    const std::size_t max_rva = kDepthGatePatchRva + sizeof(kDepthGateSig);  // highest signature end
    static_assert(kDepthGatePatchRva + sizeof(kDepthGateSig) >= kCopyBackPatchRva + sizeof(kCopyBackSig) &&
                  kDepthGatePatchRva > kExitPatchRva && kDepthGatePatchRva > kGatePatchRva &&
                  kDepthGatePatchRva > kOutHeightPatchRva, "max_rva must cover every signature");
    if (size < max_rva) return false;
    if (std::memcmp(image + kOutWidthPatchRva, kOutWidthSig, sizeof(kOutWidthSig)) != 0) return false;
    if (std::memcmp(image + kOutHeightPatchRva, kOutHeightSig, sizeof(kOutHeightSig)) != 0) return false;
    if (std::memcmp(image + kOutputPatchRva, kOutputSig, sizeof(kOutputSig)) != 0) return false;
    if (std::memcmp(image + kGatePatchRva, kGateSig, sizeof(kGateSig)) != 0) return false;
    if (std::memcmp(image + kDepthGatePatchRva, kDepthGateSig, sizeof(kDepthGateSig)) != 0) return false;
    if (std::memcmp(image + kExitPatchRva, kExitSig, sizeof(kExitSig)) != 0) return false;
    if (std::memcmp(image + kCopyBackPatchRva, kCopyBackSig, sizeof(kCopyBackSig)) != 0) return false;
    return true;
}

// Emits the code cave into dst (>= kCaveSize). Returns kCaveSize, or 0 if cap is too small,
// cave_va is not 16-byte aligned, or a fragment overflows its slot.
// image_base = runtime base of the proxy module. The scale slot starts at 1.0.
// exit_fn = address of `void on_dispatch_exit(ID3D11DeviceContext*)` (MS x64 ABI); must be non-zero.
inline std::size_t emit_cave(std::uint8_t* dst, std::size_t cap, std::uint64_t cave_va, std::uint64_t image_base,
                             std::uint64_t exit_fn)
{
    if (!dst || cap < kCaveSize || (cave_va & 15) != 0 || exit_fn == 0) return 0;
    std::memset(dst, 0xcc, kCaveSize);
    std::size_t n = 0;
    auto b = [&](std::initializer_list<std::uint8_t> xs) { for (auto x : xs) dst[n++] = x; };
    auto d32 = [&](std::int32_t v) { std::uint8_t t[4]; std::memcpy(t, &v, 4); b({t[0],t[1],t[2],t[3]}); };
    auto rel = [&](std::uint64_t target) { d32(static_cast<std::int32_t>(target - (cave_va + n + 4))); };
    auto va = [&](std::size_t rva) { return image_base + rva; };
    auto cv = [&](std::size_t off) { return cave_va + off; };

    // --- fragment 1: OutWidth ---
    n = kFragOutW;
    b({0xf3,0x44,0x0f,0x2c,0x85,0x48,0x10,0x00,0x00});   // cvttss2si r8d,[rbp+0x1048]
    b({0x48,0x8d,0x15}); rel(va(kOutWidthStrRva));       // lea rdx,"OutWidth"
    b({0xe9}); rel(va(kOutWidthReturnRva));              // jmp back
    if (n > kFragOutH) return 0;

    // --- fragment 2: OutHeight ---
    n = kFragOutH;
    b({0xf3,0x44,0x0f,0x2c,0x85,0x4c,0x10,0x00,0x00});   // cvttss2si r8d,[rbp+0x104c]
    b({0x48,0x8d,0x15}); rel(va(kOutHeightStrRva));      // lea rdx,"OutHeight"
    b({0xe9}); rel(va(kOutHeightReturnRva));             // jmp back
    if (n > kFragOutput) return 0;

    // --- fragment 3: Output texture ---
    n = kFragOutput;
    b({0xf3,0x44,0x0f,0x2c,0x05}); rel(va(kNativeHRva)); // cvttss2si r8d,[rip+nativeH]
    b({0xf3,0x0f,0x2c,0x15});      rel(va(kNativeWRva)); // cvttss2si edx,[rip+nativeW]
    b({0xe9});                     rel(va(kOutputReturnRva)); // jmp back
    if (n > kFragGate) return 0;

    // --- gates 0 / 0b: pass iff |texture - camera*scale| < 1 for W and H (NaN -> skip) ---
    // Halves are 53 bytes for both sites (operand lengths 3+6 and 4+5 bytes).
    // u8 casts: k is 0/1 so the disp8 bytes never wrap.
    for (int site = 0; site < 2; ++site) {
        n = site == 0 ? kFragGate : kFragDepthGate;
        for (std::uint8_t k = 0; k < 2; ++k) {
            const auto o = static_cast<std::uint8_t>(4 * k);
            if (site == 0) b({0x8b,0x45,static_cast<std::uint8_t>(0x20 + o)});      // mov eax,[rbp+0x20/0x24]
            else           b({0x8b,0x44,0x24,static_cast<std::uint8_t>(0x48 + o)}); // mov eax,[rsp+0x48/0x4c]
            b({0x0f,0x57,0xc0});                                                     // xorps xmm0,xmm0
            b({0xf3,0x48,0x0f,0x2a,0xc0});                                           // cvtsi2ss xmm0,rax
            if (site == 0) b({0xf3,0x0f,0x10,0x4c,0x24,static_cast<std::uint8_t>(0x78 + o)}); // movss xmm1,[rsp+0x78/0x7c]
            else           b({0xf3,0x0f,0x10,0x4d,static_cast<std::uint8_t>(0x88 + o)});      // movss xmm1,[rbp-0x78/-0x74]
            b({0xf3,0x0f,0x59,0x0d}); rel(cv(kScaleOff));                            // mulss xmm1,[scale]
            b({0xf3,0x0f,0x5c,0xc1});                                                // subss xmm0,xmm1
            b({0x0f,0x54,0x05});      rel(cv(kAbsMaskOff));                          // andps xmm0,[absmask]
            b({0xf3,0x0f,0x10,0x0d}); rel(cv(kOneOff));                              // movss xmm1,[1.0]
            b({0x0f,0x2e,0xc8});                                                     // ucomiss xmm1,xmm0
            b({0x0f,0x86}); rel(va(site == 0 ? kGateSkipRva : kDepthGateSkipRva));   // jbe skip
        }
        b({0xe9}); rel(va(site == 0 ? kGatePassRva : kDepthGatePassRva));            // jmp pass
        if (n > (site == 0 ? kFragDepthGate : kFragExitHook)) return 0;
    }

    // --- 3a: exit hook. 7 pushes (56) + 0x28 = 96 bytes keeps rsp 16-aligned at the call. ---
    n = kFragExitHook;
    b({0x50, 0x51, 0x52, 0x41,0x50, 0x41,0x51, 0x41,0x52, 0x41,0x53});  // push rax,rcx,rdx,r8-r11
    b({0x48,0x83,0xec,0x28});                                           // sub rsp,0x28 (shadow + align)
    b({0x48,0x89,0xf9});                                                // mov rcx,rdi (ctx)
    b({0xff,0x15}); rel(cv(kExitFnOff));                                // call [exit_fn]
    b({0x48,0x83,0xc4,0x28});                                           // add rsp,0x28
    b({0x41,0x5b, 0x41,0x5a, 0x41,0x59, 0x41,0x58, 0x5a, 0x59, 0x58});  // pop r11-r8,rdx,rcx,rax
    b({0x48,0x8b,0x4d,0x50, 0x48,0x33,0xcc});                           // replay: mov rcx,[rbp+0x50]; xor rcx,rsp
    b({0xe9}); rel(va(kExitReturnRva));                                 // jmp 0x1800176b3
    if (n > kFragCopySkip) return 0;

    // --- 3b: copy-back skip ---
    n = kFragCopySkip;
    b({0xe9}); rel(va(kCopyBackReturnRva));                             // jmp 0x180018e07
    if (n > kAbsMaskOff) return 0;

    // --- data ---
    const std::uint32_t mask = 0x7fffffffu;
    for (int i = 0; i < 4; ++i) std::memcpy(dst + kAbsMaskOff + 4 * i, &mask, 4);
    const float one = 1.0f;
    std::memcpy(dst + kScaleOff, &one, 4);
    std::memcpy(dst + kOneOff, &one, 4);
    std::memcpy(dst + kExitFnOff, &exit_fn, 8);
    return kCaveSize;
}

// Emits a 5-byte `jmp rel32` from -> to. Returns 5.
inline std::size_t emit_jump(std::uint8_t* dst, std::uint64_t from, std::uint64_t to)
{
    dst[0] = 0xe9;
    const std::int32_t rel = static_cast<std::int32_t>(to - (from + 5));
    std::memcpy(dst + 1, &rel, 4);
    return 5;
}

inline const char* name(Result r)
{
    switch (r) {
    case Result::Applied: return "applied";
    case Result::BadImage: return "bad-image";
    case Result::SigMismatch: return "signature-mismatch";
    case Result::NoMemory: return "no-memory";
    case Result::BadRange: return "bad-range";
    }
    return "?";
}

}  // namespace proxy_patch
