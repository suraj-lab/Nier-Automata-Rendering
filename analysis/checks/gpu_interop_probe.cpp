// Exercise the upstream bridge itself, without loading FSR or the game.
#include "../../upstream/Nier-FSR4/src/nier_fsr4.cpp"

#define REQUIRE_HR(call) do { \
    const HRESULT result = (call); \
    printf("%s: 0x%08lX\n", #call, (unsigned long)result); \
    fflush(stdout); \
    if (FAILED(result)) return 1; \
} while (0)

static int RoundTrip(Bridge& bridge, DXGI_FORMAT format)
{
    constexpr UINT width = 16, height = 16;
    const UINT pixelBytes = format == DXGI_FORMAT_R16G16B16A16_FLOAT ? 8 : 4;
    const UINT rowBytes = width * pixelBytes;
    std::vector<unsigned char> expected(rowBytes * height);
    for (UINT i = 0; i < width * height; ++i)
    {
        if (pixelBytes == 8)
        {
            const uint16_t pixel[] = {0x3c00, 0x3800, 0x3400, 0x3c00};
            memcpy(expected.data() + i * pixelBytes, pixel, sizeof pixel);
        }
        else
        {
            const uint32_t pixel = 0x3c0;
            memcpy(expected.data() + i * pixelBytes, &pixel, sizeof pixel);
        }
    }

    D3D11_TEXTURE2D_DESC desc{};
    desc.Width = width;
    desc.Height = height;
    desc.MipLevels = desc.ArraySize = desc.SampleDesc.Count = 1;
    desc.Format = format;
    desc.Usage = D3D11_USAGE_DEFAULT;
    desc.BindFlags = D3D11_BIND_SHADER_RESOURCE;
    D3D11_SUBRESOURCE_DATA initial{expected.data(), rowBytes, 0};
    ID3D11Texture2D* source = nullptr;
    REQUIRE_HR(bridge.dev11->CreateTexture2D(&desc, &initial, &source));
    printf("CASE format=%d\n", format);
    fflush(stdout);
    if (!bridge.Ensure(bridge.color, source, false, "probe-colour") ||
        !bridge.Ensure(bridge.output, source, true, "probe-output"))
        return 1;

    for (DXGI_FORMAT auxiliary : {DXGI_FORMAT_R32_FLOAT, DXGI_FORMAT_R16G16_FLOAT})
    {
        D3D11_TEXTURE2D_DESC auxDesc = desc;
        auxDesc.Format = auxiliary;
        ID3D11Texture2D* texture = nullptr;
        REQUIRE_HR(bridge.dev11->CreateTexture2D(&auxDesc, nullptr, &texture));
        const bool depth = auxiliary == DXGI_FORMAT_R32_FLOAT;
        const bool shared = bridge.Ensure(depth ? bridge.depth : bridge.mv, texture,
                                         false, depth ? "probe-depth" : "probe-motion");
        texture->Release();
        if (!shared)
            return 1;
    }

    desc.Usage = D3D11_USAGE_STAGING;
    desc.BindFlags = 0;
    desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    ID3D11Texture2D* readback = nullptr;
    REQUIRE_HR(bridge.dev11->CreateTexture2D(&desc, nullptr, &readback));
    REQUIRE_HR(bridge.alloc[0]->Reset());
    REQUIRE_HR(bridge.list->Reset(bridge.alloc[0], nullptr));

    D3D12_RESOURCE_BARRIER barriers[2]{};
    for (auto& barrier : barriers)
    {
        barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_COMMON;
    }
    barriers[0].Transition.pResource = bridge.color.r12;
    barriers[0].Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;
    barriers[1].Transition.pResource = bridge.output.r12;
    barriers[1].Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_DEST;
    bridge.list->ResourceBarrier(2, barriers);
    bridge.list->CopyResource(bridge.output.r12, bridge.color.r12);
    for (auto& barrier : barriers)
        std::swap(barrier.Transition.StateBefore, barrier.Transition.StateAfter);
    bridge.list->ResourceBarrier(2, barriers);
    REQUIRE_HR(bridge.list->Close());

    bridge.ctx11->CopyResource(bridge.color.t11, source);
    const UINT64 ready = ++bridge.readyValue;
    REQUIRE_HR(bridge.ctx11->Signal(bridge.readyFence11, ready));
    bridge.ctx11->Flush();
    REQUIRE_HR(bridge.queue->Wait(bridge.readyFence12, ready));
    ID3D12CommandList* lists[] = {bridge.list};
    bridge.queue->ExecuteCommandLists(1, lists);
    const UINT64 done = ++bridge.fenceValue;
    bridge.allocFence[0] = done;
    REQUIRE_HR(bridge.queue->Signal(bridge.fence12, done));
    REQUIRE_HR(bridge.ctx11->Wait(bridge.fence11, done));
    if (!bridge.WaitCpu(done))
        return 1;
    bridge.ctx11->CopyResource(readback, bridge.output.t11);
    D3D11_MAPPED_SUBRESOURCE mapped{};
    REQUIRE_HR(bridge.ctx11->Map(readback, 0, D3D11_MAP_READ, 0, &mapped));
    bool matches = true;
    for (UINT row = 0; row < height; ++row)
        matches &= memcmp(static_cast<unsigned char*>(mapped.pData) + row * mapped.RowPitch,
                          expected.data() + row * rowBytes, rowBytes) == 0;
    bridge.ctx11->Unmap(readback, 0);
    readback->Release();
    source->Release();
    printf("READBACK format=%d %s\n", format, matches ? "PASS" : "FAIL");
    fflush(stdout);
    return matches ? 0 : 1;
}

int main()
{
    if (!freopen("gpu-interop-results.txt", "w", stdout))
        return 2;
    ID3D11Device* device = nullptr;
    const D3D_FEATURE_LEVEL level = D3D_FEATURE_LEVEL_11_0;
    REQUIRE_HR(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0,
                               &level, 1, D3D11_SDK_VERSION, &device, nullptr, nullptr));
    Bridge bridge;
    if (!bridge.Init(device))
    {
        puts("BRIDGE_INIT FAIL (see NIER_FSR4.log)");
        return 1;
    }
    const int result = RoundTrip(bridge, DXGI_FORMAT_R16G16B16A16_FLOAT) ||
                       RoundTrip(bridge, DXGI_FORMAT_R11G11B10_FLOAT);
    bridge.Shutdown();
    device->Release();
    printf("RESULT exit=%d\n", result);
    if (fclose(stdout) != 0)
        return 2;
    return result;
}
