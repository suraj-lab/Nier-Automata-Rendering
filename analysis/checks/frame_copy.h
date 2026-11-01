#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <emmintrin.h>

namespace frame_copy {
// D3D9 A8R8G8B8 readback -> packed game backbuffer; x64's baseline SSE2 needs no CPU feature switch.
inline void bgra(const unsigned char* src, std::ptrdiff_t pitch, unsigned char* dst,
                 std::size_t width, std::size_t height, bool swap) {
    if (!width || !height) return;
    const __m128i alpha = _mm_set1_epi32(-16777216);  // 0xff000000
    const __m128i green = _mm_set1_epi32(0x0000ff00);
    const __m128i blue = _mm_set1_epi32(0x000000ff);
    const __m128i red = _mm_set1_epi32(0x00ff0000);
    for (std::size_t y = 0; y < height; ++y) {
        const auto* s = src + static_cast<std::ptrdiff_t>(y) * pitch;
        auto* d = dst + y * width * 4;
        std::size_t x = 0;
        for (; x + 4 <= width; x += 4, s += 16, d += 16) {
            __m128i p = _mm_loadu_si128(reinterpret_cast<const __m128i*>(s));
            if (swap) {
                const __m128i rb = _mm_or_si128(_mm_slli_epi32(_mm_and_si128(p, blue), 16),
                                               _mm_srli_epi32(_mm_and_si128(p, red), 16));
                p = _mm_or_si128(_mm_and_si128(p, green), rb);
            }
            _mm_storeu_si128(reinterpret_cast<__m128i*>(d), _mm_or_si128(p, alpha));
        }
        for (; x < width; ++x, s += 4, d += 4) {
            std::uint32_t p;
            std::memcpy(&p, s, sizeof p);
            if (swap) p = (p & 0x0000ff00u) | ((p & 0x000000ffu) << 16) | ((p & 0x00ff0000u) >> 16);
            p |= 0xff000000u;
            std::memcpy(d, &p, sizeof p);
        }
    }
}
}  // namespace frame_copy
