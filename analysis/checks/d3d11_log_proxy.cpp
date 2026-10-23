// Measurement only; chainloads renamed NIER_DLAA without changing render state.
// Build/test offline. Renamed-module routing and game compatibility remain unverified.
#include <windows.h>
#include <d3d11.h>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <cwchar>
#include <string>
#include "d3d11_hook_registry.h"
#include "d3d11_trace_abi.h"

static HMODULE real_d3d11 = nullptr;
static D3D11HookRegistry hooks;
static thread_local unsigned long long active_draw = 0;

typedef HRESULT (WINAPI *PFN_CreateDevice)(IDXGIAdapter*, D3D_DRIVER_TYPE, HMODULE, UINT,
    const D3D_FEATURE_LEVEL*, UINT, UINT, ID3D11Device**, D3D_FEATURE_LEVEL*, ID3D11DeviceContext**);
typedef HRESULT (WINAPI *PFN_CreateDeviceAndSwapChain)(IDXGIAdapter*, D3D_DRIVER_TYPE, HMODULE, UINT,
    const D3D_FEATURE_LEVEL*, UINT, UINT, const DXGI_SWAP_CHAIN_DESC*, IDXGISwapChain**, ID3D11Device**,
    D3D_FEATURE_LEVEL*, ID3D11DeviceContext**);

static PFN_CreateDevice real_CreateDevice = nullptr;
static PFN_CreateDeviceAndSwapChain real_CreateDeviceAndSwapChain = nullptr;

typedef HRESULT (STDMETHODCALLTYPE *CreateTexture2D_t)(ID3D11Device*, const D3D11_TEXTURE2D_DESC*,
    const D3D11_SUBRESOURCE_DATA*, ID3D11Texture2D**);
typedef void (STDMETHODCALLTYPE *RSSetViewports_t)(ID3D11DeviceContext*, UINT, const D3D11_VIEWPORT*);

typedef HRESULT (STDMETHODCALLTYPE *CreateDeferredContext_t)(ID3D11Device*, UINT, ID3D11DeviceContext**);

static unsigned long long logf_line(const char* fmt, ...)
{
    const DWORD error = GetLastError();
    static std::mutex mutex;
    std::lock_guard<std::mutex> lock(mutex);
    static FILE* file = fopen("texture-map.log", "a");
    static unsigned long long sequence = 0;
    const auto event = ++sequence;
    if (file) {
        // Bound disk growth; a truncated trace is explicitly invalid for reconstruction.
        if (event > 100000) {
            if (event == 100001) { fputs("ERROR: CAPTURE_TRUNCATED event_limit=100000\n", file); fflush(file); }
            SetLastError(error);
            return 0;
        }
        va_list ap; va_start(ap, fmt);
        fprintf(file, "pid=%lu tid=%lu event=%llu draw=%llu ", static_cast<unsigned long>(GetCurrentProcessId()),
            static_cast<unsigned long>(GetCurrentThreadId()), event, active_draw);
        vfprintf(file, fmt, ap); fputc('\n', file); fflush(file);
        va_end(ap);
    } else {
        OutputDebugStringA("D3D11 logger: cannot open texture-map.log; capture unavailable\n");
    }
    SetLastError(error);
    return event;
}

template<class Function>
static Function original(void** slot)
{
    void* address = hooks.original(slot);
    Function function = nullptr;
    static_assert(sizeof(function) == sizeof(address));
    std::memcpy(&function, &address, sizeof(function));
    return function;
}

static const char* usage_name(D3D11_USAGE u)
{
    switch (u) { case D3D11_USAGE_DEFAULT: return "DEFAULT"; case D3D11_USAGE_IMMUTABLE: return "IMMUTABLE";
        case D3D11_USAGE_DYNAMIC: return "DYNAMIC"; case D3D11_USAGE_STAGING: return "STAGING"; default: return "?"; }
}

static bool patch_slot(void** slot, void* expected, void* hook)
{
    DWORD protection = 0;
    if (!VirtualProtect(slot, sizeof(void*), PAGE_READWRITE, &protection)) {
        logf_line("ERROR: VirtualProtect failed slot=%p error=%lu", static_cast<void*>(slot),
            static_cast<unsigned long>(GetLastError()));
        return false;
    }
    void* previous = InterlockedCompareExchangePointer(slot, hook, expected);
    DWORD unused = 0;
    if (!VirtualProtect(slot, sizeof(void*), protection, &unused))
        logf_line("ERROR: protection restoration failed slot=%p error=%lu; capture incomplete",
            static_cast<void*>(slot), static_cast<unsigned long>(GetLastError()));
    return previous == expected;
}

struct ResourceInfo {
    void* identity = nullptr;
    D3D11_RESOURCE_DIMENSION dimension = D3D11_RESOURCE_DIMENSION_UNKNOWN;
    D3D11_TEXTURE2D_DESC texture{};
};

static ResourceInfo resource_info(ID3D11Resource* resource)
{
    ResourceInfo info;
    if (!resource) return info;
    IUnknown* identity = nullptr;
    if (SUCCEEDED(resource->QueryInterface(__uuidof(IUnknown), reinterpret_cast<void**>(&identity)))) {
        info.identity = identity;
        identity->Release();
    }
    resource->GetType(&info.dimension);
    ID3D11Texture2D* texture = nullptr;
    if (info.dimension == D3D11_RESOURCE_DIMENSION_TEXTURE2D &&
        SUCCEEDED(resource->QueryInterface(__uuidof(ID3D11Texture2D), reinterpret_cast<void**>(&texture)))) {
        texture->GetDesc(&info.texture);
        texture->Release();
    }
    return info;
}

static void trace_view(ID3D11DeviceContext* ctx, const char* stage, UINT slot, ID3D11View* view)
{
    ID3D11Resource* resource = nullptr;
    if (view) view->GetResource(&resource);
    const auto info = resource_info(resource);
    logf_line("View ctx=%p stage=%s slot=%u view=%p resource=%p id=%p dim=%u w=%u h=%u fmt=%u mips=%u array=%u",
        static_cast<void*>(ctx), stage, slot, static_cast<void*>(view), static_cast<void*>(resource),
        info.identity, static_cast<unsigned>(info.dimension), info.texture.Width, info.texture.Height,
        static_cast<unsigned>(info.texture.Format), info.texture.MipLevels, info.texture.ArraySize);
    if (resource) resource->Release();
}

static void trace_srvs(ID3D11DeviceContext* ctx, bool compute, UINT start, UINT count,
    ID3D11ShaderResourceView* const* requested)
{
    if (start > D3D11_COMMONSHADER_INPUT_RESOURCE_SLOT_COUNT ||
        count > D3D11_COMMONSHADER_INPUT_RESOURCE_SLOT_COUNT - start) {
        logf_line("ERROR: SRV trace range invalid; capture incomplete"); return;
    }
    const bool observed = ctx->GetType() == D3D11_DEVICE_CONTEXT_IMMEDIATE;
    ID3D11ShaderResourceView* views[D3D11_COMMONSHADER_INPUT_RESOURCE_SLOT_COUNT]{};
    if (observed && count) {
        if (compute) ctx->CSGetShaderResources(start, count, views);
        else ctx->PSGetShaderResources(start, count, views);
    }
    for (UINT i = 0; i < count; ++i) {
        auto* view = observed ? views[i] : requested ? requested[i] : nullptr;
        trace_view(ctx, compute ? (observed ? "CS-observed" : "CS-requested") :
            (observed ? "PS-observed" : "PS-requested"), start + i, view);
        if (observed && view) view->Release();
    }
}

static void trace_targets(ID3D11DeviceContext* ctx, UINT count,
    ID3D11RenderTargetView* const* requested, ID3D11DepthStencilView* requested_depth)
{
    const bool observed = ctx->GetType() == D3D11_DEVICE_CONTEXT_IMMEDIATE;
    if (!observed && count == D3D11_KEEP_RENDER_TARGETS_AND_DEPTH_STENCIL) {
        logf_line("RT-keep ctx=%p deferred=1", static_cast<void*>(ctx)); return;
    }
    if (!observed && count > D3D11_SIMULTANEOUS_RENDER_TARGET_COUNT) {
        logf_line("ERROR: RTV trace range invalid; capture incomplete"); return;
    }
    ID3D11RenderTargetView* views[D3D11_SIMULTANEOUS_RENDER_TARGET_COUNT]{};
    ID3D11DepthStencilView* depth = nullptr;
    if (observed) ctx->OMGetRenderTargets(D3D11_SIMULTANEOUS_RENDER_TARGET_COUNT, views, &depth);
    const UINT slots = observed ? D3D11_SIMULTANEOUS_RENDER_TARGET_COUNT : count;
    logf_line("RT-%s ctx=%p slots=%u", observed ? "observed" : "requested", static_cast<void*>(ctx), slots);
    for (UINT i = 0; i < slots; ++i) {
        auto* view = observed ? views[i] : requested ? requested[i] : nullptr;
        if (view || i == 0) trace_view(ctx, observed ? "RTV-observed" : "RTV-requested", i, view);
        if (observed && view) view->Release();
    }
    trace_view(ctx, observed ? "DSV-observed" : "DSV-requested", 0, observed ? depth : requested_depth);
    if (depth) depth->Release();
}

static void trace_uavs(ID3D11DeviceContext* ctx, bool compute, UINT start, UINT count,
    ID3D11UnorderedAccessView* const* requested)
{
    const bool observed = ctx->GetType() == D3D11_DEVICE_CONTEXT_IMMEDIATE;
    if (count == D3D11_KEEP_UNORDERED_ACCESS_VIEWS) {
        logf_line("UAV-keep ctx=%p observed=%d", static_cast<void*>(ctx), observed);
        if (!observed) return;
        start = 0; count = D3D11_PS_CS_UAV_REGISTER_COUNT;
    }
    // shortcut: queries cover base FL11_0 UAV slots; expand if higher slots are used.
    if (start > D3D11_PS_CS_UAV_REGISTER_COUNT || count > D3D11_PS_CS_UAV_REGISTER_COUNT - start) {
        logf_line("ERROR: UAV trace exceeds base slots; capture incomplete"); return;
    }
    ID3D11UnorderedAccessView* views[D3D11_PS_CS_UAV_REGISTER_COUNT]{};
    if (observed && count) {
        if (compute) ctx->CSGetUnorderedAccessViews(start, count, views);
        else ctx->OMGetRenderTargetsAndUnorderedAccessViews(0, nullptr, nullptr, start, count, views);
    }
    for (UINT i = 0; i < count; ++i) {
        auto* view = observed ? views[i] : requested ? requested[i] : nullptr;
        trace_view(ctx, compute ? (observed ? "CSUAV-observed" : "CSUAV-requested") :
            (observed ? "OMUAV-observed" : "OMUAV-requested"), start + i, view);
        if (observed && view) view->Release();
    }
}

static unsigned long long trace_copy(ID3D11DeviceContext* ctx, const char* method, ID3D11Resource* dst, ID3D11Resource* src)
{
    const auto from = resource_info(src), to = resource_info(dst);
    return logf_line("%s ctx=%p src=%p src_id=%p src_dim=%u src_w=%u src_h=%u src_fmt=%u dst=%p dst_id=%p dst_dim=%u dst_w=%u dst_h=%u dst_fmt=%u",
        method, static_cast<void*>(ctx), static_cast<void*>(src), from.identity, static_cast<unsigned>(from.dimension),
        from.texture.Width, from.texture.Height, static_cast<unsigned>(from.texture.Format),
        static_cast<void*>(dst), to.identity, static_cast<unsigned>(to.dimension), to.texture.Width, to.texture.Height,
        static_cast<unsigned>(to.texture.Format));
}

struct DrawScope {
    unsigned long long saved = active_draw;
    DrawScope(ID3D11DeviceContext* ctx, const char* method) {
        const DWORD error = GetLastError();
        const bool immediate = ctx->GetType() == D3D11_DEVICE_CONTEXT_IMMEDIATE;
        active_draw = logf_line("%s-entry ctx=%p immediate=%d", method, static_cast<void*>(ctx), immediate);
        if (immediate) {
            ID3D11PixelShader* shader = nullptr;
            ctx->PSGetShader(&shader, nullptr, nullptr);
            logf_line("PS-shader ctx=%p shader=%p", static_cast<void*>(ctx), static_cast<void*>(shader));
            if (shader) shader->Release();
            trace_srvs(ctx, false, 0, 1, nullptr);
            trace_targets(ctx, 0, nullptr, nullptr);
        }
        SetLastError(error);
    }
    ~DrawScope() { active_draw = saved; }
};

static void STDMETHODCALLTYPE hook_PSSetShaderResources(ID3D11DeviceContext* ctx, UINT start, UINT n, ID3D11ShaderResourceView* const* views)
{
    const auto call = original<TraceABI::SetSRVs>(&(*(void***)ctx)[8]);
    if (!call) { logf_line("ERROR: missing PS SRV original"); return; }
    call(ctx, start, n, views); const DWORD error = GetLastError();
    logf_line("PSSetShaderResources ctx=%p start=%u count=%u", static_cast<void*>(ctx), start, n);
    trace_srvs(ctx, false, start, n, views); SetLastError(error);
}

static void STDMETHODCALLTYPE hook_CSSetShaderResources(ID3D11DeviceContext* ctx, UINT start, UINT n, ID3D11ShaderResourceView* const* views)
{
    const auto call = original<TraceABI::SetSRVs>(&(*(void***)ctx)[67]);
    if (!call) { logf_line("ERROR: missing CS SRV original"); return; }
    call(ctx, start, n, views); const DWORD error = GetLastError();
    logf_line("CSSetShaderResources ctx=%p start=%u count=%u", static_cast<void*>(ctx), start, n);
    trace_srvs(ctx, true, start, n, views); SetLastError(error);
}

static void STDMETHODCALLTYPE hook_OMSetRenderTargets(ID3D11DeviceContext* ctx, UINT n, ID3D11RenderTargetView* const* views, ID3D11DepthStencilView* depth)
{
    const auto call = original<TraceABI::SetRTs>(&(*(void***)ctx)[33]);
    if (!call) { logf_line("ERROR: missing RT original"); return; }
    call(ctx, n, views, depth); const DWORD error = GetLastError();
    logf_line("OMSetRenderTargets ctx=%p requested_count=%u", static_cast<void*>(ctx), n);
    trace_targets(ctx, n, views, depth); SetLastError(error);
}

static void STDMETHODCALLTYPE hook_OMSetRenderTargetsAndUnorderedAccessViews(ID3D11DeviceContext* ctx, UINT n,
    ID3D11RenderTargetView* const* rtvs, ID3D11DepthStencilView* depth, UINT start, UINT count,
    ID3D11UnorderedAccessView* const* uavs, const UINT* initial)
{
    const auto call = original<TraceABI::SetRTsUAVs>(&(*(void***)ctx)[34]);
    if (!call) { logf_line("ERROR: missing RT/UAV original"); return; }
    call(ctx, n, rtvs, depth, start, count, uavs, initial); const DWORD error = GetLastError();
    logf_line("OMSetRenderTargetsAndUnorderedAccessViews ctx=%p rts=%u start=%u count=%u", static_cast<void*>(ctx), n, start, count);
    trace_targets(ctx, n, rtvs, depth); trace_uavs(ctx, false, start, count, uavs); SetLastError(error);
}

static void STDMETHODCALLTYPE hook_CSSetUnorderedAccessViews(ID3D11DeviceContext* ctx, UINT start, UINT n,
    ID3D11UnorderedAccessView* const* views, const UINT* initial)
{
    const auto call = original<TraceABI::SetUAVs>(&(*(void***)ctx)[68]);
    if (!call) { logf_line("ERROR: missing CS UAV original"); return; }
    call(ctx, start, n, views, initial); const DWORD error = GetLastError();
    logf_line("CSSetUnorderedAccessViews ctx=%p start=%u count=%u", static_cast<void*>(ctx), start, n);
    trace_uavs(ctx, true, start, n, views); SetLastError(error);
}

static void STDMETHODCALLTYPE hook_CopyResource(ID3D11DeviceContext* ctx, ID3D11Resource* dst, ID3D11Resource* src)
{
    const auto call = original<TraceABI::Copy>(&(*(void***)ctx)[47]);
    if (!call) { logf_line("ERROR: missing copy original"); return; }
    const DWORD error = GetLastError(); trace_copy(ctx, "CopyResource", dst, src); SetLastError(error);
    call(ctx, dst, src);
}

static void STDMETHODCALLTYPE hook_CopySubresourceRegion(ID3D11DeviceContext* ctx, ID3D11Resource* dst, UINT dsub,
    UINT x, UINT y, UINT z, ID3D11Resource* src, UINT ssub, const D3D11_BOX* box)
{
    const auto call = original<TraceABI::CopyRegion>(&(*(void***)ctx)[46]);
    if (!call) { logf_line("ERROR: missing region copy original"); return; }
    const DWORD error = GetLastError(); const auto event = trace_copy(ctx, "CopySubresourceRegion", dst, src);
    logf_line("CopyRegionArgs copy_event=%llu dst_sub=%u xyz=%u,%u,%u src_sub=%u box=%d bounds=%u,%u,%u,%u,%u,%u", event,
        dsub, x, y, z, ssub, box != nullptr, box ? box->left : 0, box ? box->top : 0, box ? box->front : 0,
        box ? box->right : 0, box ? box->bottom : 0, box ? box->back : 0);
    SetLastError(error); call(ctx, dst, dsub, x, y, z, src, ssub, box);
}

static void STDMETHODCALLTYPE hook_ResolveSubresource(ID3D11DeviceContext* ctx, ID3D11Resource* dst, UINT dsub,
    ID3D11Resource* src, UINT ssub, DXGI_FORMAT format)
{
    const auto call = original<TraceABI::Resolve>(&(*(void***)ctx)[57]);
    if (!call) { logf_line("ERROR: missing resolve original"); return; }
    const DWORD error = GetLastError(); const auto event = trace_copy(ctx, "ResolveSubresource", dst, src);
    logf_line("ResolveArgs copy_event=%llu dst_sub=%u src_sub=%u format=%u", event, dsub, ssub, static_cast<unsigned>(format));
    SetLastError(error); call(ctx, dst, dsub, src, ssub, format);
}

static void STDMETHODCALLTYPE hook_Draw(ID3D11DeviceContext* ctx, UINT count, UINT start)
{
    const auto call = original<TraceABI::Draw>(&(*(void***)ctx)[13]);
    if (!call) { logf_line("ERROR: missing draw original"); return; }
    DrawScope scope(ctx, "Draw"); call(ctx, count, start);
}
static void STDMETHODCALLTYPE hook_DrawIndexed(ID3D11DeviceContext* ctx, UINT count, UINT start, INT base)
{
    const auto call = original<TraceABI::DrawIndexed>(&(*(void***)ctx)[12]);
    if (!call) { logf_line("ERROR: missing indexed draw original"); return; }
    DrawScope scope(ctx, "DrawIndexed"); call(ctx, count, start, base);
}
static void STDMETHODCALLTYPE hook_DrawInstanced(ID3D11DeviceContext* ctx, UINT count, UINT instances, UINT start, UINT first)
{
    const auto call = original<TraceABI::DrawInstanced>(&(*(void***)ctx)[21]);
    if (!call) { logf_line("ERROR: missing instanced draw original"); return; }
    DrawScope scope(ctx, "DrawInstanced"); call(ctx, count, instances, start, first);
}
static void STDMETHODCALLTYPE hook_DrawIndexedInstanced(ID3D11DeviceContext* ctx, UINT count, UINT instances, UINT start, INT base, UINT first)
{
    const auto call = original<TraceABI::DrawIndexedInstanced>(&(*(void***)ctx)[20]);
    if (!call) { logf_line("ERROR: missing indexed instanced draw original"); return; }
    DrawScope scope(ctx, "DrawIndexedInstanced"); call(ctx, count, instances, start, base, first);
}

static void STDMETHODCALLTYPE hook_Dispatch(ID3D11DeviceContext* ctx, UINT x, UINT y, UINT z)
{
    const auto call = original<TraceABI::Dispatch>(&(*(void***)ctx)[41]);
    if (!call) { logf_line("ERROR: missing dispatch original"); return; }
    const DWORD error = GetLastError();
    logf_line("Dispatch-entry ctx=%p groups=%u,%u,%u", static_cast<void*>(ctx), x, y, z);
    if (ctx->GetType() == D3D11_DEVICE_CONTEXT_IMMEDIATE) {
        trace_srvs(ctx, true, 0, 2, nullptr); trace_uavs(ctx, true, 0, 3, nullptr);
    }
    SetLastError(error); call(ctx, x, y, z);
}
static void STDMETHODCALLTYPE hook_ClearState(ID3D11DeviceContext* ctx)
{
    const auto call = original<TraceABI::Clear>(&(*(void***)ctx)[110]);
    if (!call) { logf_line("ERROR: missing clear original"); return; }
    call(ctx); const DWORD error = GetLastError();
    logf_line("ClearState ctx=%p", static_cast<void*>(ctx)); SetLastError(error);
}
static void STDMETHODCALLTYPE hook_ExecuteCommandList(ID3D11DeviceContext* ctx, ID3D11CommandList* list, BOOL restore)
{
    const auto call = original<TraceABI::Execute>(&(*(void***)ctx)[58]);
    if (!call) { logf_line("ERROR: missing execute original"); return; }
    const DWORD error = GetLastError();
    logf_line("ExecuteCommandList ctx=%p list=%p restore=%d", static_cast<void*>(ctx), static_cast<void*>(list), restore);
    SetLastError(error); call(ctx, list, restore);
}
static HRESULT STDMETHODCALLTYPE hook_FinishCommandList(ID3D11DeviceContext* ctx, BOOL restore, ID3D11CommandList** out)
{
    const auto call = original<TraceABI::Finish>(&(*(void***)ctx)[114]);
    if (!call) { logf_line("ERROR: missing finish original"); return E_FAIL; }
    const HRESULT hr = call(ctx, restore, out); const DWORD error = GetLastError();
    logf_line("FinishCommandList ctx=%p list=%p restore=%d hr=0x%08lX", static_cast<void*>(ctx),
        SUCCEEDED(hr) && out ? static_cast<void*>(*out) : nullptr, restore, static_cast<unsigned long>(hr));
    SetLastError(error); return hr;
}

static HRESULT STDMETHODCALLTYPE hook_CreateTexture2D(ID3D11Device* dev, const D3D11_TEXTURE2D_DESC* d,
    const D3D11_SUBRESOURCE_DATA* init, ID3D11Texture2D** out)
{
    const auto call = original<CreateTexture2D_t>(&(*(void***)dev)[5]);
    if (!call) { logf_line("ERROR: missing texture original; capture invalid"); return E_FAIL; }
    const HRESULT hr = call(dev, d, init, out);
    const DWORD error = GetLastError();
    const auto info = resource_info(SUCCEEDED(hr) && out ? *out : nullptr);
    if (d)
        logf_line("CreateTexture2D dev=%p texture=%p id=%p hr=0x%08lX w=%u h=%u mips=%u array=%u fmt=%u samples=%u quality=%u usage=%s bind=0x%X cpu=0x%X misc=0x%X",
            static_cast<void*>(dev), SUCCEEDED(hr) && out ? static_cast<void*>(*out) : nullptr, info.identity,
            static_cast<unsigned long>(hr), d->Width, d->Height, d->MipLevels, d->ArraySize,
            d->Format, d->SampleDesc.Count, d->SampleDesc.Quality, usage_name(d->Usage),
            d->BindFlags, d->CPUAccessFlags, d->MiscFlags);
    else logf_line("CreateTexture2D null descriptor hr=0x%08lX", static_cast<unsigned long>(hr));
    SetLastError(error);
    return hr;
}

static void STDMETHODCALLTYPE hook_RSSetViewports(ID3D11DeviceContext* ctx, UINT n, const D3D11_VIEWPORT* vp)
{
    const auto call = original<RSSetViewports_t>(&(*(void***)ctx)[44]);
    if (!call) { logf_line("ERROR: missing viewport original; capture invalid"); return; }
    call(ctx, n, vp);
    const DWORD error = GetLastError();
    logf_line("RSSetViewports ctx=%p count=%u", static_cast<void*>(ctx), n);
    if (vp && n <= D3D11_VIEWPORT_AND_SCISSORRECT_OBJECT_COUNT_PER_PIPELINE)
        for (UINT i = 0; i < n; ++i)
            logf_line("RSSetViewports ctx=%p [%u/%u] x=%.1f y=%.1f w=%.1f h=%.1f minz=%.3f maxz=%.3f",
                static_cast<void*>(ctx), i, n, vp[i].TopLeftX, vp[i].TopLeftY, vp[i].Width, vp[i].Height, vp[i].MinDepth, vp[i].MaxDepth);
    SetLastError(error);
}

static void install_hooks(ID3D11Device* dev, ID3D11DeviceContext* ctx);

static HRESULT STDMETHODCALLTYPE hook_CreateDeferredContext(ID3D11Device* dev, UINT flags, ID3D11DeviceContext** out)
{
    const auto call = original<CreateDeferredContext_t>(&(*(void***)dev)[27]);
    if (!call) { logf_line("ERROR: missing deferred-context original; capture invalid"); return E_FAIL; }
    const HRESULT hr = call(dev, flags, out);
    const DWORD error = GetLastError();
    if (SUCCEEDED(hr) && out) install_hooks(nullptr, *out);
    SetLastError(error);
    return hr;
}

static void install_hooks(ID3D11Device* dev, ID3D11DeviceContext* ctx)
{
    if (dev) {
        void** table = *(void***)dev;
        const bool texture = hooks.install(&table[5], reinterpret_cast<void*>(&hook_CreateTexture2D), patch_slot);
        const bool deferred = hooks.install(&table[27], reinterpret_cast<void*>(&hook_CreateDeferredContext), patch_slot);
        logf_line("Device hooks dev=%p texture=%d deferred=%d", static_cast<void*>(dev), texture, deferred);
    }
    if (ctx) {
        void** table = *(void***)ctx;
        const bool viewport = hooks.install(&table[44], reinterpret_cast<void*>(&hook_RSSetViewports), patch_slot);
        logf_line("Context hook ctx=%p type=%u viewport_slot=44 installed=%d; newer deferred APIs unverified",
            static_cast<void*>(ctx), static_cast<unsigned>(ctx->GetType()), viewport);
        struct Patch { size_t slot; void* callback; const char* name; };
        const Patch patches[] = {
            {8, reinterpret_cast<void*>(&hook_PSSetShaderResources), "PSSetShaderResources"},
            {67, reinterpret_cast<void*>(&hook_CSSetShaderResources), "CSSetShaderResources"},
            {33, reinterpret_cast<void*>(&hook_OMSetRenderTargets), "OMSetRenderTargets"},
            {34, reinterpret_cast<void*>(&hook_OMSetRenderTargetsAndUnorderedAccessViews), "OMSetRenderTargetsAndUnorderedAccessViews"},
            {68, reinterpret_cast<void*>(&hook_CSSetUnorderedAccessViews), "CSSetUnorderedAccessViews"},
            {47, reinterpret_cast<void*>(&hook_CopyResource), "CopyResource"},
            {46, reinterpret_cast<void*>(&hook_CopySubresourceRegion), "CopySubresourceRegion"},
            {57, reinterpret_cast<void*>(&hook_ResolveSubresource), "ResolveSubresource"},
            {13, reinterpret_cast<void*>(&hook_Draw), "Draw"},
            {12, reinterpret_cast<void*>(&hook_DrawIndexed), "DrawIndexed"},
            {21, reinterpret_cast<void*>(&hook_DrawInstanced), "DrawInstanced"},
            {20, reinterpret_cast<void*>(&hook_DrawIndexedInstanced), "DrawIndexedInstanced"},
            {41, reinterpret_cast<void*>(&hook_Dispatch), "Dispatch"},
            {110, reinterpret_cast<void*>(&hook_ClearState), "ClearState"},
            {58, reinterpret_cast<void*>(&hook_ExecuteCommandList), "ExecuteCommandList"},
            {114, reinterpret_cast<void*>(&hook_FinishCommandList), "FinishCommandList"},
        };
        for (const auto& patch : patches) {
            const bool ok = hooks.install(&table[patch.slot], patch.callback, patch_slot);
            logf_line("%sResourceHook ctx=%p name=%s slot=%zu installed=%d", ok ? "" : "ERROR: ",
                static_cast<void*>(ctx), patch.name, patch.slot, ok);
        }
    }
}

static void observe_outputs(ID3D11Device* dev, ID3D11DeviceContext* ctx, IDXGISwapChain* swap)
{
    ID3D11Device* owned_dev = nullptr;
    ID3D11DeviceContext* owned_ctx = nullptr;
    if (!dev && ctx) ctx->GetDevice(&owned_dev);
    if (!dev && !owned_dev && swap)
        swap->GetDevice(__uuidof(ID3D11Device), reinterpret_cast<void**>(&owned_dev));
    if (!dev) dev = owned_dev;
    if (dev && !ctx) { dev->GetImmediateContext(&owned_ctx); ctx = owned_ctx; }
    install_hooks(dev, ctx);
    if (owned_ctx) owned_ctx->Release();
    if (owned_dev) owned_dev->Release();
}

static bool load_real()
{
    static const bool ready = [] {
        HMODULE self = nullptr;
        if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_PIN,
                reinterpret_cast<LPCWSTR>(&load_real), &self)) return false;
        wchar_t path[32768];
        const DWORD length = GetModuleFileNameW(self, path, 32768);
        if (!length || length >= 32768) return false;
        wchar_t* filename = wcsrchr(path, L'\\');
        if (!filename) return false;
        const std::wstring next = std::wstring(path, filename + 1) + L"d3d11_dlaa.dll";
        real_d3d11 = LoadLibraryExW(next.c_str(), nullptr,
            LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
        if (!real_d3d11 || real_d3d11 == self) return false;
        FARPROC create = GetProcAddress(real_d3d11, "D3D11CreateDevice");
        FARPROC swap = GetProcAddress(real_d3d11, "D3D11CreateDeviceAndSwapChain");
        static_assert(sizeof(create) == sizeof(real_CreateDevice));
        std::memcpy(&real_CreateDevice, &create, sizeof(create));
        std::memcpy(&real_CreateDeviceAndSwapChain, &swap, sizeof(swap));
        const bool ok = create && swap;
        logf_line("Next-stage module=%p exports_ready=%d; no system fallback", static_cast<void*>(real_d3d11), ok);
        return ok;
    }();
    return ready;
}

extern "C" HRESULT WINAPI D3D11CreateDevice(IDXGIAdapter* adapter, D3D_DRIVER_TYPE type, HMODULE sw,
    UINT flags, const D3D_FEATURE_LEVEL* levels, UINT nlevels, UINT sdk, ID3D11Device** outdev,
    D3D_FEATURE_LEVEL* outfl, ID3D11DeviceContext** outctx)
{
    if (!load_real()) return E_FAIL;
    const HRESULT hr = real_CreateDevice(adapter, type, sw, flags, levels, nlevels, sdk, outdev, outfl, outctx);
    const DWORD error = GetLastError();
    logf_line("D3D11CreateDevice hr=0x%08lX", static_cast<unsigned long>(hr));
    if (SUCCEEDED(hr)) observe_outputs(outdev ? *outdev : nullptr, outctx ? *outctx : nullptr, nullptr);
    SetLastError(error);
    return hr;
}

extern "C" HRESULT WINAPI D3D11CreateDeviceAndSwapChain(IDXGIAdapter* adapter, D3D_DRIVER_TYPE type,
    HMODULE sw, UINT flags, const D3D_FEATURE_LEVEL* levels, UINT nlevels, UINT sdk,
    const DXGI_SWAP_CHAIN_DESC* sd, IDXGISwapChain** outsc, ID3D11Device** outdev,
    D3D_FEATURE_LEVEL* outfl, ID3D11DeviceContext** outctx)
{
    if (!load_real()) return E_FAIL;
    const HRESULT hr = real_CreateDeviceAndSwapChain(adapter, type, sw, flags, levels, nlevels, sdk, sd, outsc, outdev, outfl, outctx);
    const DWORD error = GetLastError();
    logf_line("D3D11CreateDeviceAndSwapChain hr=0x%08lX", static_cast<unsigned long>(hr));
    if (SUCCEEDED(hr)) observe_outputs(outdev ? *outdev : nullptr, outctx ? *outctx : nullptr, outsc ? *outsc : nullptr);
    SetLastError(error);
    return hr;
}
