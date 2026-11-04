// Which DXGI formats in a DX10 DDS header does remix-1.6.1's gli map to a format with a non-zero block extent?
// Build: g++ -std=c++17 -I analysis/runtime/src/dxvk-remix/include (remix-1.6.1 tag, sparse: include/gli include/glm).
#include <cstdio>
#include <gli/gli.hpp>
int main() {
    gli::dx dx;
    for (unsigned v = 1; v <= 132; ++v) {
        gli::dx::dxgiFormat f(static_cast<gli::dx::dxgi_format_dds>(v));
        gli::format g = dx.find(gli::dx::D3DFMT_DX10, f);
        bool ok = g != static_cast<gli::format>(gli::FORMAT_INVALID) && g >= gli::FORMAT_FIRST && g <= gli::FORMAT_LAST;
        glm::ivec3 e = ok ? gli::block_extent(g) : glm::ivec3(0);
        printf("%u %d %d %d\n", v, ok ? int(g) : -1, e.x, e.y);
    }
}
