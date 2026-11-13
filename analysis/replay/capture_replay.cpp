// Replays the draw stream of an F9 capture (packed by pack_capture.py) through d3d11.dll, every frame, so the proxy's
// live Remix path sees the game's real buffers, layouts, pixel shaders, constant buffers, textures and states without
// the game. With the proxy beside the exe this is "NieR without NieR"; without it, a plain D3D11 load test.
//
// What it is not: the capture has no vertex shaders, so every draw runs a generated VS that puts all vertices at the
// origin (nothing is rasterised, the game's own picture is not reproduced). The proxy reads state on the CPU and
// never needs the rasterised result.
//
// usage: capture_replay.exe <a.manifest> [<b.manifest>]
// env:   REPLAY_FRAMES (600)  REPLAY_FRAME_MS (16)  REPLAY_SIZE=WxH (scene size of the first manifest)
//        REPLAY_SHOTS=60,300  frames at which the stub layer dumps the presented backbuffer to shot-<n>.raw
//        REPLAY_SWITCH=N      with two manifests: show a for N frames, then b for N, and so on (stream-in test)
// writes replay-result.txt (key=value per line) and replay-frames.txt (per frame: total and draw-loop microseconds;
// the rest of the frame is the clear and Present).
#include <windows.h>
#include <d3d11.h>
#include <d3dcompiler.h>
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <string>
#include <tuple>
#include <vector>

namespace {
FILE* out = nullptr;
ID3D11Device* device = nullptr;
ID3D11DeviceContext* context = nullptr;
decltype(&D3DCompile) compile = nullptr;
unsigned missing_shaders = 0, missing_textures = 0, bad_layouts = 0;

std::vector<unsigned char> read_file(const std::string& path) {
    std::vector<unsigned char> data;
    if (FILE* f = std::fopen(path.c_str(), "rb")) {
        std::fseek(f, 0, SEEK_END);
        const long n = std::ftell(f);
        std::fseek(f, 0, SEEK_SET);
        if (n > 0) { data.resize(static_cast<std::size_t>(n)); if (std::fread(data.data(), 1, data.size(), f) != data.size()) data.clear(); }
        std::fclose(f);
    }
    return data;
}

struct Element { std::string semantic; unsigned format = 0, offset = 0, slot = 0; };
struct Slice { unsigned slot = 0, offset = 0, bytes = 0; };
struct VertexBuffer { unsigned slot = 0, stride = 0, offset = 0; int buffer = -1; };
struct Draw {
    unsigned index_count = 0, start_index = 0, instanced = 0, instance_count = 0, start_instance = 0, has_index = 0,
             ib_format = 0, ib_offset = 0, vp_w = 0, vp_h = 0, state[11] = {};
    int base_vertex = 0, ib = -1;
    unsigned long long ps_hash = 0;
    std::vector<VertexBuffer> vbs;
    std::vector<Element> layout;
    std::vector<Slice> vcb, pcb;
    std::vector<std::pair<unsigned, unsigned>> tex;
    ID3D11InputLayout* il = nullptr;
    ID3D11VertexShader* vs = nullptr;
    ID3D11PixelShader* ps = nullptr;
    ID3D11BlendState* blend = nullptr;
    ID3D11DepthStencilState* depth = nullptr;
    ID3D11RasterizerState* raster = nullptr;
    ID3D11RenderTargetView* rtv = nullptr;
    ID3D11DepthStencilView* dsv = nullptr;
};
struct Scene {
    unsigned width = 0, height = 0;
    std::vector<Draw> draws;
    std::vector<unsigned char> cbs;
    std::map<int, ID3D11Buffer*> buffers;
    std::map<unsigned, ID3D11ShaderResourceView*> textures;
    ID3D11ShaderResourceView* lights[2] = {};  // PS slots 20 and 22
};

// ---- shared state objects ---------------------------------------------------------------------
std::map<unsigned long long, ID3D11PixelShader*> pixel_shaders;
std::map<std::string, std::pair<ID3D11VertexShader*, ID3D11InputLayout*>> vertex_shaders;
std::map<std::tuple<unsigned, unsigned, unsigned, unsigned, unsigned>, ID3D11BlendState*> blends;
std::map<std::tuple<unsigned, unsigned, unsigned>, ID3D11DepthStencilState*> depths;
std::map<std::pair<unsigned, unsigned>, ID3D11RasterizerState*> rasters;
struct Target { ID3D11RenderTargetView* rtv = nullptr; ID3D11DepthStencilView* dsv = nullptr; };
std::map<std::tuple<unsigned, unsigned, unsigned>, Target> targets;
struct ConstantBuffer { ID3D11Buffer* buffer = nullptr; long long written = -1; };
std::map<std::tuple<unsigned, unsigned, unsigned>, ConstantBuffer> constant_buffers;  // (stage, slot, bytes)

const char* hlsl_type(unsigned format) {
    switch (format) {
        case 6: return "float3";              // R32G32B32_FLOAT
        case 16: case 34: return "float2";    // R32G32_FLOAT, R16G16_FLOAT
        case 30: return "uint4";              // R8G8B8A8_UINT
        case 41: return "float";              // R32_FLOAT
        default: return "float4";
    }
}

bool make_vertex_shader(Draw& d) {
    std::string key, source = "struct I {";
    std::map<std::string, unsigned> counts;
    std::vector<D3D11_INPUT_ELEMENT_DESC> descs;
    std::vector<unsigned> indices;
    for (const Element& e : d.layout) indices.push_back(counts[e.semantic]++);
    for (std::size_t i = 0; i < d.layout.size(); ++i) {
        const Element& e = d.layout[i];
        char part[160];
        std::snprintf(part, sizeof part, "%s:%u:%u:%u;", e.semantic.c_str(), e.format, e.offset, e.slot);
        key += part;
        std::snprintf(part, sizeof part, " %s a%u : %s%u;", hlsl_type(e.format), static_cast<unsigned>(i), e.semantic.c_str(), indices[i]);
        source += part;
        descs.push_back({e.semantic.c_str(), indices[i], static_cast<DXGI_FORMAT>(e.format), e.slot, e.offset,
                         D3D11_INPUT_PER_VERTEX_DATA, 0});
    }
    source += " };\nfloat4 main(I i) : SV_Position { return float4(0, 0, 0, 1); }\n";
    auto known = vertex_shaders.find(key);
    if (known == vertex_shaders.end()) {
        ID3DBlob *blob = nullptr, *err = nullptr;
        ID3D11VertexShader* vs = nullptr;
        ID3D11InputLayout* il = nullptr;
        if (compile && SUCCEEDED(compile(source.c_str(), source.size(), "vs", nullptr, nullptr, "main", "vs_4_0", 0, 0, &blob, &err)) && blob) {
            device->CreateVertexShader(blob->GetBufferPointer(), blob->GetBufferSize(), nullptr, &vs);
            device->CreateInputLayout(descs.data(), static_cast<UINT>(descs.size()), blob->GetBufferPointer(), blob->GetBufferSize(), &il);
            blob->Release();
        } else if (err) {
            std::fprintf(out, "vs_error=%s\n", static_cast<const char*>(err->GetBufferPointer()));
        }
        if (err) err->Release();
        known = vertex_shaders.emplace(key, std::make_pair(vs, il)).first;
    }
    d.vs = known->second.first;
    d.il = known->second.second;
    return d.vs && d.il;
}

ID3D11PixelShader* pixel_shader(const std::string& dir, unsigned long long hash) {
    auto known = pixel_shaders.find(hash);
    if (known != pixel_shaders.end()) return known->second;
    char name[64];
    std::snprintf(name, sizeof name, "/ps_%llu.dxbc", hash);
    const auto blob = read_file(dir + name);
    ID3D11PixelShader* ps = nullptr;
    if (blob.empty() || FAILED(device->CreatePixelShader(blob.data(), blob.size(), nullptr, &ps))) ++missing_shaders;
    return pixel_shaders[hash] = ps;
}

std::size_t mip_bytes(unsigned format, unsigned w, unsigned h) {
    const std::size_t bw = (w + 3) / 4, bh = (h + 3) / 4;
    switch (format) {
        case 70: case 71: case 72: case 79: case 80: case 81: return bw * bh * 8;                    // BC1, BC4
        case 73: case 74: case 75: case 76: case 77: case 78: case 82: case 83: case 84:
        case 94: case 95: case 96: case 97: case 98: case 99: return bw * bh * 16;                    // BC2/3/5/6/7
        case 27: case 28: case 29: case 87: case 88: case 90: case 91: case 93: return std::size_t(w) * h * 4;
        case 10: return std::size_t(w) * h * 8;                                                       // RGBA16F
        case 61: return std::size_t(w) * h;                                                           // R8
        default: return 0;
    }
}

ID3D11ShaderResourceView* load_texture(const std::string& path) {
    const auto dds = read_file(path);
    const auto u32 = [&](std::size_t at) { unsigned v = 0; std::memcpy(&v, dds.data() + at, 4); return v; };
    if (dds.size() < 148 || std::memcmp(dds.data(), "DDS ", 4) || std::memcmp(dds.data() + 84, "DX10", 4)) return nullptr;
    D3D11_TEXTURE2D_DESC desc{};
    desc.Height = u32(12); desc.Width = u32(16); desc.MipLevels = std::max(1u, u32(28)); desc.ArraySize = 1;
    desc.Format = static_cast<DXGI_FORMAT>(u32(128)); desc.SampleDesc.Count = 1;
    desc.Usage = D3D11_USAGE_IMMUTABLE; desc.BindFlags = D3D11_BIND_SHADER_RESOURCE;
    if (u32(132) != 3 || u32(140) != 1) return nullptr;  // 2D, one slice
    std::vector<D3D11_SUBRESOURCE_DATA> mips;
    std::size_t at = 148;
    for (unsigned m = 0; m < desc.MipLevels; ++m) {
        const unsigned w = std::max(1u, desc.Width >> m), h = std::max(1u, desc.Height >> m);
        const std::size_t bytes = mip_bytes(u32(128), w, h);
        if (!bytes || at + bytes > dds.size()) { if (!m) return nullptr; desc.MipLevels = m; break; }
        mips.push_back({dds.data() + at, static_cast<UINT>(mip_bytes(u32(128), w, 1)), 0});  // pitch: one row, or one block row
        at += bytes;
    }
    ID3D11Texture2D* tex = nullptr;
    ID3D11ShaderResourceView* srv = nullptr;
    if (SUCCEEDED(device->CreateTexture2D(&desc, mips.data(), &tex)) && tex) {
        device->CreateShaderResourceView(tex, nullptr, &srv);
        tex->Release();
    }
    return srv;
}

Target target(unsigned w, unsigned h, unsigned dsv_format) {
    // The shadow atlas is depth-only in the game (no colour target); every other pass gets a colour target of its size.
    const bool depth_only = dsv_format == 40;
    const auto key = std::make_tuple(w, h, dsv_format);
    auto known = targets.find(key);
    if (known != targets.end()) return known->second;
    Target t;
    D3D11_TEXTURE2D_DESC desc{};
    desc.Width = w; desc.Height = h; desc.MipLevels = 1; desc.ArraySize = 1; desc.SampleDesc.Count = 1;
    if (!depth_only) {
        desc.Format = DXGI_FORMAT_R8G8B8A8_UNORM; desc.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;
        ID3D11Texture2D* colour = nullptr;
        if (SUCCEEDED(device->CreateTexture2D(&desc, nullptr, &colour)) && colour) { device->CreateRenderTargetView(colour, nullptr, &t.rtv); colour->Release(); }
    }
    if (dsv_format == 40 || dsv_format == 45) {
        desc.Format = static_cast<DXGI_FORMAT>(dsv_format); desc.BindFlags = D3D11_BIND_DEPTH_STENCIL;
        ID3D11Texture2D* depth = nullptr;
        if (SUCCEEDED(device->CreateTexture2D(&desc, nullptr, &depth)) && depth) { device->CreateDepthStencilView(depth, nullptr, &t.dsv); depth->Release(); }
    }
    return targets[key] = t;
}

void make_states(Draw& d) {
    const unsigned* s = d.state;  // blend_enable src dst op mask | depth_enable depth_write depth_func | cull fill | dsv
    auto& blend = blends[std::make_tuple(s[0], s[1], s[2], s[3], s[4])];
    if (!blend) {
        D3D11_BLEND_DESC desc{};
        auto& rt = desc.RenderTarget[0];
        rt.BlendEnable = s[0] != 0;
        rt.SrcBlend = rt.SrcBlendAlpha = static_cast<D3D11_BLEND>(s[1] ? s[1] : 2);
        rt.DestBlend = rt.DestBlendAlpha = static_cast<D3D11_BLEND>(s[2] ? s[2] : 1);
        rt.BlendOp = rt.BlendOpAlpha = static_cast<D3D11_BLEND_OP>(s[3] ? s[3] : 1);
        rt.RenderTargetWriteMask = static_cast<UINT8>(s[4]);
        device->CreateBlendState(&desc, &blend);
    }
    auto& depth = depths[std::make_tuple(s[5], s[6], s[7])];
    if (!depth) {
        D3D11_DEPTH_STENCIL_DESC desc{};
        desc.DepthEnable = s[5] != 0;
        desc.DepthWriteMask = s[6] ? D3D11_DEPTH_WRITE_MASK_ALL : D3D11_DEPTH_WRITE_MASK_ZERO;
        desc.DepthFunc = static_cast<D3D11_COMPARISON_FUNC>(s[7] ? s[7] : 4);
        device->CreateDepthStencilState(&desc, &depth);
    }
    auto& raster = rasters[std::make_pair(s[8], s[9])];
    if (!raster) {
        D3D11_RASTERIZER_DESC desc{};
        desc.CullMode = static_cast<D3D11_CULL_MODE>(s[8] ? s[8] : 3);
        desc.FillMode = static_cast<D3D11_FILL_MODE>(s[9] ? s[9] : 3);
        desc.DepthClipEnable = TRUE;
        device->CreateRasterizerState(&desc, &raster);
    }
    d.blend = blend; d.depth = depth; d.raster = raster;
}

bool load_scene(const char* manifest, Scene& scene) {
    FILE* f = std::fopen(manifest, "r");
    if (!f) { std::fprintf(out, "FAIL manifest %s\n", manifest); return false; }
    char word[64], path[1024], semantic[64];
    std::string shader_dir;
    Draw* d = nullptr;
    while (std::fscanf(f, "%63s", word) == 1) {
        const std::string w = word;
        if (w == "replay") { int v; std::fscanf(f, "%d", &v); }
        else if (w == "size") std::fscanf(f, "%u %u", &scene.width, &scene.height);
        else if (w == "shaders") { std::fscanf(f, "%1023s", path); shader_dir = path; }
        else if (w == "cbblob") { std::fscanf(f, "%1023s", path); scene.cbs = read_file(path); }
        else if (w == "lights") {
            unsigned slot, stride, count;
            std::fscanf(f, "%u %u %u %1023s", &slot, &stride, &count, path);
            const auto bytes = read_file(path);
            if (!bytes.empty() && stride && count && bytes.size() >= std::size_t(stride) * count) {
                D3D11_BUFFER_DESC desc{};
                desc.ByteWidth = stride * count; desc.Usage = D3D11_USAGE_DEFAULT; desc.BindFlags = D3D11_BIND_SHADER_RESOURCE;
                desc.MiscFlags = D3D11_RESOURCE_MISC_BUFFER_STRUCTURED; desc.StructureByteStride = stride;
                D3D11_SUBRESOURCE_DATA init{bytes.data(), 0, 0};
                ID3D11Buffer* buffer = nullptr;
                if (SUCCEEDED(device->CreateBuffer(&desc, &init, &buffer)) && buffer) {
                    D3D11_SHADER_RESOURCE_VIEW_DESC view{};
                    view.Format = DXGI_FORMAT_UNKNOWN; view.ViewDimension = D3D11_SRV_DIMENSION_BUFFEREX;
                    view.BufferEx.FirstElement = 0; view.BufferEx.NumElements = count;
                    device->CreateShaderResourceView(buffer, &view, &scene.lights[slot == 22 ? 1 : 0]);
                    buffer->Release();
                }
            }
        }
        else if (w == "buffer") {
            int id; unsigned bytes;
            std::fscanf(f, "%d %u %1023s", &id, &bytes, path);
            const auto data = read_file(path);
            D3D11_BUFFER_DESC desc{};
            desc.ByteWidth = static_cast<UINT>(data.size()); desc.Usage = D3D11_USAGE_DEFAULT;
            desc.BindFlags = D3D11_BIND_VERTEX_BUFFER | D3D11_BIND_INDEX_BUFFER;
            D3D11_SUBRESOURCE_DATA init{data.data(), 0, 0};
            ID3D11Buffer* buffer = nullptr;
            if (!data.empty()) device->CreateBuffer(&desc, &init, &buffer);
            scene.buffers[id] = buffer;
        }
        else if (w == "texture") {
            unsigned id;
            std::fscanf(f, "%u %1023s", &id, path);
            if (!(scene.textures[id] = load_texture(path))) ++missing_textures;
        }
        else if (w == "draw") {
            scene.draws.emplace_back();
            d = &scene.draws.back();
            std::fscanf(f, "%u %u %d %u %u %u %u %u %u %d %u %u %llu", &d->index_count, &d->start_index, &d->base_vertex,
                        &d->instanced, &d->instance_count, &d->start_instance, &d->has_index, &d->ib_format, &d->ib_offset,
                        &d->ib, &d->vp_w, &d->vp_h, &d->ps_hash);
        }
        else if (!d) { std::fprintf(out, "FAIL manifest token %s\n", word); std::fclose(f); return false; }
        else if (w == "state") { for (unsigned& v : d->state) std::fscanf(f, "%u", &v); }
        else if (w == "vb") { VertexBuffer v; std::fscanf(f, "%u %u %u %d", &v.slot, &v.stride, &v.offset, &v.buffer); d->vbs.push_back(v); }
        else if (w == "el") { Element e; std::fscanf(f, "%63s %u %u %u", semantic, &e.format, &e.offset, &e.slot); e.semantic = semantic; d->layout.push_back(e); }
        else if (w == "vcb" || w == "pcb") { Slice s; std::fscanf(f, "%u %u %u", &s.slot, &s.offset, &s.bytes); (w == "vcb" ? d->vcb : d->pcb).push_back(s); }
        else if (w == "tex") { unsigned slot, id; std::fscanf(f, "%u %u", &slot, &id); d->tex.emplace_back(slot, id); }
        else if (w == "end") {
            if (!make_vertex_shader(*d)) ++bad_layouts;
            d->ps = pixel_shader(shader_dir, d->ps_hash);
            make_states(*d);
            const Target t = target(d->vp_w, d->vp_h, d->state[10]);
            d->rtv = t.rtv; d->dsv = t.dsv;
            d = nullptr;
        }
        else { std::fprintf(out, "FAIL manifest token %s\n", word); std::fclose(f); return false; }
    }
    std::fclose(f);
    return !scene.draws.empty();
}

ID3D11Buffer* constant_buffer(unsigned stage, const Slice& s, const Scene& scene) {
    auto& cb = constant_buffers[std::make_tuple(stage, s.slot, s.bytes)];
    if (!cb.buffer) {
        D3D11_BUFFER_DESC desc{};
        desc.ByteWidth = (s.bytes + 15) & ~15u; desc.Usage = D3D11_USAGE_DYNAMIC; desc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
        desc.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;
        device->CreateBuffer(&desc, nullptr, &cb.buffer);
    }
    const long long stamp = static_cast<long long>(reinterpret_cast<std::uintptr_t>(&scene) ^ s.offset);
    if (cb.buffer && cb.written != stamp && s.offset + s.bytes <= scene.cbs.size()) {
        // Written the way the game writes per-object constants: a discard map of the whole buffer before the draw.
        D3D11_MAPPED_SUBRESOURCE m{};
        if (SUCCEEDED(context->Map(cb.buffer, 0, D3D11_MAP_WRITE_DISCARD, 0, &m))) {
            std::memcpy(m.pData, scene.cbs.data() + s.offset, s.bytes);
            context->Unmap(cb.buffer, 0);
        }
        cb.written = stamp;
    }
    return cb.buffer;
}

// REPLAY_PROFILE=1: microseconds per call group over the run, to tell which D3D11 call the frame waits in.
bool profile = false;
unsigned long long group_ticks[5] = {};  // targets+states, input assembler, constant buffers, textures, draw call
struct Group {
    unsigned index; LARGE_INTEGER start{};
    explicit Group(unsigned i) : index(i) { if (profile) QueryPerformanceCounter(&start); }
    ~Group() { if (profile) { LARGE_INTEGER end; QueryPerformanceCounter(&end); group_ticks[index] += static_cast<unsigned long long>(end.QuadPart - start.QuadPart); } }
};

void replay(const Scene& scene) {
    ID3D11RenderTargetView* bound_rtv = reinterpret_cast<ID3D11RenderTargetView*>(~std::uintptr_t(0));
    ID3D11DepthStencilView* bound_dsv = nullptr;
    const float blend_factor[4] = {1, 1, 1, 1};
    for (const Draw& d : scene.draws) {
        if (!d.vs || !d.il) continue;
        { Group g(0);
        if (d.rtv != bound_rtv || d.dsv != bound_dsv) {
            context->OMSetRenderTargets(d.rtv ? 1 : 0, d.rtv ? &d.rtv : nullptr, d.dsv);
            bound_rtv = d.rtv; bound_dsv = d.dsv;
        }
        D3D11_VIEWPORT vp{0, 0, static_cast<float>(d.vp_w), static_cast<float>(d.vp_h), 0, 1};
        context->RSSetViewports(1, &vp);
        context->OMSetBlendState(d.blend, blend_factor, 0xffffffff);
        context->OMSetDepthStencilState(d.depth, 0);
        context->RSSetState(d.raster);
        }
        { Group g(1);
        context->IASetInputLayout(d.il);
        context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        // Every slot is set on every draw, unlisted ones to null: the capture lists exactly what was bound, and the proxy
        // range-checks every bound slot, so a binding left over from the previous draw would be a replay artefact.
        ID3D11Buffer* vbs[8] = {};
        UINT strides[8] = {}, offsets[8] = {};
        for (const VertexBuffer& v : d.vbs) {
            const auto b = scene.buffers.find(v.buffer);
            if (v.slot < 8 && b != scene.buffers.end()) { vbs[v.slot] = b->second; strides[v.slot] = v.stride; offsets[v.slot] = v.offset; }
        }
        context->IASetVertexBuffers(0, 8, vbs, strides, offsets);
        const auto ib = scene.buffers.find(d.ib);
        context->IASetIndexBuffer(ib == scene.buffers.end() ? nullptr : ib->second, static_cast<DXGI_FORMAT>(d.ib_format), d.ib_offset);
        context->VSSetShader(d.vs, nullptr, 0);
        context->PSSetShader(d.ps, nullptr, 0);
        }
        { Group g(2);
        ID3D11Buffer* vcbs[14] = {};
        ID3D11Buffer* pcbs[14] = {};
        for (const Slice& s : d.vcb) if (s.slot < 14) vcbs[s.slot] = constant_buffer(0, s, scene);
        for (const Slice& s : d.pcb) if (s.slot < 14) pcbs[s.slot] = constant_buffer(1, s, scene);
        context->VSSetConstantBuffers(0, 14, vcbs);
        context->PSSetConstantBuffers(0, 14, pcbs);
        }
        { Group g(3);
        ID3D11ShaderResourceView* views[23] = {};
        for (const auto& [slot, id] : d.tex) {
            const auto t = scene.textures.find(id);
            if (slot < 23 && t != scene.textures.end()) views[slot] = t->second;
        }
        if (d.rtv) { views[20] = scene.lights[0]; views[22] = scene.lights[1]; }  // not the depth-only shadow pass
        context->PSSetShaderResources(0, 23, views);
        }
        Group g(4);
        if (!d.has_index) context->Draw(d.index_count, d.start_index);
        else if (d.instanced) context->DrawIndexedInstanced(d.index_count, std::max(1u, d.instance_count), d.start_index, d.base_vertex, d.start_instance);
        else context->DrawIndexed(d.index_count, d.start_index, d.base_vertex);
    }
}

unsigned env_u(const char* name, unsigned fallback) {
    const char* e = std::getenv(name);
    return e && *e ? static_cast<unsigned>(std::strtoul(e, nullptr, 10)) : fallback;
}
}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) return 2;
    out = std::fopen("replay-result.txt", "w");
    if (!out) return 2;
    WNDCLASSW wc{}; wc.lpfnWndProc = DefWindowProcW; wc.hInstance = GetModuleHandleW(nullptr); wc.lpszClassName = L"ReplayNier";
    RegisterClassW(&wc);

    HMODULE d3d11 = LoadLibraryW(L"d3d11.dll");
    char loaded[MAX_PATH] = ""; GetModuleFileNameA(d3d11, loaded, MAX_PATH);
    std::fprintf(out, "d3d11=%s\n", loaded);
    auto create = reinterpret_cast<decltype(&D3D11CreateDevice)>(reinterpret_cast<void*>(GetProcAddress(d3d11, "D3D11CreateDevice")));
    if (!create || FAILED(create(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, nullptr, 0, D3D11_SDK_VERSION, &device, nullptr, &context))) {
        std::fprintf(out, "FAIL device\n"); std::fclose(out); return 3;
    }
    FARPROC cp = GetProcAddress(LoadLibraryW(L"d3dcompiler_47.dll"), "D3DCompile");
    std::memcpy(&compile, &cp, sizeof compile);

    std::vector<Scene> scenes(static_cast<std::size_t>(argc - 1));
    const DWORD load_start = GetTickCount();
    for (int i = 1; i < argc; ++i)
        if (!load_scene(argv[i], scenes[static_cast<std::size_t>(i - 1)])) { std::fprintf(out, "FAIL scene %s\n", argv[i]); std::fclose(out); return 3; }
    std::fprintf(out, "load_ms=%lu\ndraws=%zu\nmissing_shaders=%u\nmissing_textures=%u\nbad_layouts=%u\n", GetTickCount() - load_start,
                 scenes[0].draws.size(), missing_shaders, missing_textures, bad_layouts);

    unsigned width = scenes[0].width ? scenes[0].width : 1920, height = scenes[0].height ? scenes[0].height : 1080;
    if (const char* e = std::getenv("REPLAY_SIZE")) std::sscanf(e, "%ux%u", &width, &height);
    RECT rect{0, 0, static_cast<LONG>(width), static_cast<LONG>(height)};
    AdjustWindowRect(&rect, WS_OVERLAPPEDWINDOW, FALSE);
    HWND hwnd = CreateWindowW(wc.lpszClassName, L"replay", WS_OVERLAPPEDWINDOW, 0, 0, rect.right - rect.left, rect.bottom - rect.top,
                              nullptr, nullptr, wc.hInstance, nullptr);
    ShowWindow(hwnd, SW_SHOW); SetForegroundWindow(hwnd); SetFocus(hwnd);
    IDXGIDevice* dxgi = nullptr; IDXGIAdapter* adapter = nullptr; IDXGIFactory* factory = nullptr;
    device->QueryInterface(__uuidof(IDXGIDevice), reinterpret_cast<void**>(&dxgi));
    dxgi->GetAdapter(&adapter);
    adapter->GetParent(__uuidof(IDXGIFactory), reinterpret_cast<void**>(&factory));
    DXGI_SWAP_CHAIN_DESC sd{};
    sd.BufferCount = 2; sd.BufferDesc.Width = width; sd.BufferDesc.Height = height; sd.BufferDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    sd.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT; sd.OutputWindow = hwnd; sd.SampleDesc.Count = 1; sd.Windowed = TRUE;
    sd.SwapEffect = DXGI_SWAP_EFFECT_DISCARD;
    IDXGISwapChain* swapchain = nullptr;
    if (FAILED(factory->CreateSwapChain(device, &sd, &swapchain)) || !swapchain) { std::fprintf(out, "FAIL swapchain\n"); std::fclose(out); return 3; }
    ID3D11Texture2D* back = nullptr; ID3D11RenderTargetView* back_rtv = nullptr;
    swapchain->GetBuffer(0, __uuidof(ID3D11Texture2D), reinterpret_cast<void**>(&back));
    device->CreateRenderTargetView(back, nullptr, &back_rtv);
    std::fprintf(out, "size=%ux%u\n", width, height);
    std::fflush(out);

    HMODULE stub = GetModuleHandleW(L"d3d11_dlaa.dll");
    auto request = stub ? reinterpret_cast<void (*)(const wchar_t*)>(reinterpret_cast<void*>(GetProcAddress(stub, "stub_request_capture"))) : nullptr;
    std::vector<unsigned> shots;
    if (const char* e = std::getenv("REPLAY_SHOTS")) for (const char* p = e; *p;) { shots.push_back(static_cast<unsigned>(std::strtoul(p, const_cast<char**>(&p), 10))); if (*p) ++p; }
    const unsigned frames = env_u("REPLAY_FRAMES", 600), frame_ms = env_u("REPLAY_FRAME_MS", 16), every = env_u("REPLAY_SWITCH", 0);
    profile = env_u("REPLAY_PROFILE", 0) != 0;
    FILE* times = std::fopen("replay-frames.txt", "w");
    LARGE_INTEGER freq, start, now, frame_start;
    QueryPerformanceFrequency(&freq); QueryPerformanceCounter(&start);
    unsigned long long worst_us = 0, total_us = 0;
    unsigned presented = 0;
    for (unsigned frame = 1; frame <= frames; ++frame) {
        MSG msg;
        while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) { TranslateMessage(&msg); DispatchMessageW(&msg); }
        QueryPerformanceCounter(&frame_start);
        const Scene& scene = scenes[every && scenes.size() > 1 ? (frame / every) % scenes.size() : 0];
        replay(scene);
        LARGE_INTEGER drawn;
        QueryPerformanceCounter(&drawn);
        const float clear[4] = {0.02f, 0.03f, 0.08f, 1};
        context->OMSetRenderTargets(1, &back_rtv, nullptr);
        context->ClearRenderTargetView(back_rtv, clear);
        for (unsigned s : shots) if (s == frame && request) { wchar_t name[64]; swprintf(name, 64, L"shot-%u.raw", frame); request(name); }
        if (SUCCEEDED(swapchain->Present(0, 0))) ++presented;
        QueryPerformanceCounter(&now);
        const unsigned long long us = static_cast<unsigned long long>((now.QuadPart - frame_start.QuadPart) * 1000000 / freq.QuadPart);
        if (times) std::fprintf(times, "%llu %llu\n", us, static_cast<unsigned long long>((drawn.QuadPart - frame_start.QuadPart) * 1000000 / freq.QuadPart));
        total_us += us; worst_us = std::max(worst_us, us);
        if (us < frame_ms * 1000ull) Sleep(static_cast<DWORD>(frame_ms - us / 1000));
    }
    if (times) std::fclose(times);
    QueryPerformanceCounter(&now);
    if (profile)
        std::fprintf(out, "profile_us_per_frame=states %llu ia %llu cbs %llu textures %llu draw %llu\n",
                     group_ticks[0] * 1000000 / freq.QuadPart / frames, group_ticks[1] * 1000000 / freq.QuadPart / frames,
                     group_ticks[2] * 1000000 / freq.QuadPart / frames, group_ticks[3] * 1000000 / freq.QuadPart / frames,
                     group_ticks[4] * 1000000 / freq.QuadPart / frames);
    std::fprintf(out, "presented=%u\nframe_avg_us=%llu\nframe_worst_us=%llu\nwall_ms=%llu\n", presented, total_us / std::max(1u, frames), worst_us,
                 static_cast<unsigned long long>((now.QuadPart - start.QuadPart) * 1000 / freq.QuadPart));
    std::fclose(out);
    std::fflush(nullptr);
    // Not ExitProcess: with the real Remix runtime loaded, DLL detach waits on its worker threads forever (230 s seen).
    // REPLAY_EXIT=clean exercises that path on purpose, so item S1 can measure it and take a stack while it hangs.
    if (std::getenv("REPLAY_EXIT") && !std::strcmp(std::getenv("REPLAY_EXIT"), "clean")) {
        std::fprintf(out, "clean-exit-requested\n");
        return 0;   // falling off main() reports the exit code and lets the CRT run the DLL detaches
    }
    TerminateProcess(GetCurrentProcess(), 0);
    return 0;
}
