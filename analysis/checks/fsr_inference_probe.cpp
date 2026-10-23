// Calls the built bridge DLL's real NGX interface on synthetic, static frames.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <d3d11.h>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

#ifndef PROBE_WIDTH
#define PROBE_WIDTH 640
#endif
#ifndef PROBE_HEIGHT
#define PROBE_HEIGHT 360
#endif
static constexpr UINT outputWidth = PROBE_WIDTH, outputHeight = PROBE_HEIGHT;
static_assert(outputWidth > 0 && outputHeight > 0 && outputWidth % 2 == 0 && outputHeight % 2 == 0);

#define REQUIRE_HR(call) do { \
    const HRESULT result = (call); \
    printf("%s: 0x%08lX\n", #call, (unsigned long)result); \
    fflush(stdout); \
    if (FAILED(result)) return 1; \
} while (0)
#define REQUIRE_NGX(call) do { \
    const int result = (call); \
    printf("%s: 0x%08X\n", #call, (unsigned int)result); \
    fflush(stdout); \
    if (result != 1) return 1; \
} while (0)

struct Api
{
    int (*Init_ProjectID)(const char*, int, const char*, const wchar_t*, ID3D11Device*, int, const void*);
    int (*AllocateParameters)(void**);
    int (*DestroyParameters)(void*);
    int (*CreateFeature)(ID3D11DeviceContext*, int, void*, void**);
    int (*EvaluateFeature)(ID3D11DeviceContext*, const void*, const void*, void*);
    int (*ReleaseFeature)(void*);
    int (*Shutdown)();
};

// Use the same verified MSVC-layout parameter vtable as the mod and upstream smoke test.
template <class T> T Slot(void* object, int offset)
{
    return *reinterpret_cast<T*>(*reinterpret_cast<char**>(object) + offset);
}
static void SetU32(void* p, const char* key, unsigned int value)
{
    Slot<void (*)(void*, const char*, unsigned int)>(p, 0x20)(p, key, value);
}
static void SetF32(void* p, const char* key, float value)
{
    Slot<void (*)(void*, const char*, float)>(p, 0x30)(p, key, value);
}
static void SetResource(void* p, const char* key, ID3D11Resource* value)
{
    Slot<void (*)(void*, const char*, ID3D11Resource*)>(p, 0x10)(p, key, value);
}

static float FiniteHalf(uint16_t bits)
{
    const int exponent = (bits >> 10) & 31;
    const int mantissa = bits & 1023;
    const float value = exponent ? std::ldexp(float(1024 + mantissa), exponent - 25)
                                 : std::ldexp(float(mantissa), -24);
    return bits & 0x8000 ? -value : value;
}

static int RunCase(Api& api, ID3D11Device* device, ID3D11DeviceContext* context,
                   UINT width, UINT height, const char* label)
{
    constexpr UINT frames = 16;
    printf("CASE %s render=%ux%u output=%ux%u frames=%u\n",
           label, width, height, outputWidth, outputHeight, frames);
    fflush(stdout);
    const uint16_t shades[] = {0x3000, 0x3400, 0x3800, 0x3a00, 0x3c00, 0x3e00, 0x4000, 0x4200};
    std::vector<uint16_t> colorData(width * height * 4);
    for (UINT y = 0; y < height; ++y)
        for (UINT x = 0; x < width; ++x)
        {
            auto* pixel = &colorData[(y * width + x) * 4];
            pixel[0] = shades[x * 8 / width];
            pixel[1] = shades[y * 8 / height];
            pixel[2] = shades[((x / 16) + (y / 16)) % 8];
            pixel[3] = 0x3c00;
        }
    std::vector<float> depthData(width * height, 0.5f);
    std::vector<uint16_t> motionData(width * height * 2, 0);
    std::vector<uint16_t> sentinel(outputWidth * outputHeight * 4, 0xc000);
    D3D11_TEXTURE2D_DESC desc{};
    desc.Width = width;
    desc.Height = height;
    desc.MipLevels = desc.ArraySize = desc.SampleDesc.Count = 1;
    desc.Usage = D3D11_USAGE_DEFAULT;
    desc.BindFlags = D3D11_BIND_SHADER_RESOURCE;
    desc.Format = DXGI_FORMAT_R16G16B16A16_FLOAT;
    D3D11_SUBRESOURCE_DATA data{colorData.data(), width * 8, 0};
    ID3D11Texture2D *color = nullptr, *depth = nullptr, *motion = nullptr;
    ID3D11Texture2D *output = nullptr, *readback = nullptr;
    REQUIRE_HR(device->CreateTexture2D(&desc, &data, &color));
    desc.Format = DXGI_FORMAT_R32_FLOAT;
    data = {depthData.data(), width * 4, 0};
    REQUIRE_HR(device->CreateTexture2D(&desc, &data, &depth));
    desc.Format = DXGI_FORMAT_R16G16_FLOAT;
    data = {motionData.data(), width * 4, 0};
    REQUIRE_HR(device->CreateTexture2D(&desc, &data, &motion));
    desc.Width = outputWidth;
    desc.Height = outputHeight;
    desc.Format = DXGI_FORMAT_R16G16B16A16_FLOAT;
    desc.BindFlags |= D3D11_BIND_UNORDERED_ACCESS;
    data = {sentinel.data(), outputWidth * 8, 0};
    REQUIRE_HR(device->CreateTexture2D(&desc, &data, &output));
    desc.BindFlags = 0;
    desc.Usage = D3D11_USAGE_STAGING;
    desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    REQUIRE_HR(device->CreateTexture2D(&desc, nullptr, &readback));

    void *parameters = nullptr, *feature = nullptr;
    REQUIRE_NGX(api.AllocateParameters(&parameters));
    if (!parameters) return 1;
    SetU32(parameters, "Width", width);
    SetU32(parameters, "Height", height);
    SetU32(parameters, "OutWidth", outputWidth);
    SetU32(parameters, "OutHeight", outputHeight);
    SetU32(parameters, "PerfQualityValue", width == outputWidth ? 5 : 0);
    SetU32(parameters, "DLSS.Feature.Create.Flags", 0x43);
    REQUIRE_NGX(api.CreateFeature(context, 1, parameters, &feature));
    if (!feature) return 1;
    SetResource(parameters, "Color", color);
    SetResource(parameters, "Output", output);
    SetResource(parameters, "Depth", depth);
    SetResource(parameters, "MotionVectors", motion);
    SetU32(parameters, "DLSS.Render.Subrect.Dimensions.Width", width);
    SetU32(parameters, "DLSS.Render.Subrect.Dimensions.Height", height);
    SetF32(parameters, "Jitter.Offset.X", 0.0f);
    SetF32(parameters, "Jitter.Offset.Y", 0.0f);
    SetF32(parameters, "MV.Scale.X", 1.0f);
    SetF32(parameters, "MV.Scale.Y", 1.0f);
    SetF32(parameters, "DLSS.Pre.Exposure", 1.0f);
    SetF32(parameters, "FrameTimeDeltaInMsec", 16.666667f);
    for (UINT frame = 0; frame < frames; ++frame)
    {
        SetU32(parameters, "Reset", frame == 0 || frame == 8);
        printf("FRAME %s %u\n", label, frame);
        REQUIRE_NGX(api.EvaluateFeature(context, feature, parameters, nullptr));
    }
    context->CopyResource(readback, output);
    D3D11_MAPPED_SUBRESOURCE mapped{};
    REQUIRE_HR(context->Map(readback, 0, D3D11_MAP_READ, 0, &mapped));
    UINT nonfinite = 0, untouched = 0;
    float minimum = 1e30f, maximum = -1e30f;
    char filename[80];
    snprintf(filename, sizeof filename, "%s-output.rgba16f", label);
    FILE* raw = fopen(filename, "wb");
    if (!raw) return 1;
    for (UINT y = 0; y < outputHeight; ++y)
    {
        const auto* row = reinterpret_cast<const uint16_t*>(
            static_cast<const unsigned char*>(mapped.pData) + y * mapped.RowPitch);
        if (fwrite(row, outputWidth * 8, 1, raw) != 1) return 1;
        for (UINT x = 0; x < outputWidth; ++x)
        {
            const auto* pixel = row + x * 4;
            untouched += pixel[0] == 0xc000 && pixel[1] == 0xc000 && pixel[2] == 0xc000;
            for (UINT c = 0; c < 3; ++c)
                if ((pixel[c] & 0x7c00) == 0x7c00)
                    ++nonfinite;
                else
                {
                    const float value = FiniteHalf(pixel[c]);
                    minimum = std::min(minimum, value);
                    maximum = std::max(maximum, value);
                }
        }
    }
    const bool saved = fclose(raw) == 0;
    context->Unmap(readback, 0);
    const bool sane = saved && nonfinite == 0 && untouched == 0 &&
                      minimum > -64.0f && maximum < 64.0f && maximum - minimum > 0.01f;
    printf("READBACK %s %s nonfinite=%u untouched=%u rgb_min=%.6f rgb_max=%.6f\n",
           label, sane ? "PASS" : "FAIL", nonfinite, untouched, minimum, maximum);
    fflush(stdout);
    REQUIRE_NGX(api.ReleaseFeature(feature));
    REQUIRE_NGX(api.DestroyParameters(parameters));
    color->Release();
    depth->Release();
    motion->Release();
    output->Release();
    readback->Release();
    return sane ? 0 : 1;
}

int main()
{
    if (!freopen("fsr-inference-results.txt", "w", stdout)) return 2;
    if (FiniteHalf(0) != 0.0f || FiniteHalf(0x3c00) != 1.0f ||
        FiniteHalf(0xc000) != -2.0f || FiniteHalf(1) != std::ldexp(1.0f, -24))
    {
        puts("HALF DECODE SELF-CHECK FAIL");
        return 1;
    }
    HMODULE module = LoadLibraryW(L"NIER_FSR4.dll");
    if (!module) { printf("LOAD FAIL error=%lu\n", GetLastError()); return 1; }
    Api api{};
#define RESOLVE(member) do { \
    const FARPROC symbol = GetProcAddress(module, "NVSDK_NGX_D3D11_" #member); \
    static_assert(sizeof(api.member) == sizeof(symbol)); \
    std::memcpy(&api.member, &symbol, sizeof(symbol)); \
    if (!api.member) { puts("MISSING EXPORT " #member); return 1; } \
} while (0)
    RESOLVE(Init_ProjectID);
    RESOLVE(AllocateParameters);
    RESOLVE(DestroyParameters);
    RESOLVE(CreateFeature);
    RESOLVE(EvaluateFeature);
    RESOLVE(ReleaseFeature);
    RESOLVE(Shutdown);
#undef RESOLVE
    ID3D11Device* device = nullptr;
    ID3D11DeviceContext* context = nullptr;
    const D3D_FEATURE_LEVEL level = D3D_FEATURE_LEVEL_11_0;
    REQUIRE_HR(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0,
                               &level, 1, D3D11_SDK_VERSION, &device, nullptr, &context));
    const D3D11_VIEWPORT viewport = {0, 0, (FLOAT)outputWidth, (FLOAT)outputHeight, 0, 1};
    context->RSSetViewports(1, &viewport);
    context->RSSetViewports(0, nullptr);
    ID3D11DeviceContext* deferred = nullptr;
    REQUIRE_HR(device->CreateDeferredContext(0, &deferred));
    deferred->RSSetViewports(1, &viewport);
    deferred->RSSetViewports(0, nullptr);
    deferred->Release();
    REQUIRE_NGX(api.Init_ProjectID("synthetic-fsr-probe", 0, "1", L".", device, 0x15, nullptr));
    const int result = RunCase(api, device, context, outputWidth, outputHeight, "native") ||
                       RunCase(api, device, context, outputWidth / 2, outputHeight / 2, "upscale");
    REQUIRE_NGX(api.Shutdown());
    context->Release();
    device->Release();
    FreeLibrary(module);
    printf("RESULT exit=%d (provider must also be checked in NIER_FSR4.log)\n", result);
    if (fclose(stdout) != 0) return 2;
    return result;
}
