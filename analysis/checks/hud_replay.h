#pragma once
// Replay the game's HUD over the Remix image.
//
// The HUD is 56 alpha-blended sprite draws into the final image. The scene filter keeps them out of the world (they are
// not geometry) and the capture side keeps them as clip-space quads with the game's own texture views. This draws them
// back on top of the composed path-traced frame, in the Present hook, with the game's own textures — no copy, no DDS.
//
// Everything here runs on the game thread, inside our Present hook: the state we touch is saved and restored so the
// game's next frame starts exactly as it would have without us.
#include <d3d11.h>
#include <d3dcompiler.h>
#include <vector>
#include "live_types.h"
#include "live_capture.h"

namespace hud_replay {

struct Pipeline {
    ID3D11VertexShader* vs = nullptr;
    ID3D11PixelShader* ps = nullptr;
    ID3D11InputLayout* layout = nullptr;
    ID3D11SamplerState* sampler = nullptr;
    ID3D11RasterizerState* raster = nullptr;  // solid, no cull, no depth clip: the game's state may be wireframe/culled
    ID3D11BlendState* blend = nullptr;        // straight alpha, created once
    ID3D11Buffer* constants = nullptr;   // one 4x4 matrix, updated per draw
    ID3D11Buffer* vertices = nullptr;    // dynamic: refilled every frame
    unsigned capacity = 0;               // vertices the buffer can hold
    bool failed = false;
};

inline bool compile(const char* source, const char* entry, const char* target, ID3DBlob** blob) {
    ID3DBlob* error = nullptr;
    const HRESULT hr = D3DCompile(source, std::strlen(source), nullptr, nullptr, nullptr, entry, target,
                                  D3DCOMPILE_OPTIMIZATION_LEVEL1, 0, blob, &error);
    if (error) error->Release();
    return SUCCEEDED(hr) && *blob;
}

inline void release(Pipeline& p);

inline bool ensure(ID3D11Device* device, Pipeline& p) {
    if (p.vs || p.failed) return p.vs != nullptr;
    // World -> clip with the game's own CB11 matrix. CB11 is three float4 registers with the translation in element 3
    // of each (48-byte stride; the world path reads it the same way): out_r = dot(register_r, float4(p, 1)), i.e. the
    // matrix on the left. mul(v, m) would put the translation into w (review 2026-10-29, R9).
    static const char vs_src[] =
        "cbuffer M : register(b0) { row_major float4x4 m; };\n"
        "struct VSOut { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; };\n"
        "VSOut main(float3 pos : POSITION, float2 uv : TEXCOORD0) {\n"
        "  VSOut o; o.pos = mul(m, float4(pos, 1.0)); o.uv = uv; return o;\n"
        "}\n";
    static const char ps_src[] =
        "Texture2D tex : register(t0);\n"
        "SamplerState smp : register(s0);\n"
        // SV_POSITION first: PS inputs link to VS outputs by register under DXVK, not by name (live 2026-10-29: uv read
        // the pixel position, so the whole frame showed one clamped corner texel).
        "float4 main(float4 pos : SV_POSITION, float2 uv : TEXCOORD0) : SV_TARGET { return tex.Sample(smp, uv); }\n";
    ID3DBlob* vs_blob = nullptr;
    ID3DBlob* ps_blob = nullptr;
    if (!compile(vs_src, "main", "vs_4_0", &vs_blob) || !compile(ps_src, "main", "ps_4_0", &ps_blob)) {
        if (vs_blob) vs_blob->Release();
        if (ps_blob) ps_blob->Release();
        p.failed = true;
        return false;
    }
    const D3D11_INPUT_ELEMENT_DESC elements[] = {
        {"POSITION", 0, DXGI_FORMAT_R32G32B32_FLOAT, 0, 0, D3D11_INPUT_PER_VERTEX_DATA, 0},
        {"TEXCOORD", 0, DXGI_FORMAT_R32G32_FLOAT, 0, 12, D3D11_INPUT_PER_VERTEX_DATA, 0},
    };
    bool ok = SUCCEEDED(device->CreateVertexShader(vs_blob->GetBufferPointer(), vs_blob->GetBufferSize(), nullptr, &p.vs)) &&
              SUCCEEDED(device->CreatePixelShader(ps_blob->GetBufferPointer(), ps_blob->GetBufferSize(), nullptr, &p.ps)) &&
              SUCCEEDED(device->CreateInputLayout(elements, 2, vs_blob->GetBufferPointer(), vs_blob->GetBufferSize(), &p.layout));
    vs_blob->Release();
    ps_blob->Release();
    D3D11_BUFFER_DESC cbd{}; cbd.ByteWidth = 64; cbd.Usage = D3D11_USAGE_DYNAMIC;
    cbd.BindFlags = D3D11_BIND_CONSTANT_BUFFER; cbd.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;
    ok = ok && SUCCEEDED(device->CreateBuffer(&cbd, nullptr, &p.constants));
    D3D11_SAMPLER_DESC sd{};
    sd.Filter = D3D11_FILTER_MIN_MAG_MIP_LINEAR;
    sd.AddressU = sd.AddressV = sd.AddressW = D3D11_TEXTURE_ADDRESS_CLAMP;
    sd.ComparisonFunc = D3D11_COMPARISON_NEVER;
    sd.MaxLOD = D3D11_FLOAT32_MAX;
    ok = ok && SUCCEEDED(device->CreateSamplerState(&sd, &p.sampler));
    D3D11_RASTERIZER_DESC rd{};
    rd.FillMode = D3D11_FILL_SOLID;
    rd.CullMode = D3D11_CULL_NONE;
    rd.DepthClipEnable = FALSE;
    rd.ScissorEnable = FALSE;
    ok = ok && SUCCEEDED(device->CreateRasterizerState(&rd, &p.raster));
    D3D11_BLEND_DESC bd{};
    bd.RenderTarget[0].BlendEnable = TRUE;
    bd.RenderTarget[0].SrcBlend = D3D11_BLEND_SRC_ALPHA;
    bd.RenderTarget[0].DestBlend = D3D11_BLEND_INV_SRC_ALPHA;
    bd.RenderTarget[0].BlendOp = D3D11_BLEND_OP_ADD;
    bd.RenderTarget[0].SrcBlendAlpha = D3D11_BLEND_ONE;
    bd.RenderTarget[0].DestBlendAlpha = D3D11_BLEND_ZERO;
    bd.RenderTarget[0].BlendOpAlpha = D3D11_BLEND_OP_ADD;
    bd.RenderTarget[0].RenderTargetWriteMask = D3D11_COLOR_WRITE_ENABLE_ALL;
    ok = ok && SUCCEEDED(device->CreateBlendState(&bd, &p.blend));
    if (!ok) { release(p); p.failed = true; }
    return ok;
}

inline void release(Pipeline& p) {
    if (p.vs) p.vs->Release();
    if (p.ps) p.ps->Release();
    if (p.layout) p.layout->Release();
    if (p.sampler) p.sampler->Release();
    if (p.raster) p.raster->Release();
    if (p.blend) p.blend->Release();
    if (p.constants) p.constants->Release();
    if (p.vertices) p.vertices->Release();
    p = Pipeline{};
}

inline bool ensure_vertices(ID3D11Device* device, Pipeline& p, unsigned count) {
    if (p.vertices && p.capacity >= count) return true;
    if (p.vertices) { p.vertices->Release(); p.vertices = nullptr; }
    const unsigned capacity = count < 4096 ? 4096 : count;
    D3D11_BUFFER_DESC bd{};
    bd.ByteWidth = capacity * sizeof(live_capture::UiVertex);
    bd.Usage = D3D11_USAGE_DYNAMIC;
    bd.BindFlags = D3D11_BIND_VERTEX_BUFFER;
    bd.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;
    if (FAILED(device->CreateBuffer(&bd, nullptr, &p.vertices))) { p.failed = true; return false; }
    p.capacity = capacity;
    return true;
}

// Save and restore the immediate-context state we touch: the game's next frame must not inherit anything.
struct SavedState {
    ID3D11InputLayout* layout = nullptr;
    ID3D11VertexShader* vs = nullptr;
    ID3D11PixelShader* ps = nullptr;
    ID3D11Buffer* vb = nullptr;
    ID3D11Buffer* ib = nullptr;
    ID3D11Buffer* cb = nullptr;
    ID3D11ShaderResourceView* srv = nullptr;
    ID3D11SamplerState* sampler = nullptr;
    ID3D11BlendState* blend = nullptr;
    float blend_factor[4] = {};
    UINT sample_mask = 0xFFFFFFFF;
    ID3D11RasterizerState* raster = nullptr;
    ID3D11RenderTargetView* rtvs[D3D11_SIMULTANEOUS_RENDER_TARGET_COUNT] = {};
    ID3D11DepthStencilView* dsv = nullptr;
    ID3D11GeometryShader* gs = nullptr;  // a stage the game left bound would otherwise run on our quads
    ID3D11HullShader* hs = nullptr;
    ID3D11DomainShader* ds = nullptr;
    D3D11_PRIMITIVE_TOPOLOGY topology = D3D11_PRIMITIVE_TOPOLOGY_UNDEFINED;
    UINT stride = 0, offset = 0, count = 0;
    DXGI_FORMAT ib_format = DXGI_FORMAT_UNKNOWN;
    UINT ib_offset = 0;
    D3D11_VIEWPORT viewport{};

    void save(ID3D11DeviceContext* c) {
        c->IAGetInputLayout(&layout);
        c->IAGetVertexBuffers(0, 1, &vb, &stride, &offset);
        c->IAGetIndexBuffer(&ib, &ib_format, &ib_offset);
        c->VSGetShader(&vs, nullptr, nullptr);
        c->PSGetShader(&ps, nullptr, nullptr);
        c->VSGetConstantBuffers(0, 1, &cb);
        c->PSGetShaderResources(0, 1, &srv);
        c->PSGetSamplers(0, 1, &sampler);
        c->OMGetBlendState(&blend, blend_factor, &sample_mask);
        c->RSGetState(&raster);
        c->OMGetRenderTargets(D3D11_SIMULTANEOUS_RENDER_TARGET_COUNT, rtvs, &dsv);
        c->GSGetShader(&gs, nullptr, nullptr);
        c->HSGetShader(&hs, nullptr, nullptr);
        c->DSGetShader(&ds, nullptr, nullptr);
        c->IAGetPrimitiveTopology(&topology);
        UINT n = 1;
        c->RSGetViewports(&n, &viewport);
    }
    void restore(ID3D11DeviceContext* c) {
        c->IASetInputLayout(layout);
        c->IASetVertexBuffers(0, 1, &vb, &stride, &offset);
        c->IASetIndexBuffer(ib, ib_format, ib_offset);
        c->VSSetShader(vs, nullptr, 0);
        c->PSSetShader(ps, nullptr, 0);
        c->VSSetConstantBuffers(0, 1, &cb);
        c->PSSetShaderResources(0, 1, &srv);
        c->PSSetSamplers(0, 1, &sampler);
        c->OMSetBlendState(blend, blend_factor, sample_mask);
        c->RSSetState(raster);
        c->OMSetRenderTargets(D3D11_SIMULTANEOUS_RENDER_TARGET_COUNT, rtvs, dsv);
        c->GSSetShader(gs, nullptr, 0);
        c->HSSetShader(hs, nullptr, 0);
        c->DSSetShader(ds, nullptr, 0);
        c->IASetPrimitiveTopology(topology);
        c->RSSetViewports(1, &viewport);
        if (layout) layout->Release();
        if (vb) vb->Release();
        if (ib) ib->Release();
        if (vs) vs->Release();
        if (ps) ps->Release();
        if (cb) cb->Release();
        if (srv) srv->Release();
        if (sampler) sampler->Release();
        if (blend) blend->Release();
        if (raster) raster->Release();
        for (auto* v : rtvs) if (v) v->Release();
        if (dsv) dsv->Release();
        if (gs) gs->Release();
        if (hs) hs->Release();
        if (ds) ds->Release();
    }
};

// Draw the captured HUD onto `target` (the game's backbuffer, which we have just filled with the Remix frame).
inline bool draw(ID3D11DeviceContext* context, ID3D11Texture2D* target, const live_capture::UiSnapshot& ui, Pipeline& p,
                 bool opaque = false) {
    const std::vector<live_capture::UiDraw>& draws = ui.draws;
    const std::vector<live_capture::UiVertex>& vertices = ui.verts;
    if (draws.empty() || vertices.empty()) return true;
    ID3D11Device* device = nullptr;
    target->GetDevice(&device);
    if (!device) return false;
    bool ok = ensure(device, p) && ensure_vertices(device, p, static_cast<unsigned>(vertices.size()));
    if (!ok) { device->Release(); return false; }

    D3D11_MAPPED_SUBRESOURCE mapped{};
    if (FAILED(context->Map(p.vertices, 0, D3D11_MAP_WRITE_DISCARD, 0, &mapped))) { device->Release(); return false; }
    std::memcpy(mapped.pData, vertices.data(), vertices.size() * sizeof(live_capture::UiVertex));
    context->Unmap(p.vertices, 0);

    D3D11_TEXTURE2D_DESC desc{};
    target->GetDesc(&desc);
    ID3D11RenderTargetView* view = nullptr;
    if (FAILED(device->CreateRenderTargetView(target, nullptr, &view))) { device->Release(); return false; }

    SavedState saved;
    saved.save(context);          // before we change anything

    D3D11_VIEWPORT vp{0.f, 0.f, static_cast<float>(desc.Width), static_cast<float>(desc.Height), 0.f, 1.f};
    context->RSSetViewports(1, &vp);
    context->OMSetRenderTargets(1, &view, nullptr);
    context->RSSetState(p.raster);
    context->GSSetShader(nullptr, nullptr, 0);
    context->HSSetShader(nullptr, nullptr, 0);
    context->DSSetShader(nullptr, nullptr, 0);
    context->IASetInputLayout(p.layout);
    context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    const UINT stride = sizeof(live_capture::UiVertex), offset = 0;
    context->IASetVertexBuffers(0, 1, &p.vertices, &stride, &offset);
    context->IASetIndexBuffer(nullptr, DXGI_FORMAT_UNKNOWN, 0);
    context->VSSetShader(p.vs, nullptr, 0);
    context->PSSetShader(p.ps, nullptr, 0);
    context->VSSetConstantBuffers(0, 1, &p.constants);
    context->PSSetSamplers(0, 1, &p.sampler);

    context->OMSetBlendState(opaque ? nullptr : p.blend, nullptr, 0xFFFFFFFF);  // the world image ignores its alpha

    for (std::size_t i = 0; i < draws.size(); ++i) {
        const auto& d = draws[i];
        ID3D11ShaderResourceView* srv = i < ui.srvs.size() ? ui.srvs[i] : nullptr;
        if (!srv || !d.count || d.first + d.count > vertices.size()) continue;
        // CB11 is 3x4 row-major: expand to a 4x4 with the last row 0,0,0,1.
        float m[16] = {};
        for (int r = 0; r < 3; ++r)
            for (int c = 0; c < 4; ++c) m[4 * r + c] = d.world[4 * r + c];
        m[15] = 1.f;
        D3D11_MAPPED_SUBRESOURCE cb{};
        if (FAILED(context->Map(p.constants, 0, D3D11_MAP_WRITE_DISCARD, 0, &cb))) { ok = false; break; }
        std::memcpy(cb.pData, m, sizeof m);
        context->Unmap(p.constants, 0);
        context->PSSetShaderResources(0, 1, &srv);
        context->Draw(static_cast<UINT>(d.count), d.first);
    }

    saved.restore(context);
    view->Release();
    device->Release();
    return ok;
}

}  // namespace hud_replay
