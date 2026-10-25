// Mock game for the full geometry/draw capture: binds a known mesh + VS constant buffer, hooks
// DrawIndexed, triggers a capture, and writes the recovered geometry, format and transform bytes.
// Usage: geometry_capture_mock_game.exe
#include <windows.h>
#include <d3d11.h>
#include <d3dcompiler.h>
#include <cstdio>
#include <cstring>
#include "geometry_capture.h"
#include "input_layout_hook.h"
#include "draw_capture.h"

static void write_file(const char* name, const void* data, std::size_t size) {
    FILE* f = std::fopen(name, "wb");
    if (f) { std::fwrite(data, 1, size, f); std::fclose(f); }
}

int wmain() {
    ID3D11Device* device = nullptr;
    ID3D11DeviceContext* context = nullptr;
    D3D_FEATURE_LEVEL level = {};
    if (FAILED(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, nullptr, 0,
                                 D3D11_SDK_VERSION, &device, &level, &context))) {
        std::fprintf(stderr, "FAIL device\n"); return 2;
    }
    input_layout_hook::install(device);
    draw_capture::install(context);

    using CompileFn = decltype(&D3DCompile);
    FARPROC cp = GetProcAddress(LoadLibraryW(L"d3dcompiler_47.dll"), "D3DCompile");
    CompileFn compile = nullptr; std::memcpy(&compile, &cp, sizeof compile);
    const char* vs_src =
        "struct VSOut { float4 pos : SV_POSITION; };\n"
        "VSOut main(float3 pos : POSITION, float3 nrm : NORMAL, float2 uv : TEXCOORD)"
        "{ VSOut o; o.pos = float4(pos, 1); return o; }\n";
    const char* ps_src = "float4 main() : SV_TARGET { return float4(0,0,0,0); }\n";
    ID3DBlob *vs = nullptr, *ps = nullptr, *err = nullptr;
    if (!compile || FAILED(compile(vs_src, std::strlen(vs_src), "vs", nullptr, nullptr, "main", "vs_4_0", 0, 0, &vs, &err)))
        { std::fprintf(stderr, "FAIL vs: %s\n", err ? (char*)err->GetBufferPointer() : ""); return 2; }
    if (err) err->Release();
    if (FAILED(compile(ps_src, std::strlen(ps_src), "ps", nullptr, nullptr, "main", "ps_4_0", 0, 0, &ps, &err)))
        { std::fprintf(stderr, "FAIL ps: %s\n", err ? (char*)err->GetBufferPointer() : ""); return 2; }
    if (err) err->Release();

    ID3D11VertexShader* vs_sh = nullptr; ID3D11PixelShader* ps_sh = nullptr;
    device->CreateVertexShader(vs->GetBufferPointer(), vs->GetBufferSize(), nullptr, &vs_sh);
    device->CreatePixelShader(ps->GetBufferPointer(), ps->GetBufferSize(), nullptr, &ps_sh);

    D3D11_INPUT_ELEMENT_DESC descs[3] = {
        {"POSITION", 0, DXGI_FORMAT_R32G32B32_FLOAT, 0, 0,  D3D11_INPUT_PER_VERTEX_DATA, 0},
        {"NORMAL",   0, DXGI_FORMAT_R32G32B32_FLOAT, 0, 12, D3D11_INPUT_PER_VERTEX_DATA, 0},
        {"TEXCOORD", 0, DXGI_FORMAT_R32G32_FLOAT,    0, 24, D3D11_INPUT_PER_VERTEX_DATA, 0},
    };
    ID3D11InputLayout* layout = nullptr;
    device->CreateInputLayout(descs, 3, vs->GetBufferPointer(), vs->GetBufferSize(), &layout);
    vs->Release(); ps->Release();

    unsigned char vertices[3 * 32];
    for (unsigned i = 0; i < sizeof(vertices); ++i) vertices[i] = static_cast<unsigned char>((i * 7 + 3) & 0xff);
    const unsigned char indices[6] = {0x00,0x00, 0x01,0x00, 0x02,0x00};
    unsigned char cb_bytes[64];
    for (unsigned i = 0; i < sizeof(cb_bytes); ++i) cb_bytes[i] = static_cast<unsigned char>((i * 11 + 5) & 0xff);
    write_file("expected_vb.bin", vertices, sizeof(vertices));
    write_file("expected_ib.bin", indices, sizeof(indices));
    write_file("expected_cb.bin", cb_bytes, sizeof(cb_bytes));

    D3D11_BUFFER_DESC vb{}; vb.ByteWidth = sizeof(vertices); vb.Usage = D3D11_USAGE_DEFAULT; vb.BindFlags = D3D11_BIND_VERTEX_BUFFER;
    D3D11_SUBRESOURCE_DATA vd = {vertices, 0, 0}; ID3D11Buffer* vb_buf = nullptr; device->CreateBuffer(&vb, &vd, &vb_buf);
    D3D11_BUFFER_DESC ib{}; ib.ByteWidth = sizeof(indices); ib.Usage = D3D11_USAGE_DEFAULT; ib.BindFlags = D3D11_BIND_INDEX_BUFFER;
    D3D11_SUBRESOURCE_DATA id = {indices, 0, 0}; ID3D11Buffer* ib_buf = nullptr; device->CreateBuffer(&ib, &id, &ib_buf);
    D3D11_BUFFER_DESC cb{}; cb.ByteWidth = sizeof(cb_bytes); cb.Usage = D3D11_USAGE_DEFAULT; cb.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
    D3D11_SUBRESOURCE_DATA cd = {cb_bytes, 0, 0}; ID3D11Buffer* cb_buf = nullptr; device->CreateBuffer(&cb, &cd, &cb_buf);

    D3D11_TEXTURE2D_DESC td{}; td.Width = 64; td.Height = 64; td.MipLevels = 1; td.ArraySize = 1;
    td.Format = DXGI_FORMAT_R8G8B8A8_UNORM; td.SampleDesc.Count = 1; td.Usage = D3D11_USAGE_DEFAULT; td.BindFlags = D3D11_BIND_RENDER_TARGET;
    ID3D11Texture2D* tex = nullptr; device->CreateTexture2D(&td, nullptr, &tex);
    ID3D11RenderTargetView* rtv = nullptr; device->CreateRenderTargetView(tex, nullptr, &rtv);

    D3D11_VIEWPORT vp{}; vp.Width = 64; vp.Height = 64; vp.MaxDepth = 1;
    context->RSSetViewports(1, &vp);
    context->OMSetRenderTargets(1, &rtv, nullptr);
    context->IASetInputLayout(layout);
    const UINT stride = 32, offset = 0;
    context->IASetVertexBuffers(0, 1, &vb_buf, &stride, &offset);
    context->IASetIndexBuffer(ib_buf, DXGI_FORMAT_R16_UINT, 0);
    context->VSSetShader(vs_sh, nullptr, 0);
    context->PSSetShader(ps_sh, nullptr, 0);
    context->VSSetConstantBuffers(0, 1, &cb_buf);

    draw_capture::min_index_count = 1;  // this test exercises the capture mechanics, not the filter
    context->DrawIndexed(3, 0, 0);  // before the frame: must not be recorded
    draw_capture::begin_frame();
    context->DrawIndexed(3, 0, 0);
    context->DrawIndexed(3, 0, 0);  // same static buffers again: must share the first read
    if (!draw_capture::end_frame()) { std::fprintf(stderr, "FAIL frame not active\n"); return 1; }
    context->DrawIndexed(3, 0, 0);  // after the frame: must not be recorded
    if (draw_capture::frame.size() != 2) { std::fprintf(stderr, "FAIL frame draws %zu\n", draw_capture::frame.size()); return 1; }
    {
        const auto& a = draw_capture::frame[0].geometry; const auto& b = draw_capture::frame[1].geometry;
        if (!a.vertex[0].shared_id || a.vertex[0].bytes != b.vertex[0].bytes || a.vertex[0].shared_id != b.vertex[0].shared_id ||
            !a.index.shared_id || a.index.bytes != b.index.bytes) { std::fprintf(stderr, "FAIL static buffers not shared\n"); return 1; }
        if (draw_capture::frame_bytes != sizeof(vertices) + sizeof(indices) + 2 * sizeof(cb_bytes)) {
            std::fprintf(stderr, "FAIL frame_bytes %zu counts shared buffers twice\n", draw_capture::frame_bytes); return 1;
        }
        if (!draw_capture::cache.entries.empty()) { std::fprintf(stderr, "FAIL cache kept buffer references\n"); return 1; }
    }
    // A DYNAMIC vertex buffer rewritten between two draws (same pointer) must be read fresh both times.
    D3D11_BUFFER_DESC dvb = vb; dvb.Usage = D3D11_USAGE_DYNAMIC; dvb.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;
    ID3D11Buffer* dyn = nullptr;
    if (FAILED(device->CreateBuffer(&dvb, nullptr, &dyn)) || !dyn) { std::fprintf(stderr, "FAIL dynamic buffer\n"); return 1; }
    const auto fill = [&](unsigned char value) {
        D3D11_MAPPED_SUBRESOURCE m{};
        context->Map(dyn, 0, D3D11_MAP_WRITE_DISCARD, 0, &m);
        std::memset(m.pData, value, sizeof(vertices));
        context->Unmap(dyn, 0);
    };
    context->IASetVertexBuffers(0, 1, &dyn, &stride, &offset);
    draw_capture::begin_frame();
    fill(0x11); context->DrawIndexed(3, 0, 0);
    fill(0x22); context->DrawIndexed(3, 0, 0);
    draw_capture::end_frame();
    if (draw_capture::frame.size() != 2) { std::fprintf(stderr, "FAIL dynamic frame draws %zu\n", draw_capture::frame.size()); return 1; }
    {
        const auto& a = draw_capture::frame[0].geometry.vertex[0]; const auto& b = draw_capture::frame[1].geometry.vertex[0];
        if (a.shared_id || b.shared_id || !a.bytes || !b.bytes || (*a.bytes)[0] != 0x11 || (*b.bytes)[0] != 0x22) {
            std::fprintf(stderr, "FAIL dynamic buffer shared or stale\n"); return 1;
        }
    }
    std::puts("cache checks passed");
    context->IASetVertexBuffers(0, 1, &vb_buf, &stride, &offset);
    draw_capture::begin_frame();
    context->DrawIndexed(3, 0, 0);
    draw_capture::end_frame();

    const draw_capture::Record& r = draw_capture::frame[0];
    if (!r.valid) { std::fprintf(stderr, "FAIL draw capture\n"); return 3; }
    write_file("capture_vb.bin", r.geometry.vertex[0].bytes->data(), r.geometry.vertex[0].bytes->size());
    write_file("capture_ib.bin", r.geometry.index.bytes->data(), r.geometry.index.bytes->size());
    if (!r.vs_cbs.empty())
        write_file("capture_cb.bin", r.vs_cbs[0].bytes.data(), r.vs_cbs[0].bytes.size());

    input_layout_hook::Layout els;
    const bool have_layout = input_layout_hook::lookup(r.geometry.layout, els);
    FILE* f = std::fopen("capture.json", "w");
    if (!f) return 4;
    std::fprintf(f, "{\"index_count\":%u,\"start_index\":%u,\"base_vertex\":%d,\"instanced\":%d,"
                   "\"vb_bytes\":%zu,\"ib_bytes\":%zu,\"vs_cbs\":%zu,\"cb_bytes\":%zu,"
                   "\"layout_found\":%d,\"layout_elements\":%zu,\"layout\":[",
                 r.index_count, r.start_index, r.base_vertex, r.instanced ? 1 : 0,
                 r.geometry.vertex[0].bytes->size(), r.geometry.index.bytes->size(),
                 r.vs_cbs.size(), r.vs_cbs.empty() ? 0 : r.vs_cbs[0].bytes.size(),
                 have_layout ? 1 : 0, els.elements.size());
    for (std::size_t i = 0; i < els.elements.size(); ++i) {
        const auto& e = els.elements[i];
        std::fprintf(f, "%s{\"semantic\":\"%s\",\"format\":%u,\"offset\":%u}", i ? "," : "",
                     e.semantic.c_str(), static_cast<unsigned>(e.format), e.offset);
    }
    std::fprintf(f, "]}\n");
    std::fclose(f);
    std::puts("draw capture written");
    // Exit immediately: the capture is complete. COM teardown under Wine/wined3d spins in a USB
    // enumeration loop at shutdown; the OS reclaims the leaked objects (test harness only).
    std::fflush(nullptr);
    ExitProcess(0);
    return 0;
}
