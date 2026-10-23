#pragma once
#include <d3d11.h>

// Shared with the SDK compile check so trace callbacks cannot drift from COM ABI.
namespace TraceABI {
using SetSRVs = void (STDMETHODCALLTYPE *)(ID3D11DeviceContext*, UINT, UINT, ID3D11ShaderResourceView* const*);
using SetRTs = void (STDMETHODCALLTYPE *)(ID3D11DeviceContext*, UINT, ID3D11RenderTargetView* const*, ID3D11DepthStencilView*);
using SetRTsUAVs = void (STDMETHODCALLTYPE *)(ID3D11DeviceContext*, UINT, ID3D11RenderTargetView* const*, ID3D11DepthStencilView*, UINT, UINT, ID3D11UnorderedAccessView* const*, const UINT*);
using SetUAVs = void (STDMETHODCALLTYPE *)(ID3D11DeviceContext*, UINT, UINT, ID3D11UnorderedAccessView* const*, const UINT*);
using Copy = void (STDMETHODCALLTYPE *)(ID3D11DeviceContext*, ID3D11Resource*, ID3D11Resource*);
using CopyRegion = void (STDMETHODCALLTYPE *)(ID3D11DeviceContext*, ID3D11Resource*, UINT, UINT, UINT, UINT, ID3D11Resource*, UINT, const D3D11_BOX*);
using Resolve = void (STDMETHODCALLTYPE *)(ID3D11DeviceContext*, ID3D11Resource*, UINT, ID3D11Resource*, UINT, DXGI_FORMAT);
using Draw = void (STDMETHODCALLTYPE *)(ID3D11DeviceContext*, UINT, UINT);
using DrawIndexed = void (STDMETHODCALLTYPE *)(ID3D11DeviceContext*, UINT, UINT, INT);
using DrawInstanced = void (STDMETHODCALLTYPE *)(ID3D11DeviceContext*, UINT, UINT, UINT, UINT);
using DrawIndexedInstanced = void (STDMETHODCALLTYPE *)(ID3D11DeviceContext*, UINT, UINT, UINT, INT, UINT);
using Dispatch = void (STDMETHODCALLTYPE *)(ID3D11DeviceContext*, UINT, UINT, UINT);
using Clear = void (STDMETHODCALLTYPE *)(ID3D11DeviceContext*);
using Execute = void (STDMETHODCALLTYPE *)(ID3D11DeviceContext*, ID3D11CommandList*, BOOL);
using Finish = HRESULT (STDMETHODCALLTYPE *)(ID3D11DeviceContext*, BOOL, ID3D11CommandList**);
}
