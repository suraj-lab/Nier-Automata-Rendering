// Render-scale setter core for NieRAutomata.exe (Win10 build, SHA-256 5171bed0…).
// Pure logic, no Windows calls, so it is unit-tested natively (scale_patch_test.cpp).
// Evidence: analysis/GAME_RENDER_SCALE.md, analysis/VIEWPORT_RESULTS.md.
#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace scale_patch {

// getWidth helper: `mov r10,[rip+disp32]` loading the renderer global...
constexpr std::size_t kSig1Rva = 0x248179;
constexpr unsigned char kSig1[] = {0x4c, 0x8b, 0x15, 0x20, 0x70, 0x53, 0x01};
// ...and `mulss xmm0,[r10+0x80]` reading the scale from it.
constexpr std::size_t kSig2Rva = 0x2481b8;
constexpr unsigned char kSig2[] = {0xf3, 0x41, 0x0f, 0x59, 0x82, 0x80, 0x00, 0x00, 0x00};
constexpr std::size_t kRendererGlobalRva = 0x177f1a0;
constexpr std::size_t kWidth = 0x3c, kHeight = 0x40, kScale = 0x80, kRendererMin = kScale + 4;

enum class Result {
    Applied,        // scale written
    BadImage,       // image too small for the offsets (permanent)
    SigMismatch,    // code bytes differ: other build or not yet decrypted (permanent once decrypted)
    NoRenderer,     // global still null (retry)
    Unreadable,     // renderer memory not readable (retry)
    BadSize,        // width/height not plausible yet (retry)
    NotDefault,     // scale is not exactly 1.0: someone else changed it, do not touch (permanent)
    BadScale,       // requested scale outside (0.25, 1.0) (permanent)
};

struct Info { std::uint32_t width = 0, height = 0; float before = 0; void* renderer = nullptr; };

using ReadableFn = bool (*)(const void* p, std::size_t n);

inline bool retryable(Result r) { return r == Result::NoRenderer || r == Result::Unreadable || r == Result::BadSize; }

inline Result try_apply(unsigned char* image, std::size_t image_size, float scale, ReadableFn readable, Info* info)
{
    if (!(scale > 0.25f && scale < 1.0f)) return Result::BadScale;
    if (!image || image_size < kRendererGlobalRva + sizeof(void*) || image_size < kSig2Rva + sizeof(kSig2))
        return Result::BadImage;
    if (std::memcmp(image + kSig1Rva, kSig1, sizeof(kSig1)) || std::memcmp(image + kSig2Rva, kSig2, sizeof(kSig2)))
        return Result::SigMismatch;
    // The global's address must also follow from sig1's rip-relative displacement.
    std::int32_t disp;
    std::memcpy(&disp, image + kSig1Rva + 3, sizeof(disp));
    if (kSig1Rva + sizeof(kSig1) + disp != kRendererGlobalRva) return Result::SigMismatch;

    unsigned char* renderer;
    std::memcpy(&renderer, image + kRendererGlobalRva, sizeof(renderer));
    if (!renderer) return Result::NoRenderer;
    if (!readable(renderer, kRendererMin)) return Result::Unreadable;

    std::uint32_t w, h; float cur;
    std::memcpy(&w, renderer + kWidth, 4);
    std::memcpy(&h, renderer + kHeight, 4);
    std::memcpy(&cur, renderer + kScale, 4);
    if (info) *info = Info{w, h, cur, renderer};
    if (w < 320 || h < 200 || w > 16384 || h > 16384) return Result::BadSize;
    if (cur != 1.0f) return Result::NotDefault;

    *reinterpret_cast<volatile float*>(renderer + kScale) = scale;  // aligned 4-byte store, atomic on x64
    return Result::Applied;
}

inline const char* name(Result r)
{
    switch (r) {
    case Result::Applied: return "applied";
    case Result::BadImage: return "bad-image";
    case Result::SigMismatch: return "signature-mismatch";
    case Result::NoRenderer: return "no-renderer";
    case Result::Unreadable: return "renderer-unreadable";
    case Result::BadSize: return "bad-size";
    case Result::NotDefault: return "scale-not-default";
    case Result::BadScale: return "bad-scale";
    }
    return "?";
}

}  // namespace scale_patch
