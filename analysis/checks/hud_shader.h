#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace hud_shader {
// First 64 bits of the shipped HUD pixel shader's DXBC checksum; joined to the real frame trace.
constexpr std::uint64_t kSprite = 0xA1B772527CEA5742ull;
inline bool is_sprite(const unsigned char* bytes, std::size_t size) {
    if (!bytes || size < 32 || std::memcmp(bytes, "DXBC", 4)) return false;
    std::uint64_t checksum;
    std::uint32_t length;
    std::memcpy(&checksum, bytes + 4, sizeof checksum);
    std::memcpy(&length, bytes + 24, sizeof length);
    return checksum == kSprite && length == size;
}
}  // namespace hud_shader
