#pragma once
// E1 diagnostics only: bounded descriptor samples, not geometry capture or a complete effects inventory.
#include <d3d11.h>
#include <algorithm>
#include <cmath>
#include <array>
#include <atomic>
#include <cstdint>
#include <cstring>
#include <iomanip>
#include <mutex>
#include <sstream>
#include <string>
#include <vector>

namespace effect_census {
// Last native-HUD handoff target (pointer identity only, set by remix_live::before_draw); diagnostic comparison.
inline std::atomic<const void*> hud_target{nullptr};
// Set once the native handoff ran in the current frame (reset at Present): effect samples report draw order.
inline std::atomic<bool> handoff_this_frame{false};
// NIER_REMIX_LIVE_EFFECT_CENSUS=handoff: no records until the HUD target is known (the session budget is otherwise
// spent at world entry, long before the first handoff).
inline std::atomic<bool> defer_until_handoff{false};
inline std::atomic<bool> enabled{false};
inline std::mutex pending_mutex;
inline std::vector<std::string> pending;
inline std::uint64_t last_frame = ~std::uint64_t{0};
inline unsigned frame_records = 0, session_records = 0;
inline bool limited = false, limit_reported = false;
inline constexpr unsigned frame_limit = 64, session_limit = 256;

inline bool reserve(std::uint64_t frame) {
    std::lock_guard<std::mutex> lock(pending_mutex);
    if (frame != last_frame) { last_frame = frame; frame_records = 0; }
    if (session_records >= session_limit || frame_records >= frame_limit) { limited = true; return false; }
    ++session_records;
    ++frame_records;
    return true;
}

struct Batch { std::vector<std::string> records; bool truncated = false; };
inline Batch take() {
    Batch out;
    if (!enabled.load(std::memory_order_relaxed)) return out;
    std::lock_guard<std::mutex> lock(pending_mutex);
    out.records.swap(pending);
    out.truncated = limited && !limit_reported;
    if (out.truncated) limit_reported = true;
    return out;
}

// Copy descriptors and release all getter references BEFORE formatting (which may allocate/throw).
struct Srv {
    unsigned slot = 0, stride = 0, first = 0, count = 0, dimension = 0, format = 0;
    const char* kind = "unsupported";
};
inline std::string resources(ID3D11DeviceContext* context, bool vertex) {
    std::array<ID3D11ShaderResourceView*, D3D11_COMMONSHADER_INPUT_RESOURCE_SLOT_COUNT> views{};
    std::array<Srv, D3D11_COMMONSHADER_INPUT_RESOURCE_SLOT_COUNT> items{};
    unsigned used = 0;
    if (vertex) context->VSGetShaderResources(0, static_cast<UINT>(views.size()), views.data());
    else context->PSGetShaderResources(0, static_cast<UINT>(views.size()), views.data());
    for (unsigned slot = 0; slot < views.size(); ++slot) {
        auto* view = views[slot];
        if (!view) continue;
        Srv item; item.slot = slot;
        D3D11_SHADER_RESOURCE_VIEW_DESC desc{};
        view->GetDesc(&desc);
        item.dimension = static_cast<unsigned>(desc.ViewDimension);
        item.format = static_cast<unsigned>(desc.Format);
        ID3D11Resource* resource = nullptr;
        view->GetResource(&resource);
        ID3D11Buffer* buffer = nullptr;
        if (resource && SUCCEEDED(resource->QueryInterface(__uuidof(ID3D11Buffer), reinterpret_cast<void**>(&buffer)))) {
            D3D11_BUFFER_DESC bd{};
            buffer->GetDesc(&bd);
            if (desc.ViewDimension == D3D11_SRV_DIMENSION_BUFFER || desc.ViewDimension == D3D11_SRV_DIMENSION_BUFFEREX) {
                item.kind = bd.MiscFlags & D3D11_RESOURCE_MISC_BUFFER_STRUCTURED ? "structured" :
                            bd.MiscFlags & D3D11_RESOURCE_MISC_BUFFER_ALLOW_RAW_VIEWS ? "raw" : "typed-buffer";
                item.stride = bd.StructureByteStride;
                if (desc.ViewDimension == D3D11_SRV_DIMENSION_BUFFEREX) {
                    item.first = desc.BufferEx.FirstElement; item.count = desc.BufferEx.NumElements;
                } else { item.first = desc.Buffer.FirstElement; item.count = desc.Buffer.NumElements; }
            }
            buffer->Release();
        } else if (resource) {
            switch (desc.ViewDimension) {
                case D3D11_SRV_DIMENSION_TEXTURE1D: case D3D11_SRV_DIMENSION_TEXTURE1DARRAY: item.kind = "texture1d"; break;
                case D3D11_SRV_DIMENSION_TEXTURE2D: case D3D11_SRV_DIMENSION_TEXTURE2DARRAY:
                case D3D11_SRV_DIMENSION_TEXTURE2DMS: case D3D11_SRV_DIMENSION_TEXTURE2DMSARRAY: item.kind = "texture2d"; break;
                case D3D11_SRV_DIMENSION_TEXTURE3D: item.kind = "texture3d"; break;
                case D3D11_SRV_DIMENSION_TEXTURECUBE: case D3D11_SRV_DIMENSION_TEXTURECUBEARRAY: item.kind = "cube"; break;
                default: break;
            }
        }
        if (resource) resource->Release();
        view->Release();
        items[used++] = item;
    }
    std::ostringstream out;
    out << '[';
    for (unsigned i = 0; i < used; ++i) {
        const auto& v = items[i];
        if (i) out << ',';
        out << "{\"slot\":" << v.slot << ",\"kind\":\"" << v.kind << '"';
        if (std::strcmp(v.kind, "structured") == 0 || std::strcmp(v.kind, "raw") == 0 || std::strcmp(v.kind, "typed-buffer") == 0)
            out << ",\"stride\":" << v.stride << ",\"first\":" << v.first << ",\"count\":" << v.count;
        else out << ",\"dimension\":" << v.dimension << ",\"format\":" << v.format;
        out << '}';
    }
    out << ']';
    return out.str();
}

inline void sample(ID3D11DeviceContext* context, std::uint64_t frame, std::uint64_t code,
                   unsigned indices, unsigned instances, unsigned minimum) {
    if (!enabled.load(std::memory_order_relaxed)) return;
    if (defer_until_handoff.load(std::memory_order_relaxed)) {
        // Only the identified HUD target: the per-frame cap is otherwise spent on scene-target effects drawn earlier.
        const void* hud = hud_target.load(std::memory_order_relaxed);
        if (!hud) return;
        ID3D11RenderTargetView* view = nullptr;
        context->OMGetRenderTargets(1, &view, nullptr);
        ID3D11Resource* resource = nullptr;
        if (view) { view->GetResource(&resource); view->Release(); }
        if (resource) resource->Release();  // pointer identity only
        if (resource != hud) return;
    }
    if (!reserve(frame)) return;
    const bool after_handoff = handoff_this_frame.load(std::memory_order_relaxed);
    D3D11_PRIMITIVE_TOPOLOGY topology{};
    context->IAGetPrimitiveTopology(&topology);
    D3D11_RENDER_TARGET_BLEND_DESC rt_blend{};
    rt_blend.SrcBlend = rt_blend.SrcBlendAlpha = D3D11_BLEND_ONE;
    rt_blend.DestBlend = rt_blend.DestBlendAlpha = D3D11_BLEND_ZERO;
    rt_blend.BlendOp = rt_blend.BlendOpAlpha = D3D11_BLEND_OP_ADD;
    rt_blend.RenderTargetWriteMask = D3D11_COLOR_WRITE_ENABLE_ALL;
    ID3D11BlendState* blend = nullptr;
    UINT sample_mask = 0;
    context->OMGetBlendState(&blend, nullptr, &sample_mask);
    bool alpha_to_coverage = false, independent_blend = false;
    if (blend) {
        D3D11_BLEND_DESC desc{}; blend->GetDesc(&desc); blend->Release();
        rt_blend = desc.RenderTarget[0];
        alpha_to_coverage = desc.AlphaToCoverageEnable != FALSE;
        independent_blend = desc.IndependentBlendEnable != FALSE;
    }
    D3D11_DEPTH_STENCIL_DESC depth{};
    depth.DepthEnable = TRUE; depth.DepthWriteMask = D3D11_DEPTH_WRITE_MASK_ALL; depth.DepthFunc = D3D11_COMPARISON_LESS;
    ID3D11DepthStencilState* depth_state = nullptr;
    context->OMGetDepthStencilState(&depth_state, nullptr);
    if (depth_state) { depth_state->GetDesc(&depth); depth_state->Release(); }
    unsigned format = 0, width = 0, height = 0, samples = 0;
    const void* rt_resource = nullptr;
    bool target_supported = false;
    ID3D11RenderTargetView* target = nullptr;
    context->OMGetRenderTargets(1, &target, nullptr);  // slot 0 only; additional targets are outside this diagnostic schema
    if (target) {
        D3D11_RENDER_TARGET_VIEW_DESC vd{}; target->GetDesc(&vd);
        format = static_cast<unsigned>(vd.Format);
        ID3D11Resource* resource = nullptr; target->GetResource(&resource);
        rt_resource = resource;
        ID3D11Texture2D* texture = nullptr;
        if (resource && SUCCEEDED(resource->QueryInterface(__uuidof(ID3D11Texture2D), reinterpret_cast<void**>(&texture)))) {
            D3D11_TEXTURE2D_DESC td{}; texture->GetDesc(&td); texture->Release();
            unsigned mip = 0;
            switch (vd.ViewDimension) {
                case D3D11_RTV_DIMENSION_TEXTURE2D: mip = vd.Texture2D.MipSlice; target_supported = true; break;
                case D3D11_RTV_DIMENSION_TEXTURE2DARRAY: mip = vd.Texture2DArray.MipSlice; target_supported = true; break;
                case D3D11_RTV_DIMENSION_TEXTURE2DMS: case D3D11_RTV_DIMENSION_TEXTURE2DMSARRAY: target_supported = true; break;
                default: break;
            }
            if (target_supported) {
                width = mip < 32 ? std::max(1u, td.Width >> mip) : 1u;
                height = mip < 32 ? std::max(1u, td.Height >> mip) : 1u;
                samples = td.SampleDesc.Count;
            }
        }
        if (resource) resource->Release();
        target->Release();
    }
    std::ostringstream out;
    out << std::boolalpha << "{\"version\":1,\"frame\":" << frame << ",\"ps_code\":\""
        << std::hex << std::setw(16) << std::setfill('0') << code << std::dec << "\",\"indices\":" << indices
        << ",\"instances\":" << instances << ",\"small\":" << (indices < minimum)
        << ",\"topology\":" << static_cast<unsigned>(topology)
        << ",\"blend\":{\"enable\":" << (rt_blend.BlendEnable != FALSE)
        << ",\"src\":" << rt_blend.SrcBlend << ",\"dst\":" << rt_blend.DestBlend << ",\"op\":" << rt_blend.BlendOp
        << ",\"src_alpha\":" << rt_blend.SrcBlendAlpha << ",\"dst_alpha\":" << rt_blend.DestBlendAlpha
        << ",\"op_alpha\":" << rt_blend.BlendOpAlpha << ",\"write_mask\":" << static_cast<unsigned>(rt_blend.RenderTargetWriteMask) << '}'
        << ",\"rt\":{\"format\":" << format << ",\"width\":" << width << ",\"height\":" << height << ",\"samples\":" << samples << '}'
        << ",\"depth\":{\"enabled\":" << (depth.DepthEnable != FALSE)
        << ",\"write\":" << (depth.DepthWriteMask == D3D11_DEPTH_WRITE_MASK_ALL) << ",\"func\":" << depth.DepthFunc << '}'
        << ",\"alpha_to_coverage\":" << alpha_to_coverage << ",\"independent_blend\":" << independent_blend
        << ",\"sample_mask\":" << sample_mask << ",\"stencil_enabled\":" << (depth.StencilEnable != FALSE)
        << ",\"target_slot\":0,\"rt_supported\":" << target_supported
        << ",\"after_hud_handoff\":" << after_handoff
        << ",\"rt_resource\":\"0x" << std::hex << reinterpret_cast<std::uintptr_t>(rt_resource)
        << "\",\"hud_target_resource\":\"0x" << reinterpret_cast<std::uintptr_t>(hud_target.load(std::memory_order_relaxed)) << std::dec << '"'
        << ",\"srv_ps\":" << resources(context, false) << ",\"srv_vs\":" << resources(context, true) << '}';
    std::lock_guard<std::mutex> lock(pending_mutex);
    pending.push_back(out.str());
}

// W1.1 sky-candidate census (NIER_REMIX_LIVE_SKY_CENSUS=1): one record per geometry build with world extent > 1000.
inline std::atomic<bool> sky_enabled{false};
inline std::vector<std::string> sky_pending;   // guarded by pending_mutex
inline unsigned sky_records = 0;
inline constexpr unsigned sky_limit = 64;

inline std::string constant_buffers(ID3D11DeviceContext* context, bool vertex) {
    std::array<ID3D11Buffer*, D3D11_COMMONSHADER_CONSTANT_BUFFER_API_SLOT_COUNT> buffers{};
    std::array<unsigned, D3D11_COMMONSHADER_CONSTANT_BUFFER_API_SLOT_COUNT> bytes{};
    if (vertex) context->VSGetConstantBuffers(0, static_cast<UINT>(buffers.size()), buffers.data());
    else context->PSGetConstantBuffers(0, static_cast<UINT>(buffers.size()), buffers.data());
    for (std::size_t i = 0; i < buffers.size(); ++i)
        if (buffers[i]) { D3D11_BUFFER_DESC d{}; buffers[i]->GetDesc(&d); bytes[i] = d.ByteWidth; buffers[i]->Release(); }
    std::ostringstream out;
    out << '[';
    bool first = true;
    for (std::size_t i = 0; i < bytes.size(); ++i)
        if (bytes[i]) { out << (first ? "" : ",") << "{\"slot\":" << i << ",\"bytes\":" << bytes[i] << '}'; first = false; }
    out << ']';
    return out.str();
}

inline std::string sky_textures(ID3D11DeviceContext* context) {
    std::array<ID3D11ShaderResourceView*, D3D11_COMMONSHADER_INPUT_RESOURCE_SLOT_COUNT> views{};
    context->PSGetShaderResources(0, static_cast<UINT>(views.size()), views.data());
    struct Item { unsigned slot, format, width, height; const char* kind; };
    std::vector<Item> items;
    for (unsigned slot = 0; slot < views.size(); ++slot) {
        if (!views[slot]) continue;
        D3D11_SHADER_RESOURCE_VIEW_DESC d{}; views[slot]->GetDesc(&d);
        Item item{slot, static_cast<unsigned>(d.Format), 0, 0, "other"};
        if (d.ViewDimension == D3D11_SRV_DIMENSION_TEXTURE2D || d.ViewDimension == D3D11_SRV_DIMENSION_TEXTURECUBE) {
            item.kind = d.ViewDimension == D3D11_SRV_DIMENSION_TEXTURE2D ? "texture2d" : "cube";
            ID3D11Resource* resource = nullptr; views[slot]->GetResource(&resource);
            ID3D11Texture2D* texture = nullptr;
            if (resource && SUCCEEDED(resource->QueryInterface(__uuidof(ID3D11Texture2D), reinterpret_cast<void**>(&texture)))) {
                D3D11_TEXTURE2D_DESC td{}; texture->GetDesc(&td); texture->Release();
                item.width = td.Width; item.height = td.Height;
            }
            if (resource) resource->Release();
            if (!item.width) item.kind = "other";   // unreadable size: never claim a texture without dimensions
        }
        views[slot]->Release();
        items.push_back(item);
    }
    std::ostringstream out;
    out << '[';
    for (std::size_t i = 0; i < items.size(); ++i)
        out << (i ? "," : "") << "{\"slot\":" << items[i].slot << ",\"kind\":\"" << items[i].kind << "\",\"format\":" << items[i].format
            << ",\"width\":" << items[i].width << ",\"height\":" << items[i].height << '}';
    out << ']';
    return out.str();
}

inline void sky(ID3D11DeviceContext* context, std::uint64_t frame, std::uint64_t code, unsigned indices, unsigned instances, float extent) {
    if (!sky_enabled.load(std::memory_order_relaxed) || !std::isfinite(extent)) return;  // inf/NaN: invalid JSON
    {
        std::lock_guard<std::mutex> lock(pending_mutex);
        if (sky_records >= sky_limit) {
            if (sky_records == sky_limit) { ++sky_records; sky_pending.push_back("limit"); }  // one notice, then silence
            return;
        }
        ++sky_records;
    }
    unsigned format = 0, width = 0, height = 0;
    ID3D11RenderTargetView* target = nullptr;
    context->OMGetRenderTargets(1, &target, nullptr);
    if (target) {
        D3D11_RENDER_TARGET_VIEW_DESC vd{}; target->GetDesc(&vd); format = static_cast<unsigned>(vd.Format);
        ID3D11Resource* resource = nullptr; target->GetResource(&resource);
        ID3D11Texture2D* texture = nullptr;
        if (resource && SUCCEEDED(resource->QueryInterface(__uuidof(ID3D11Texture2D), reinterpret_cast<void**>(&texture)))) {
            D3D11_TEXTURE2D_DESC td{}; texture->GetDesc(&td); texture->Release(); width = td.Width; height = td.Height;
        }
        if (resource) resource->Release();
        target->Release();
    }
    std::ostringstream out;
    out << std::boolalpha << "{\"version\":1,\"frame\":" << frame << ",\"ps_code\":\""
        << std::hex << std::setw(16) << std::setfill('0') << code << std::dec << std::setfill(' ') << "\",\"indices\":" << indices
        << ",\"instances\":" << std::max(1u, instances) << ",\"extent\":" << std::setprecision(9) << extent << ",\"is_sky\":" << (extent > 5000.f)
        << ",\"srv_ps\":" << sky_textures(context) << ",\"vs_cbs\":" << constant_buffers(context, true)
        << ",\"ps_cbs\":" << constant_buffers(context, false)
        << ",\"rt\":{\"format\":" << format << ",\"width\":" << width << ",\"height\":" << height << "}}";
    std::lock_guard<std::mutex> lock(pending_mutex);
    sky_pending.push_back(out.str());
}

inline std::vector<std::string> take_sky() {
    std::vector<std::string> out;
    if (!sky_enabled.load(std::memory_order_relaxed)) return out;
    std::lock_guard<std::mutex> lock(pending_mutex);
    out.swap(sky_pending);
    return out;
}
} // namespace effect_census
