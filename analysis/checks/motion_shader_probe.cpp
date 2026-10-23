// Runs the extracted CS on synthetic data, not the game or a replacement shader.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <d3d11.h>
#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <vector>

#define REQUIRE_HR(call) do { const HRESULT hr = (call); if (FAILED(hr)) { \
    std::printf("FAIL %s: 0x%08lX\n", #call, static_cast<unsigned long>(hr)); return 1; } } while (0)

struct Constants {
    float matrix[16], projection[4], depth[2], linear[2], jitter[2], size[2];
    UINT debug;
    float padding[3];
};
static_assert(sizeof(Constants) == 128);
static_assert(offsetof(Constants, jitter) == 96 && offsetof(Constants, size) == 104);

static float half(uint16_t bits)
{
    const int exponent = (bits >> 10) & 31, mantissa = bits & 1023;
    if (exponent == 31) return NAN;
    const float value = exponent ? std::ldexp(1.0f + mantissa / 1024.0f, exponent - 15)
                                 : std::ldexp(static_cast<float>(mantissa), -24);
    return bits & 0x8000 ? -value : value;
}

// R16 storage can move a near-exact FP32 result by one representable step.
static float halfUlp(float value)
{
    return value == 0 ? std::ldexp(1.0f, -24)
        : std::ldexp(1.0f, std::max(-24, std::ilogb(std::fabs(value)) - 10));
}

struct Case {
    const char* name;
    UINT width, height;
    float previousX, previousY, previousW;
    uint16_t objectMask;
    float jitterX, jitterY, expectedX, expectedY;
};

static int run(ID3D11Device* device, ID3D11DeviceContext* context, ID3D11ComputeShader* shader, const Case& test)
{
    Constants constants{};
    constants.matrix[0] = constants.matrix[5] = constants.matrix[10] = 1;
    constants.matrix[3] = test.previousX;
    constants.matrix[7] = test.previousY;
    constants.matrix[15] = test.previousW;
    constants.projection[0] = constants.projection[1] = 1;
    constants.depth[1] = 1;
    constants.linear[0] = 2; // Synthetic linear-depth input 0.5 becomes view depth 1.
    constants.jitter[0] = test.jitterX;
    constants.jitter[1] = test.jitterY;
    constants.size[0] = static_cast<float>(test.width);
    constants.size[1] = static_cast<float>(test.height);
    D3D11_BUFFER_DESC bufferDesc{};
    bufferDesc.ByteWidth = sizeof(constants);
    bufferDesc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
    D3D11_SUBRESOURCE_DATA initial{&constants, 0, 0};
    ID3D11Buffer* buffer = nullptr;
    REQUIRE_HR(device->CreateBuffer(&bufferDesc, &initial, &buffer));

    D3D11_TEXTURE2D_DESC desc{};
    desc.Width = test.width; desc.Height = test.height;
    desc.MipLevels = desc.ArraySize = desc.SampleDesc.Count = 1;
    desc.BindFlags = D3D11_BIND_SHADER_RESOURCE;
    desc.Format = DXGI_FORMAT_R32_FLOAT;
    std::vector<float> depth(test.width * test.height, 0.5f);
    initial = {depth.data(), test.width * 4, 0};
    ID3D11Texture2D* inputs[2]{};
    ID3D11ShaderResourceView* srvs[2]{};
    REQUIRE_HR(device->CreateTexture2D(&desc, &initial, &inputs[0]));
    REQUIRE_HR(device->CreateShaderResourceView(inputs[0], nullptr, &srvs[0]));
    std::vector<uint16_t> object(test.width * test.height * 4);
    for (size_t i = 0; i < object.size(); i += 4) {
        object[i] = 0x4200; object[i + 1] = 0xc000; // Known object displacement (3, -2).
        object[i + 3] = test.objectMask;
    }
    desc.Format = DXGI_FORMAT_R16G16B16A16_FLOAT;
    initial = {object.data(), test.width * 8, 0};
    REQUIRE_HR(device->CreateTexture2D(&desc, &initial, &inputs[1]));
    REQUIRE_HR(device->CreateShaderResourceView(inputs[1], nullptr, &srvs[1]));

    ID3D11Texture2D* outputs[3]{};
    ID3D11UnorderedAccessView* uavs[3]{};
#ifdef MOTION_FLOAT_OUTPUT
    const DXGI_FORMAT vectorFormat = DXGI_FORMAT_R32G32_FLOAT;
#else
    const DXGI_FORMAT vectorFormat = DXGI_FORMAT_R16G16_FLOAT;
#endif
    const DXGI_FORMAT formats[] = {vectorFormat, DXGI_FORMAT_R32_FLOAT, DXGI_FORMAT_R16G16B16A16_FLOAT};
    desc.BindFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS;
    for (size_t i = 0; i < 3; ++i) {
        desc.Format = formats[i];
        REQUIRE_HR(device->CreateTexture2D(&desc, nullptr, &outputs[i]));
        REQUIRE_HR(device->CreateUnorderedAccessView(outputs[i], nullptr, &uavs[i]));
    }
    const float sentinel[] = {-1000, -1000, -1000, -1000};
    context->ClearUnorderedAccessViewFloat(uavs[0], sentinel);
    context->CSSetShader(shader, nullptr, 0);
    context->CSSetConstantBuffers(0, 1, &buffer);
    context->CSSetShaderResources(0, 2, srvs);
    context->CSSetUnorderedAccessViews(0, 3, uavs, nullptr);
    context->Dispatch((test.width + 7) / 8, (test.height + 7) / 8, 1);
    ID3D11ShaderResourceView* nullSrvs[2]{};
    ID3D11UnorderedAccessView* nullUavs[3]{};
    context->CSSetShaderResources(0, 2, nullSrvs);
    context->CSSetUnorderedAccessViews(0, 3, nullUavs, nullptr);

    desc.Format = formats[0]; desc.BindFlags = 0;
    desc.Usage = D3D11_USAGE_STAGING; desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    ID3D11Texture2D* staging = nullptr;
    REQUIRE_HR(device->CreateTexture2D(&desc, nullptr, &staging));
    context->CopyResource(staging, outputs[0]);
    D3D11_MAPPED_SUBRESOURCE mapped{};
    REQUIRE_HR(context->Map(staging, 0, D3D11_MAP_READ, 0, &mapped));
    float maximumError = 0;
    bool finite = true, matches = true;
#ifdef MOTION_FLOAT_OUTPUT
    const float toleranceX = 0.00001f, toleranceY = 0.00001f;
#else
    const float toleranceX = halfUlp(test.expectedX), toleranceY = halfUlp(test.expectedY);
#endif
    for (UINT y = 0; y < test.height; ++y) {
#ifdef MOTION_FLOAT_OUTPUT
        const auto* row = reinterpret_cast<const float*>(static_cast<const char*>(mapped.pData) + y * mapped.RowPitch);
#else
        const auto* row = reinterpret_cast<const uint16_t*>(static_cast<const char*>(mapped.pData) + y * mapped.RowPitch);
#endif
        for (UINT x = 0; x < test.width; ++x) {
#ifdef MOTION_FLOAT_OUTPUT
            const float dx = row[x * 2], dy = row[x * 2 + 1];
#else
            const float dx = half(row[x * 2]), dy = half(row[x * 2 + 1]);
#endif
            finite = finite && std::isfinite(dx) && std::isfinite(dy);
            matches = matches && std::fabs(dx - test.expectedX) <= toleranceX && std::fabs(dy - test.expectedY) <= toleranceY;
            maximumError = std::max(maximumError, std::max(std::fabs(dx - test.expectedX), std::fabs(dy - test.expectedY)));
        }
    }
    context->Unmap(staging, 0);
    const bool passed = finite && matches;
    std::printf("CASE %s %ux%u expected=(%.3f,%.3f) max_error=%.9g tolerance=(%.9g,%.9g) %s\n", test.name,
        test.width, test.height, test.expectedX, test.expectedY, maximumError, toleranceX, toleranceY, passed ? "PASS" : "FAIL");
    context->ClearState();
    staging->Release(); buffer->Release();
    for (auto* item : srvs) item->Release();
    for (auto* item : inputs) item->Release();
    for (auto* item : uavs) item->Release();
    for (auto* item : outputs) item->Release();
    return passed ? 0 : 1;
}

int main(int argc, char** argv)
{
    if (argc != 2) { std::fprintf(stderr, "usage: motion_shader_probe COMPUTE.dxbc\n"); return 2; }
    if (half(0x3c00) != 1 || half(0xc000) != -2 || half(0x4200) != 3 ||
        halfUlp(0) != half(1) || halfUlp(2.5f) != half(0x4101) - half(0x4100)) return 2;
    std::ifstream input(argv[1], std::ios::binary | std::ios::ate);
    const auto size = input.tellg();
    if (!input || size < 32 || size > 16 * 1024 * 1024) return 2;
    std::vector<char> bytes(static_cast<size_t>(size));
    input.seekg(0);
    if (!input.read(bytes.data(), size)) return 2;
    ID3D11Device* device = nullptr;
    ID3D11DeviceContext* context = nullptr;
    const D3D_FEATURE_LEVEL level = D3D_FEATURE_LEVEL_11_0;
    REQUIRE_HR(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0,
        &level, 1, D3D11_SDK_VERSION, &device, nullptr, &context));
    ID3D11ComputeShader* shader = nullptr;
    REQUIRE_HR(device->CreateComputeShader(bytes.data(), bytes.size(), nullptr, &shader));
    const Case cases[] = {
        {"identity", 8, 8, 0, 0, 1, 0, 0, 0, 0, 0},
        {"camera-positive", 32, 16, 0.25f, -0.25f, 1, 0, 0, 0, 4, 2},
        {"camera-half-size", 16, 8, 0.25f, -0.25f, 1, 0, 0, 0, 2, 1},
        {"camera-negative", 32, 16, -0.25f, 0.25f, 1, 0, 0, 0, -4, -2},
        {"camera-nonmultiple", 20, 12, 0.25f, -0.25f, 1, 0, 0, 0, 2.5f, 1.5f},
        {"object-override", 32, 16, 0.25f, -0.25f, 1, 0x3c00, 0, 0, 3, -2},
        {"object-half-size", 16, 8, 0.25f, -0.25f, 1, 0x3c00, 0, 0, 3, -2},
        {"mask-half-not-valid", 32, 16, 0.25f, -0.25f, 1, 0x3800, 0, 0, 4, 2},
        {"jitter-identity", 32, 16, 0, 0, 1, 0, 0.125f, -0.25f, 0, 0},
        {"previous-behind", 32, 16, 0.25f, -0.25f, -1, 0, 0, 0, 0, 0},
    };
    for (const auto& test : cases)
        if (run(device, context, shader, test)) return 1;
    shader->Release(); context->Release(); device->Release();
    std::puts("RESULT 10 motion shader cases PASS; synthetic data only");
    return 0;
}
