// Mock game for the scale setter under Proton: plants NieR's code signatures and a fake renderer
// at the real RVAs inside this exe's own image, calls D3D11CreateDevice through the chain, then
// checks whether the setter wrote the scale. Usage: scale_setter_mock_game.exe match|mismatch
#include <windows.h>
#include <d3d11.h>
#include <cstdio>
#include <cstring>
#include "scale_patch.h"

using namespace scale_patch;
static unsigned char image_pad[0x1800000];  // .bss large enough to cover both RVAs

int main(int argc, char** argv)
{
    const bool match = argc == 2 && !strcmp(argv[1], "match");
    if (argc != 2 || (!match && strcmp(argv[1], "mismatch"))) { puts("usage: match|mismatch"); return 2; }
    // Proton does not pass Windows stdout through; keep a result file per mode.
    if (!freopen(match ? "mock-match-result.txt" : "mock-mismatch-result.txt", "w", stdout)) return 2;
    auto* base = reinterpret_cast<unsigned char*>(GetModuleHandleW(nullptr));
    const std::size_t lo = image_pad - base, hi = lo + sizeof(image_pad);
    if (lo > kSig1Rva || hi < kRendererGlobalRva + 8) { printf("FAIL pad rva 0x%zx..0x%zx\n", lo, hi); return 3; }

    std::memcpy(base + kSig1Rva, kSig1, sizeof(kSig1));
    std::memcpy(base + kSig2Rva, kSig2, sizeof(kSig2));
    if (!match) base[kSig2Rva + 5] ^= 1;
    auto* renderer = static_cast<unsigned char*>(VirtualAlloc(nullptr, 4096, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
    const std::uint32_t w = 1920, h = 1200; const float one = 1.0f;
    std::memcpy(renderer + kWidth, &w, 4); std::memcpy(renderer + kHeight, &h, 4); std::memcpy(renderer + kScale, &one, 4);
    std::memcpy(base + kRendererGlobalRva, &renderer, sizeof(renderer));

    ID3D11Device* dev = nullptr; ID3D11DeviceContext* ctx = nullptr;
    const HRESULT hr = D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, nullptr, 0,
        D3D11_SDK_VERSION, &dev, nullptr, &ctx);
    printf("D3D11CreateDevice hr=0x%08lX\n", static_cast<unsigned long>(hr));
    if (FAILED(hr)) return 4;

    float s = 1.0f;
    for (int i = 0; i < 40 && s == 1.0f; ++i) { Sleep(50); std::memcpy(&s, renderer + kScale, 4); }
    if (!match) Sleep(1000), std::memcpy(&s, renderer + kScale, 4);  // give a wrong write time to show up
    const bool ok = match ? s == 0.75f : s == 1.0f;
    printf("MOCK %s scale=%.3f %s\n", argv[1], s, ok ? "PASS" : "FAIL");
    ctx->Release(); dev->Release();
    return ok ? 0 : 1;
}
