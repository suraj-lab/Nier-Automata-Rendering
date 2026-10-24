// Upscale code-cave patch for NIER_DLAA_1.1.dll (the closed d3d11 proxy, image base 0x180000000).
// Pure logic, no Windows calls, so it is unit-tested natively (proxy_patch_test.cpp).
//
// Makes FSR4 upscale (reduced scene input -> native output) instead of native-AA (input == output):
//   1. NGX create "OutWidth"/"OutHeight" = native W/H (camera constants on the caller's stack).
//   2. The NGX "Output" texture (global 0x1800abf70) = native W/H (camera globals).
// Width/Height (input) and the evaluate "Render.Subrect" params stay scene-sized, which is correct.
//
// Evidence: analysis/offline-camera/dlaa-render-dispatch-function.decoded.c,
//           analysis/offline-camera/camera-getter-function.decoded.c, and objdump of FUN_180018210 / FUN_180017e20.
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
constexpr std::size_t kNativeWRva      = 0xabe28;  // camera W (global qword low dword)
constexpr std::size_t kNativeHRva      = 0xabe2c;  // camera H (global qword high dword)

// native W/H on the FUN_180018210 stack (camera copy at [rbp+0x1040]; W@+0x08, H@+0x0c)
constexpr std::int32_t kStackNativeW = 0x1048;
constexpr std::int32_t kStackNativeH = 0x104c;

// Original bytes at each patch point (for signature verification).
constexpr unsigned char kOutWidthSig[]  = {0x45,0x8b,0xc5,0x48,0x8d,0x15,0x35,0x9e,0x03,0x00};
constexpr unsigned char kOutHeightSig[] = {0x45,0x8b,0xc4,0x48,0x8d,0x15,0x33,0x9e,0x03,0x00};
constexpr unsigned char kOutputSig[]    = {0x44,0x8b,0xc7,0x8b,0xd6};

constexpr std::size_t kCaveSize = 64;

enum class Result { Applied, BadImage, SigMismatch, NoMemory, BadRange };

inline bool check_signatures(const std::uint8_t* image, std::size_t size)
{
    if (!image) return false;
    const std::size_t max_rva = kOutHeightPatchRva + sizeof(kOutHeightSig);
    if (size < max_rva) return false;
    if (std::memcmp(image + kOutWidthPatchRva, kOutWidthSig, sizeof(kOutWidthSig)) != 0) return false;
    if (std::memcmp(image + kOutHeightPatchRva, kOutHeightSig, sizeof(kOutHeightSig)) != 0) return false;
    if (std::memcmp(image + kOutputPatchRva, kOutputSig, sizeof(kOutputSig)) != 0) return false;
    return true;
}

// Emits the code cave into dst (>= kCaveSize). Returns bytes written (0 if cap too small).
// image_base = runtime base of the proxy module.
inline std::size_t emit_cave(std::uint8_t* dst, std::size_t cap, std::uint64_t cave_va, std::uint64_t image_base)
{
    if (!dst || cap < kCaveSize) return 0;
    std::size_t n = 0;
    auto b = [&](std::initializer_list<std::uint8_t> xs) { for (auto x : xs) dst[n++] = x; };
    auto d32 = [&](std::int32_t v) { std::uint8_t t[4]; std::memcpy(t, &v, 4); b({t[0],t[1],t[2],t[3]}); };
    auto va = [&](std::size_t rva) { return image_base + rva; };

    // --- fragment 1: OutWidth (entry at +0) ---
    b({0x44,0x8b,0x85,0x48,0x10,0x00,0x00});                         // mov r8d,[rbp+0x1048]
    b({0x48,0x8d,0x15}); d32(static_cast<std::int32_t>(va(kOutWidthStrRva) - (cave_va + n + 4))); // lea rdx,"OutWidth"
    b({0xe9}); d32(static_cast<std::int32_t>(va(kOutWidthReturnRva) - (cave_va + n + 4)));        // jmp back

    // --- fragment 2: OutHeight (entry at +19) ---
    b({0x44,0x8b,0x85,0x4c,0x10,0x00,0x00});                         // mov r8d,[rbp+0x104c]
    b({0x48,0x8d,0x15}); d32(static_cast<std::int32_t>(va(kOutHeightStrRva) - (cave_va + n + 4))); // lea rdx,"OutHeight"
    b({0xe9}); d32(static_cast<std::int32_t>(va(kOutHeightReturnRva) - (cave_va + n + 4)));        // jmp back

    // --- fragment 3: Output texture (entry at +38) ---
    b({0x44,0x8b,0x05}); d32(static_cast<std::int32_t>(va(kNativeHRva) - (cave_va + n + 4)));  // mov r8d,[rip+nativeH]
    b({0x8b,0x15});      d32(static_cast<std::int32_t>(va(kNativeWRva) - (cave_va + n + 4)));  // mov edx,[rip+nativeW]
    b({0xe9});           d32(static_cast<std::int32_t>(va(kOutputReturnRva) - (cave_va + n + 4))); // jmp back

    return n;
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
