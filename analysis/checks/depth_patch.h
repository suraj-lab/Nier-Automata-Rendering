// Depth-scale code-cave patch for NieRAutomata.exe (Win10 build, SHA-256 44ee2dc0…).
// Pure logic, no Windows calls, so it is unit-tested natively (depth_patch_test.cpp).
//
// What it does: depth_d3d_creation @0x140258fe0 creates the D24S8 scene-depth texture+DSV and
// writes its descriptor W/H back into engine metadata. The descriptor W/H are read from [rbx]/[rbx+4]
// at 0x140259049/0x14025904b and copied to the local D3D11 desc at 0x14025904e/0x140259051. Both the
// D3D allocation and the later metadata writeback (0x14025914d) use those same descriptor fields, so
// scaling the descriptor in place at 0x14025904e keeps allocation and engine metadata consistent.
//
// The backend is also used by fixed-size depth (256x256 aux, shadow maps), so the cave only scales
// when the descriptor is scene-sized: == renderer W/H (full) or == renderer W/H >> 1 (velocity half).
//
// Evidence: analysis/DEPTH_SCALE_RESULTS.md, analysis/offline-depth/binary-traces.asm.
#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <initializer_list>

namespace depth_patch {

// RVAs are relative to the image base (the game exe module).
constexpr std::size_t kPrologueRva = 0x258fe0;   // depth_d3d_creation entry
constexpr std::size_t kPatchRva    = 0x25904e;   // `mov [rbp-0x40],ecx; mov [rbp-0x3c],eax`
constexpr std::size_t kReturnRva   = 0x259054;   // instruction after the patched pair
constexpr std::size_t kRendererRva = 0x177f1a0;  // renderer global (same as scale_patch)

constexpr std::uint32_t kWidth  = 0x3c;  // renderer field: screen width
constexpr std::uint32_t kHeight = 0x40;  // renderer field: screen height
constexpr std::uint32_t kScale  = 0x80;  // renderer field: internal render scale

constexpr std::size_t kCaveSize = 96;

// 16-byte prologue of depth_d3d_creation (mov [rsp+0x20],rbx; push rbp/rsi/rdi/r12/r13/r14/r15).
constexpr unsigned char kPrologueSig[] = {
    0x48,0x89,0x5c,0x24,0x20,0x55,0x56,0x57,0x41,0x54,0x41,0x55,0x41,0x56,0x41,0x57 };
// 6 bytes we overwrite with `jmp rel32; nop`.
constexpr unsigned char kPatchSig[] = { 0x89,0x4d,0xc0,0x89,0x45,0xc4 };

enum class Result { Applied, BadImage, SigMismatch, NoMemory, BadRange };

// Verifies the image has the expected bytes at the prologue and patch point.
inline bool check_signatures(const std::uint8_t* image, std::size_t size)
{
    if (!image) return false;
    if (size <= kReturnRva) return false;
    if (kPrologueRva + sizeof(kPrologueSig) > size) return false;
    if (kPatchRva + sizeof(kPatchSig) > size) return false;
    return std::memcmp(image + kPrologueRva, kPrologueSig, sizeof(kPrologueSig)) == 0 &&
           std::memcmp(image + kPatchRva, kPatchSig, sizeof(kPatchSig)) == 0;
}

// Emits the code cave into dst (>= kCaveSize bytes). Returns bytes written (0 if cap too small).
// cave_va    = runtime address of dst (where the cave executes)
// renderer_va= runtime address of the renderer global (image_base + kRendererRva)
// return_va  = runtime address to jump back to (image_base + kReturnRva)
inline std::size_t emit_cave(std::uint8_t* dst, std::size_t cap,
                             std::uint64_t cave_va, std::uint64_t renderer_va, std::uint64_t return_va)
{
    if (!dst || cap < kCaveSize) return 0;
    std::size_t n = 0;
    auto b = [&](std::initializer_list<std::uint8_t> xs) { for (auto x : xs) dst[n++] = x; };
    auto d32 = [&](std::int32_t v) { std::uint8_t t[4]; std::memcpy(t, &v, 4); b({t[0],t[1],t[2],t[3]}); };

    // 0: pushfq                       ; save EFLAGS — the caller's jne at 0x140259064 consumes the ZF
    //                                   from `cmp [rbx+0x20],2` at 0x140259045 (the replaced movs preserved it)
    b({0x9c});
    // 1: mov rdx, [rip+disp32]        ; rdx = renderer global
    b({0x48,0x8b,0x15}); d32(static_cast<std::int32_t>(renderer_va - (cave_va + 8)));
    // 8: test rdx, rdx                ; null renderer -> skip scaling
    b({0x48,0x85,0xd2});
    // 11: je .skip
    b({0x74,0x47});
    // 12: movss xmm1, [rdx+0x80]      ; xmm1 = scale
    b({0xf3,0x0f,0x10,0x8a,0x80,0x00,0x00,0x00});
    // 20: cmp ecx, [rdx+0x3c]         ; W == renderer width?
    b({0x3b,0x4a,0x3c});
    // 23: jne .try_half
    b({0x75,0x05});
    // 25: cmp eax, [rdx+0x40]         ; H == renderer height?
    b({0x3b,0x42,0x40});
    // 28: je .scale
    b({0x74,0x18});
    // 30: .try_half: mov r8d, [rdx+0x3c]
    b({0x44,0x8b,0x42,0x3c});
    // 34: shr r8d, 1                  ; renderer W / 2
    b({0x41,0xd1,0xe8});
    // 37: cmp ecx, r8d                ; W == half width?
    b({0x41,0x3b,0xc8});
    // 40: jne .skip
    b({0x75,0x29});
    // 42: mov r8d, [rdx+0x40]
    b({0x44,0x8b,0x42,0x40});
    // 46: shr r8d, 1                  ; renderer H / 2
    b({0x41,0xd1,0xe8});
    // 49: cmp eax, r8d                ; H == half height?
    b({0x41,0x3b,0xc0});
    // 52: jne .skip
    b({0x75,0x1d});
    // 54: .scale: cvtsi2ss xmm2, ecx  ; scale W
    b({0xf3,0x0f,0x2a,0xd1});
    // 58: mulss xmm2, xmm1
    b({0xf3,0x0f,0x59,0xd1});
    // 62: cvttss2si ecx, xmm2
    b({0xf3,0x0f,0x2c,0xca});
    // 66: cvtsi2ss xmm2, eax          ; scale H
    b({0xf3,0x0f,0x2a,0xd0});
    // 70: mulss xmm2, xmm1
    b({0xf3,0x0f,0x59,0xd1});
    // 74: cvttss2si eax, xmm2
    b({0xf3,0x0f,0x2c,0xc2});
    // 78: mov [rbx], ecx              ; write scaled W back to descriptor (metadata readback)
    b({0x89,0x0b});
    // 80: mov [rbx+4], eax            ; write scaled H back
    b({0x89,0x43,0x04});
    // 83: .skip: mov [rbp-0x40], ecx  ; store W to local D3D desc (scaled or native)
    b({0x89,0x4d,0xc0});
    // 87: mov [rbp-0x3c], eax         ; store H
    b({0x89,0x45,0xc4});
    // 90: popfq                       ; restore EFLAGS (ZF) for the caller
    b({0x9d});
    // 91: jmp return_va
    b({0xe9}); d32(static_cast<std::int32_t>(return_va - (cave_va + 96)));

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

}  // namespace depth_patch
