// Offscreen routing/instrumentation test. Mock nearest reconstruction, not FSR/game integration.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <d3d11.h>
#include <d3dcompiler.h>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

#define REQUIRE_HR(call) do { const HRESULT hr = (call); if (FAILED(hr)) { \
    std::printf("FAIL %s: 0x%08lX\n", #call, static_cast<unsigned long>(hr)); return 1; } } while (0)

static const char shaders[] = R"(
Texture2D<float4> source : register(t0);
RWTexture2D<float4> reconstructed : register(u0);
[numthreads(8,8,1)] void cs(uint3 id : SV_DispatchThreadID) {
    if (id.x < 32 && id.y < 16) reconstructed[id.xy] = source.Load(int3(id.xy / 2, 0));
}
float4 vs(uint id : SV_VertexID) : SV_Position {
    float2 uv = float2((id << 1) & 2, id & 2);
    return float4(uv * float2(2,-2) + float2(-1,1), 0, 1);
}
float4 ps(float4 position : SV_Position) : SV_Target {
    return source.Load(int3(int2(position.xy), 0));
}
)";

static HRESULT compile(const char* entry, const char* profile, ID3DBlob** out)
{
    ID3DBlob* errors = nullptr;
    const HRESULT hr = D3DCompile(shaders, sizeof(shaders) - 1, nullptr, nullptr, nullptr,
        entry, profile, D3DCOMPILE_ENABLE_STRICTNESS, 0, out, &errors);
    if (errors) { std::fprintf(stderr, "%s", static_cast<const char*>(errors->GetBufferPointer())); errors->Release(); }
    return hr;
}

static void* identity(IUnknown* resource)
{
    IUnknown* object = nullptr;
    if (FAILED(resource->QueryInterface(__uuidof(IUnknown), reinterpret_cast<void**>(&object)))) return nullptr;
    void* id = object; object->Release(); return id;
}

static uint16_t channel(UINT x, UINT y, UINT c)
{
    return static_cast<uint16_t>(c == 0 ? 0x3000 + x * 32 : c == 1 ? 0x3400 + y * 64 : 0x3c00);
}

static int verify(ID3D11Device* device, ID3D11DeviceContext* context, ID3D11Texture2D* texture,
    const char* label, bool region)
{
    D3D11_TEXTURE2D_DESC desc{};
    texture->GetDesc(&desc);
    if (desc.Width != 32 || desc.Height != 16 || desc.Format != DXGI_FORMAT_R16G16B16A16_FLOAT) return 1;
    desc.BindFlags = 0; desc.Usage = D3D11_USAGE_STAGING; desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    ID3D11Texture2D* staging = nullptr;
    REQUIRE_HR(device->CreateTexture2D(&desc, nullptr, &staging));
    context->CopyResource(staging, texture);
    D3D11_MAPPED_SUBRESOURCE mapped{};
    REQUIRE_HR(context->Map(staging, 0, D3D11_MAP_READ, 0, &mapped));
    bool passed = true;
    for (UINT y = 0; y < 16; ++y) {
        const auto* row = reinterpret_cast<const uint16_t*>(static_cast<const char*>(mapped.pData) + y * mapped.RowPitch);
        for (UINT x = 0; x < 32; ++x)
            for (UINT c = 0; c < 4; ++c) {
                const bool inside = !region || (x >= 16 && y >= 8);
                const uint16_t expected = inside ? channel((x - (region ? 16 : 0)) / 2,
                    (y - (region ? 8 : 0)) / 2, c) : 0;
                if (row[x * 4 + c] != expected) passed = false;
            }
    }
    context->Unmap(staging, 0); staging->Release();
    std::printf("CHECK %s %s pixels=512 exact_half_bits=1\n", label, passed ? "PASS" : "FAIL");
    return passed ? 0 : 1;
}

int main()
{
    ID3D11Device* device = nullptr;
    ID3D11DeviceContext* context = nullptr;
    const D3D_FEATURE_LEVEL level = D3D_FEATURE_LEVEL_11_0;
    REQUIRE_HR(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0,
        &level, 1, D3D11_SDK_VERSION, &device, nullptr, &context));
    ID3DBlob *csBlob = nullptr, *vsBlob = nullptr, *psBlob = nullptr;
    REQUIRE_HR(compile("cs", "cs_5_0", &csBlob));
    REQUIRE_HR(compile("vs", "vs_5_0", &vsBlob));
    REQUIRE_HR(compile("ps", "ps_5_0", &psBlob));
    ID3D11ComputeShader* cs = nullptr;
    ID3D11VertexShader* vs = nullptr;
    ID3D11PixelShader* ps = nullptr;
    REQUIRE_HR(device->CreateComputeShader(csBlob->GetBufferPointer(), csBlob->GetBufferSize(), nullptr, &cs));
    REQUIRE_HR(device->CreateVertexShader(vsBlob->GetBufferPointer(), vsBlob->GetBufferSize(), nullptr, &vs));
    REQUIRE_HR(device->CreatePixelShader(psBlob->GetBufferPointer(), psBlob->GetBufferSize(), nullptr, &ps));
    csBlob->Release(); vsBlob->Release(); psBlob->Release();

    std::vector<uint16_t> pixels(16 * 8 * 4);
    for (UINT y = 0; y < 8; ++y)
        for (UINT x = 0; x < 16; ++x)
            for (UINT c = 0; c < 4; ++c) pixels[(y * 16 + x) * 4 + c] = channel(x, y, c);
    D3D11_TEXTURE2D_DESC desc{};
    desc.Width = 16; desc.Height = 8; desc.MipLevels = desc.ArraySize = desc.SampleDesc.Count = 1;
    desc.Format = DXGI_FORMAT_R16G16B16A16_FLOAT; desc.BindFlags = D3D11_BIND_SHADER_RESOURCE;
    const D3D11_SUBRESOURCE_DATA initial = {pixels.data(), 16 * 8, 0};
    ID3D11Texture2D *source = nullptr, *native = nullptr, *post = nullptr, *copied = nullptr, *region = nullptr;
    REQUIRE_HR(device->CreateTexture2D(&desc, &initial, &source));
    desc.Width = 32; desc.Height = 16;
    desc.BindFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS;
    REQUIRE_HR(device->CreateTexture2D(&desc, nullptr, &native));
    desc.BindFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_RENDER_TARGET;
    REQUIRE_HR(device->CreateTexture2D(&desc, nullptr, &post));
    desc.BindFlags = 0;
    REQUIRE_HR(device->CreateTexture2D(&desc, nullptr, &copied));
    desc.BindFlags = D3D11_BIND_RENDER_TARGET;
    REQUIRE_HR(device->CreateTexture2D(&desc, nullptr, &region));
    std::printf("ROUTE source_id=%p native_id=%p post_id=%p copied_id=%p region_id=%p\n",
        identity(source), identity(native), identity(post), identity(copied), identity(region));
    ID3D11ShaderResourceView *sourceView = nullptr, *nativeView = nullptr, *postView = nullptr;
    ID3D11UnorderedAccessView* nativeUav = nullptr;
    ID3D11RenderTargetView *postRtv = nullptr, *regionRtv = nullptr;
    REQUIRE_HR(device->CreateShaderResourceView(source, nullptr, &sourceView));
    REQUIRE_HR(device->CreateShaderResourceView(native, nullptr, &nativeView));
    REQUIRE_HR(device->CreateShaderResourceView(post, nullptr, &postView));
    REQUIRE_HR(device->CreateUnorderedAccessView(native, nullptr, &nativeUav));
    REQUIRE_HR(device->CreateRenderTargetView(post, nullptr, &postRtv));
    REQUIRE_HR(device->CreateRenderTargetView(region, nullptr, &regionRtv));
    context->CSSetShader(cs, nullptr, 0);
    context->CSSetShaderResources(0, 1, &sourceView);
    context->CSSetUnorderedAccessViews(0, 1, &nativeUav, nullptr);
    context->Dispatch(4, 2, 1);
    ID3D11ShaderResourceView* nullView = nullptr;
    ID3D11UnorderedAccessView* nullUav = nullptr;
    context->CSSetShaderResources(0, 1, &nullView);
    context->CSSetUnorderedAccessViews(0, 1, &nullUav, nullptr);

    D3D11_RASTERIZER_DESC rasterDesc{};
    rasterDesc.FillMode = D3D11_FILL_SOLID; rasterDesc.CullMode = D3D11_CULL_NONE; rasterDesc.DepthClipEnable = TRUE;
    ID3D11RasterizerState* raster = nullptr;
    REQUIRE_HR(device->CreateRasterizerState(&rasterDesc, &raster));
    context->RSSetState(raster);
    const D3D11_VIEWPORT viewport = {0, 0, 32, 16, 0, 1};
    context->RSSetViewports(1, &viewport);
    context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    context->VSSetShader(vs, nullptr, 0); context->PSSetShader(ps, nullptr, 0);
    context->PSSetShaderResources(0, 1, &nativeView);
    context->OMSetRenderTargets(1, &postRtv, nullptr);
    const float clear[] = {0, 0, 0, 0};
    context->ClearRenderTargetView(postRtv, clear);
    context->Draw(3, 0);
    if (verify(device, context, post, "draw", false)) return 1;
    context->ClearRenderTargetView(postRtv, clear);
    context->DrawInstanced(3, 1, 0, 0);
    if (verify(device, context, post, "draw-instanced", false)) return 1;
    const uint16_t indices[] = {0, 1, 2};
    D3D11_BUFFER_DESC indexDesc{};
    indexDesc.ByteWidth = sizeof(indices); indexDesc.BindFlags = D3D11_BIND_INDEX_BUFFER;
    const D3D11_SUBRESOURCE_DATA indexData = {indices, 0, 0};
    ID3D11Buffer* indexBuffer = nullptr;
    REQUIRE_HR(device->CreateBuffer(&indexDesc, &indexData, &indexBuffer));
    context->IASetIndexBuffer(indexBuffer, DXGI_FORMAT_R16_UINT, 0);
    context->ClearRenderTargetView(postRtv, clear);
    context->DrawIndexed(3, 0, 0);
    if (verify(device, context, post, "draw-indexed", false)) return 1;
    context->ClearRenderTargetView(postRtv, clear);
    context->DrawIndexedInstanced(3, 1, 0, 0, 0);
    if (verify(device, context, post, "draw-indexed-instanced", false)) return 1;

    context->PSSetShaderResources(0, 1, &postView);
    ID3D11ShaderResourceView* hazard = nullptr;
    context->PSGetShaderResources(0, 1, &hazard);
    if (hazard) { hazard->Release(); std::puts("FAIL hazard was not unbound"); return 1; }
    std::puts("CHECK hazard-null PASS");
    context->OMSetRenderTargetsAndUnorderedAccessViews(1, &postRtv, nullptr, 1, 1, &nativeUav, nullptr);
    ID3D11UnorderedAccessView* omView = nullptr;
    context->OMGetRenderTargetsAndUnorderedAccessViews(0, nullptr, nullptr, 1, 1, &omView);
    if (!omView) { std::puts("FAIL OM UAV not bound"); return 1; }
    omView->Release();
    context->OMSetRenderTargetsAndUnorderedAccessViews(1, &postRtv, nullptr, 0,
        D3D11_KEEP_UNORDERED_ACCESS_VIEWS, nullptr, nullptr);
    context->OMGetRenderTargetsAndUnorderedAccessViews(0, nullptr, nullptr, 1, 1, &omView);
    if (!omView || identity(omView) != identity(nativeUav)) {
        if (omView) omView->Release();
        std::puts("FAIL kept OM UAV changed"); return 1;
    }
    omView->Release();
    std::puts("CHECK OM-uav-retained PASS");
    context->OMSetRenderTargetsAndUnorderedAccessViews(D3D11_KEEP_RENDER_TARGETS_AND_DEPTH_STENCIL,
        nullptr, nullptr, 1, 1, &nullUav, nullptr);
    context->OMGetRenderTargetsAndUnorderedAccessViews(0, nullptr, nullptr, 1, 1, &omView);
    if (omView) { omView->Release(); std::puts("FAIL OM UAV not unbound"); return 1; }
    ID3D11RenderTargetView* keptTarget = nullptr;
    context->OMGetRenderTargets(1, &keptTarget, nullptr);
    if (!keptTarget || identity(keptTarget) != identity(postRtv)) {
        if (keptTarget) keptTarget->Release();
        std::puts("FAIL kept RTV changed"); return 1;
    }
    keptTarget->Release();
    std::puts("CHECK OM-uav-keep PASS");
    context->PSSetShaderResources(0, 1, &nullView);
    context->OMSetRenderTargets(0, nullptr, nullptr);

    ID3D11DeviceContext* deferred = nullptr;
    REQUIRE_HR(device->CreateDeferredContext(0, &deferred));
    deferred->PSSetShaderResources(0, 1, &nativeView);
    deferred->CopyResource(copied, post);
    ID3D11CommandList* list = nullptr;
    REQUIRE_HR(deferred->FinishCommandList(TRUE, &list));
    context->ExecuteCommandList(list, FALSE);
    list->Release(); deferred->Release();
    const float zero[] = {0, 0, 0, 0};
    context->ClearRenderTargetView(regionRtv, zero);
    const D3D11_BOX box = {0, 0, 0, 16, 8, 1};
    context->CopySubresourceRegion(region, 0, 16, 8, 0, post, 0, &box);
    if (verify(device, context, post, "native-post", false) ||
        verify(device, context, copied, "deferred-copy", false) || verify(device, context, region, "region-copy", true)) return 1;
    context->ClearState();
    indexBuffer->Release(); raster->Release();
    sourceView->Release(); nativeView->Release(); postView->Release(); nativeUav->Release();
    postRtv->Release(); regionRtv->Release();
    source->Release(); native->Release(); post->Release(); copied->Release(); region->Release();
    cs->Release(); vs->Release(); ps->Release(); context->Release(); device->Release();
    std::puts("RESULT route-probe PASS (mock reconstruction, not FSR/game)");
    return 0;
}
