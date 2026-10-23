// Compile only: validates RE offset interpretations without running Windows/GPU code.
#define CINTERFACE
#include <d3d11.h>
#include <cstddef>
#include <type_traits>
#include "d3d11_trace_abi.h"

static_assert(sizeof(void*) == 8);
static_assert(offsetof(ID3D11DeviceVtbl, CreateTexture2D) == 5 * sizeof(void*));
static_assert(offsetof(ID3D11DeviceVtbl, CreateDeferredContext) == 27 * sizeof(void*));
static_assert(offsetof(ID3D11DeviceVtbl, GetImmediateContext) == 40 * sizeof(void*));
static_assert(offsetof(ID3D11DeviceContextVtbl, Draw) == 13 * sizeof(void*));
static_assert(offsetof(ID3D11DeviceContextVtbl, DrawInstancedIndirect) == 40 * sizeof(void*));
static_assert(offsetof(ID3D11DeviceContextVtbl, RSSetViewports) == 44 * sizeof(void*));
static_assert(offsetof(ID3D11DeviceContextVtbl, CopyResource) == 0x178);
static_assert(offsetof(ID3D11DeviceContextVtbl, PSGetShaderResources) == 0x248);
static_assert(offsetof(ID3D11DeviceContextVtbl, PSGetShader) == 0x250);
static_assert(offsetof(ID3D11DeviceContextVtbl, GetType) == 0x380);

using ViewportCallback = void (STDMETHODCALLTYPE *)(ID3D11DeviceContext*, UINT, const D3D11_VIEWPORT*);
static_assert(std::is_same_v<decltype(ID3D11DeviceContextVtbl::RSSetViewports), ViewportCallback>);
static_assert(!std::is_same_v<decltype(ID3D11DeviceContextVtbl::DrawInstancedIndirect), ViewportCallback>);

static_assert(sizeof(D3D11_TEXTURE2D_DESC) == 44);
static_assert(offsetof(D3D11_TEXTURE2D_DESC, Format) == 16);
static_assert(offsetof(D3D11_TEXTURE2D_DESC, SampleDesc) == 20);
static_assert(offsetof(D3D11_TEXTURE2D_DESC, Usage) == 28);
static_assert(offsetof(D3D11_TEXTURE2D_DESC, BindFlags) == 32);
static_assert(offsetof(D3D11_TEXTURE2D_DESC, CPUAccessFlags) == 36);
static_assert(offsetof(D3D11_TEXTURE2D_DESC, MiscFlags) == 40);
static_assert(DXGI_FORMAT_R16G16_FLOAT == 0x22);
static_assert(DXGI_FORMAT_R32_FLOAT == 0x29);
static_assert(DXGI_FORMAT_R16G16B16A16_FLOAT == 10);
static_assert(D3D11_USAGE_DEFAULT == 0);
static_assert((D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS) == 0x88);

#define TRACE_ABI(method, slot, type) \
    static_assert(offsetof(ID3D11DeviceContextVtbl, method) == slot * sizeof(void*)); \
    static_assert(std::is_same_v<decltype(ID3D11DeviceContextVtbl::method), TraceABI::type>)
TRACE_ABI(PSSetShaderResources, 8, SetSRVs);
TRACE_ABI(CSSetShaderResources, 67, SetSRVs);
TRACE_ABI(OMSetRenderTargets, 33, SetRTs);
TRACE_ABI(OMSetRenderTargetsAndUnorderedAccessViews, 34, SetRTsUAVs);
TRACE_ABI(CSSetUnorderedAccessViews, 68, SetUAVs);
TRACE_ABI(CopyResource, 47, Copy);
TRACE_ABI(CopySubresourceRegion, 46, CopyRegion);
TRACE_ABI(ResolveSubresource, 57, Resolve);
TRACE_ABI(Draw, 13, Draw);
TRACE_ABI(DrawIndexed, 12, DrawIndexed);
TRACE_ABI(DrawInstanced, 21, DrawInstanced);
TRACE_ABI(DrawIndexedInstanced, 20, DrawIndexedInstanced);
TRACE_ABI(Dispatch, 41, Dispatch);
TRACE_ABI(ClearState, 110, Clear);
TRACE_ABI(ExecuteCommandList, 58, Execute);
TRACE_ABI(FinishCommandList, 114, Finish);
#undef TRACE_ABI

static_assert(offsetof(IDXGISwapChainVtbl, Present) == 8 * sizeof(void*));
static_assert(offsetof(IDXGISwapChainVtbl, GetDesc) == 12 * sizeof(void*));
static_assert(offsetof(IDXGISwapChainVtbl, ResizeBuffers) == 13 * sizeof(void*));
static_assert(offsetof(DXGI_SWAP_CHAIN_DESC, BufferDesc) == 0);
static_assert(offsetof(DXGI_MODE_DESC, Width) == 0 && offsetof(DXGI_MODE_DESC, Height) == 4);
